import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from helper import get_array_type, to_float
from pipeline.forms import VideoProjectSubmissionForm
from pipeline.models import VideoJob
from pipeline.tasks import run_video_pipeline, update_env_variable


class VideoJobModelTests(TestCase):
    def test_new_job_uses_pending_defaults(self):
        job = VideoJob.objects.create(file_name="sample")

        self.assertEqual(job.status, "pending")
        self.assertEqual(job.progress, 0)
        self.assertEqual(job.current_script, "")


class EnvironmentUpdateTests(TestCase):
    def test_update_env_variable_replaces_value_without_losing_other_keys(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("FILE_NAME=old\nMUSIC=4\n", encoding="utf-8")

            update_env_variable("FILE_NAME", "new", env_path)

            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "FILE_NAME=new\nMUSIC=4\n",
            )

    def test_update_env_variable_adds_missing_key(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"

            update_env_variable("FPS", "30", env_path)

            self.assertEqual(env_path.read_text(encoding="utf-8"), "FPS=30\n")


class PipelineRunnerTests(TestCase):
    @patch("pipeline.tasks.subprocess.run")
    @patch("pipeline.tasks.update_env_variable")
    def test_first_pipeline_step_uses_current_python_without_sys_shadowing(
        self, update_env_mock, subprocess_run_mock
    ):
        subprocess_run_mock.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="expected test stop",
        )
        job = VideoJob.objects.create(file_name="runner_test")

        run_video_pipeline(job.id, fps="30")

        command = subprocess_run_mock.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        update_env_mock.assert_any_call("FILE_NAME", "runner_test", update_env_mock.call_args_list[0].args[2])

    @patch("pipeline.tasks.subprocess.run")
    @patch("pipeline.tasks.update_env_variable")
    def test_retry_starts_at_requested_failed_script(self, update_env_mock, subprocess_run_mock):
        subprocess_run_mock.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="expected test stop",
        )
        job = VideoJob.objects.create(
            file_name="retry_runner",
            current_script="prepare_captions.py",
            status="failed",
        )

        run_video_pipeline(job.id, fps="24", start_script="prepare_captions.py")

        command = subprocess_run_mock.call_args.args[0]
        self.assertTrue(str(command[1]).endswith("prepare_captions.py"))
        self.assertNotIn("generate_voiceover_with_timing.py", str(command))


class HelperTests(TestCase):
    def test_array_type_detection(self):
        self.assertEqual(get_array_type([1, 2]), "integers")
        self.assertEqual(get_array_type(["one", "two"]), "strings")
        self.assertEqual(get_array_type([1, "two"]), "Mixed")

    def test_to_float_uses_default_for_invalid_value(self):
        self.assertEqual(to_float("invalid", default=24), 24.0)


