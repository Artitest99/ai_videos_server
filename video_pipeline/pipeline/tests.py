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
from pipeline.models import VideoEditRevision, VideoJob
from pipeline.tasks import run_video_pipeline, update_env_variable
import prepare_images


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
        self.assertContains(response, f'/job/{job.id}/edit/')
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


class ExistingVideoEditorTests(TestCase):
    def create_legacy_project(self, base_dir, name="editable"):
        base_dir = Path(base_dir)
        (base_dir / "scripts").mkdir(parents=True)
        (base_dir / "prompts").mkdir(parents=True)
        (base_dir / "captions").mkdir(parents=True)
        media_dir = base_dir / "assets" / "media" / name
        media_dir.mkdir(parents=True)
        (base_dir / "scripts" / f"{name}.txt").write_text(
            "Hello world ### Goodbye moon", encoding="utf-8"
        )
        (base_dir / "prompts" / f"{name}.json").write_text(
            json.dumps([
                {"filename": "scene_01.png", "prompt": "First visual"},
                {"filename": "scene_02.png", "prompt": "Second visual"},
            ]), encoding="utf-8"
        )
        captions = [
            {"text": "Hello world", "text_bold": ["Hello"], "start": 0, "end": .5, "media_transition": False},
            {"text": "Hello world", "text_bold": ["world"], "start": .5, "end": 1, "media_transition": True},
            {"text": "Goodbye moon", "text_bold": ["Goodbye"], "start": 1, "end": 1.5, "media_transition": False},
            {"text": "Goodbye moon", "text_bold": ["moon"], "start": 1.5, "end": 2, "media_transition": False},
        ]
        (base_dir / "captions" / f"captions_{name}.json").write_text(json.dumps(captions), encoding="utf-8")
        (media_dir / "0.png").write_bytes(b"old image zero")
        (media_dir / "1.png").write_bytes(b"old image one")
        return media_dir

    def test_completed_project_opens_as_scene_editor(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            self.create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.get(f"/job/{job.id}/edit/")

        self.assertContains(response, "Scene 1")
        self.assertContains(response, "Hello world")
        self.assertContains(response, "First visual")
        self.assertContains(response, "On-screen subtitles")

    def test_subtitle_and_prompt_edits_create_revision_without_changing_script(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            self.create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "prompt_0": "Changed first visual",
                "subtitle_0": "Hallo world",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            job.refresh_from_db()
            self.assertEqual(job.current_revision, 1)
            self.assertTrue(job.render_required)
            self.assertEqual(VideoEditRevision.objects.filter(job=job).count(), 1)
            self.assertEqual(
                (Path(directory) / "scripts" / "editable.txt").read_text(encoding="utf-8"),
                "Hello world ### Goodbye moon",
            )
            prompts = json.loads((Path(directory) / "prompts" / "editable.json").read_text(encoding="utf-8"))
            captions = json.loads((Path(directory) / "captions" / "captions_editable.json").read_text(encoding="utf-8"))
            self.assertEqual(prompts[0]["prompt"], "Changed first visual")
            self.assertEqual(captions[0]["text_bold"], ["Hallo"])
            self.assertEqual(captions[0]["start"], 0)
            self.assertEqual(job.render_start_script, "generate_images_runaware.py")

    def test_replacing_media_preserves_old_asset_in_revision_history(self):
        replacement = SimpleUploadedFile("replacement.jpg", b"new image")
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            media_dir = self.create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "prompt_0": "First visual",
                "subtitle_0": "Hello world",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
                "media_0": replacement,
            })

            self.assertEqual(response.status_code, 302)
            self.assertEqual((media_dir / "0.jpg").read_bytes(), b"new image")
            self.assertEqual(
                (media_dir / "history" / "revision_001" / "0.png").read_bytes(),
                b"old image zero",
            )
            self.assertFalse((media_dir / "0.png").exists())

    def test_subtitle_edit_rejects_word_count_change(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            self.create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "prompt_0": "First visual",
                "subtitle_0": "One extra word",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must keep 2 subtitle words")
        job.refresh_from_db()
        self.assertEqual(job.current_revision, 0)

    def test_prompt_change_archives_stale_active_and_generated_images(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            media_dir = self.create_legacy_project(directory)
            ai_dir = media_dir / "ai"
            ai_dir.mkdir()
            (ai_dir / "0.png").write_bytes(b"stale generated image")
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "prompt_0": "A completely new first visual",
                "subtitle_0": "Hello world",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            job.refresh_from_db()
            self.assertEqual(job.render_start_script, "generate_images_runaware.py")
            self.assertFalse((media_dir / "0.png").exists())
            self.assertFalse((ai_dir / "0.png").exists())
            history = media_dir / "history" / "revision_001"
            self.assertEqual((history / "0.png").read_bytes(), b"old image zero")
            self.assertEqual((history / "ai" / "0.png").read_bytes(), b"stale generated image")

    @patch("pipeline.views.threading.Thread")
    def test_render_edits_backs_up_previous_output_and_starts_renderer(self, thread_class):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            output_dir = Path(directory) / "output"
            output_dir.mkdir()
            (output_dir / "editable.mp4").write_bytes(b"previous render")
            job = VideoJob.objects.create(
                file_name="editable", fps=24, status="completed",
                current_revision=2, rendered_revision=1, render_required=True,
            )

            response = self.client.post(f"/job/{job.id}/edit/render/")

            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                (output_dir / "history" / str(job.id) / "revision_001.mp4").read_bytes(),
                b"previous render",
            )
            thread_class.assert_called_once_with(
                target=run_video_pipeline,
                args=(job.id, "24", "create_video.py"),
                daemon=True,
            )

    @patch("pipeline.views.threading.Thread")
    def test_render_after_prompt_change_starts_at_image_generation(self, thread_class):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            output_dir = Path(directory) / "output"
            output_dir.mkdir()
            (output_dir / "editable.mp4").write_bytes(b"previous render")
            job = VideoJob.objects.create(
                file_name="editable", fps=30, status="completed",
                current_revision=1, render_required=True,
                render_start_script="generate_images_runaware.py",
            )

            response = self.client.post(f"/job/{job.id}/edit/render/")

        self.assertEqual(response.status_code, 302)
        thread_class.assert_called_once_with(
            target=run_video_pipeline,
            args=(job.id, "30", "generate_images_runaware.py"),
            daemon=True,
        )


class GeneratedMediaPromotionTests(TestCase):
    def test_promotes_only_missing_scene_indexes(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "media"
            ai_dir = output_dir / "ai"
            ai_dir.mkdir(parents=True)
            (output_dir / "0.png").write_bytes(b"keep uploaded scene")
            (ai_dir / "0.png").write_bytes(b"unused generated scene")
            (ai_dir / "1.png").write_bytes(b"new generated scene")

            with patch.object(prepare_images, "OUTPUT_DIR", output_dir), patch.object(prepare_images, "AI_OUTPUT_DIR", ai_dir):
                prepare_images.promote_missing_generated_media()

            self.assertEqual((output_dir / "0.png").read_bytes(), b"keep uploaded scene")
            self.assertEqual((output_dir / "1.png").read_bytes(), b"new generated scene")