class VideoProjectSubmissionFormTests(TestCase):
    def make_form(self, **overrides):
        data = {
            "file_name": "new_project",
            "fps": 30,
            "scenes_json": json.dumps([
                {"narration": "First scene.", "prompt": "First visual."},
                {"narration": "Second scene.", "prompt": "Second visual."},
            ]),
        }
        data.update(overrides)
        return VideoProjectSubmissionForm(data=data)

    def test_accepts_valid_scene_and_prompt_input(self):
        self.assertTrue(self.make_form().is_valid())

    def test_rejects_unsafe_project_name(self):
        form = self.make_form(file_name="../outside")

        self.assertFalse(form.is_valid())
        self.assertIn("file_name", form.errors)

    def test_rejects_invalid_json(self):
        form = self.make_form(scenes_json="not-json")

        self.assertFalse(form.is_valid())
        self.assertIn("could not be read", form.errors["scenes_json"][0])

    def test_requires_narration_and_prompt_for_every_scene(self):
        form = self.make_form(scenes_json=json.dumps([
            {"narration": "", "prompt": "A visual"},
        ]))

        self.assertFalse(form.is_valid())
        self.assertIn("needs narration", form.errors["scenes_json"][0])

    def test_rejects_unsupported_upload_extension(self):
        upload = SimpleUploadedFile("payload.exe", b"not media")
        form = VideoProjectSubmissionForm(
            data=self.make_form().data,
            files={"media_0": upload},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("supported image or video", form.non_field_errors()[0])

    def test_rejects_existing_project_name(self):
        VideoJob.objects.create(file_name="new_project")

        form = self.make_form()

        self.assertFalse(form.is_valid())
        self.assertIn("already exists", form.errors["file_name"][0])


class GuidedCreatorViewTests(TestCase):
    def test_home_page_hides_legacy_json_and_marker_inputs(self):
        response = self.client.get("/")

        self.assertContains(response, "Build your scenes")
        self.assertNotContains(response, "JSON Content")
        self.assertNotContains(response, "### markers")

    def test_submission_generates_legacy_files_on_backend(self):
        scenes = [
            {"narration": "Opening words.", "prompt": "A sunrise over a quiet city."},
            {"narration": "Closing words.", "prompt": "The city glowing at night."},
        ]
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            with patch("pipeline.views.threading.Thread") as thread_class:
                response = self.client.post(
                    "/",
                    {
                        "file_name": "guided_project",
                        "fps": 30,
                        "scenes_json": json.dumps(scenes),
                    },
                )

            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                (Path(directory) / "scripts" / "guided_project.txt").read_text(encoding="utf-8"),
                "Opening words. ### Closing words.",
            )
            saved_prompts = json.loads(
                (Path(directory) / "prompts" / "guided_project.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                saved_prompts,
                [
                    {"filename": "scene_01.png", "prompt": scenes[0]["prompt"]},
                    {"filename": "scene_02.png", "prompt": scenes[1]["prompt"]},
                ],
            )
            thread_class.assert_called_once()
            thread_class.return_value.start.assert_called_once()


class JobDetailActionsTests(TestCase):
    def test_completed_job_page_contains_inline_player_and_download(self):
        job = VideoJob.objects.create(file_name="finished", status="completed")

        response = self.client.get(f"/job/{job.id}/")

        self.assertContains(response, f'/watch/{job.id}/')
        self.assertContains(response, f'/download/{job.id}/')
        self.assertContains(response, "Your video is ready")

    def test_watch_video_serves_completed_output_inline(self):
        job = VideoJob.objects.create(file_name="watchable", status="completed")
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            output_dir = Path(directory) / "output"
            output_dir.mkdir()
            (output_dir / "watchable.mp4").write_bytes(b"fake mp4 bytes")

            response = self.client.get(f"/watch/{job.id}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "video/mp4")
            self.assertTrue(response["Content-Disposition"].startswith("inline;"))
            response.close()

    @patch("pipeline.views.threading.Thread")
    def test_failed_job_can_retry_from_recorded_step(self, thread_class):
        job = VideoJob.objects.create(
            file_name="failed_job",
            fps=24,
            status="failed",
            current_script="generate_images_runaware.py",
            log="original failure\n",
        )

        response = self.client.post(f"/job/{job.id}/retry/")

        self.assertRedirects(response, f"/job/{job.id}/")
        job.refresh_from_db()
        self.assertEqual(job.status, "pending")
        self.assertIn("Re-running from generate_images_runaware.py", job.log)
        thread_class.assert_called_once_with(
            target=run_video_pipeline,
            args=(job.id, "24", "generate_images_runaware.py"),
            daemon=True,
        )
        thread_class.return_value.start.assert_called_once()

    def test_retry_is_not_available_for_completed_job(self):
        job = VideoJob.objects.create(
            file_name="already_done",
            status="completed",
            current_script="create_video.py",
        )

        response = self.client.post(f"/job/{job.id}/retry/")

        self.assertEqual(response.status_code, 404)
