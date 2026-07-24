import json
import numpy as np
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from moviepy.editor import AudioClip, CompositeAudioClip, ImageClip
from django.test import TestCase, override_settings

from helper import get_array_type, to_float
from pipeline.forms import VideoProjectSubmissionForm
from pipeline.models import BackgroundMusicAsset, VideoEditRevision, VideoJob
from pipeline.tasks import run_video_pipeline, update_env_variable
import prepare_images
from create_video import VideoGenerator
from voice_config import DEFAULT_VOICE_KEY, VOICES, resolve_voice_id
from pipeline.voice_samples import VOICE_SAMPLE_TEXT


class VideoJobModelTests(TestCase):
    def test_new_job_uses_pending_defaults(self):
        job = VideoJob.objects.create(file_name="sample")

        self.assertEqual(job.status, "pending")
        self.assertEqual(job.progress, 0)
        self.assertEqual(job.current_script, "")
        self.assertEqual(job.voice_key, DEFAULT_VOICE_KEY)


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
        update_env_mock.assert_any_call("VOICE", DEFAULT_VOICE_KEY, update_env_mock.call_args_list[0].args[2])

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
            "music_track": "1",
            "scenes_json": json.dumps([
                {"narration": "First scene.", "prompt": "First visual."},
                {"narration": "Second scene.", "prompt": "Second visual."},
            ]),
        }
        data.update(overrides)
        return VideoProjectSubmissionForm(data=data)

    def test_accepts_valid_scene_and_prompt_input(self):
        self.assertTrue(self.make_form().is_valid())

    def test_accepts_a_supported_voice_and_rejects_an_unknown_voice(self):
        form = self.make_form(voice_key="George")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["voice_key"], "George")

        invalid_form = self.make_form(file_name="another_project", voice_key="not-a-real-voice")
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("voice_key", invalid_form.errors)

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

    def test_allows_empty_prompt_when_scene_has_uploaded_media(self):
        upload = SimpleUploadedFile("scene.png", b"image")
        form = VideoProjectSubmissionForm(
            data={
                "file_name": "uploaded_scene",
                "fps": 30,
                "music_track": "1",
                "scenes_json": json.dumps([{"narration": "Narration", "prompt": ""}]),
            },
            files={"media_0": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_requires_prompt_when_scene_has_no_upload(self):
        form = VideoProjectSubmissionForm(data={
            "file_name": "missing_visual",
            "fps": 30,
            "music_track": "1",
            "scenes_json": json.dumps([{"narration": "Narration", "prompt": ""}]),
        })

        self.assertFalse(form.is_valid())
        self.assertIn("visual description or an uploaded", form.errors["scenes_json"][0])

    def test_rejects_existing_project_name(self):
        VideoJob.objects.create(file_name="new_project")

        form = self.make_form()

        self.assertFalse(form.is_valid())
        self.assertIn("already exists", form.errors["file_name"][0])


class GuidedCreatorViewTests(TestCase):
    def test_home_page_hides_legacy_json_and_marker_inputs(self):
        response = self.client.get("/")

        self.assertContains(response, "Build your scenes")
        self.assertContains(response, "Eddie")
        self.assertContains(response, "Press play to hear")
        self.assertNotContains(response, "JSON Content")
        self.assertNotContains(response, "### markers")

    def test_submission_generates_legacy_files_on_backend(self):
        scenes = [
            {"narration": "Opening words.", "prompt": "A sunrise over a quiet city."},
            {"narration": "Closing words.", "prompt": "The city glowing at night."},
        ]
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets_dir = Path(directory) / "assets"
            assets_dir.mkdir()
            (assets_dir / "background_music_1.mp3").write_bytes(b"music")
            with patch("pipeline.views.threading.Thread") as thread_class:
                response = self.client.post(
                    "/",
                    {
                        "file_name": "guided_project",
                        "fps": 30,
                        "music_track": "1",
                        "voice_key": "George",
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
                    {
                        "filename": "scene_01.png", "prompt": scenes[0]["prompt"],
                        "narration": scenes[0]["narration"],
                        "use_original_audio": False, "fit_with_borders": False, "hold_after_seconds": 0.0,
                        "video_start_seconds": 0.0, "video_end_seconds": None,
                    },
                    {
                        "filename": "scene_02.png", "prompt": scenes[1]["prompt"],
                        "narration": scenes[1]["narration"],
                        "use_original_audio": False, "fit_with_borders": False, "hold_after_seconds": 0.0,
                        "video_start_seconds": 0.0, "video_end_seconds": None,
                    },
                ],
            )
            thread_class.assert_called_once()
            thread_class.return_value.start.assert_called_once()
            self.assertEqual(VideoJob.objects.get(file_name="guided_project").music_track, "1")
            self.assertEqual(VideoJob.objects.get(file_name="guided_project").voice_key, "George")


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
        (base_dir / "assets" / "background_music_1.mp3").write_bytes(b"music")
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

    def test_subtitles_can_be_cleared_for_one_scene(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            self.create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "music_track": "1",
                "prompt_0": "First visual",
                "subtitle_0": "",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            captions = json.loads(
                (Path(directory) / "captions" / "captions_editable.json").read_text(encoding="utf-8")
            )
            self.assertEqual([cue["text"] for cue in captions[:2]], ["", ""])
            self.assertEqual([cue["text_bold"] for cue in captions[:2]], [[], []])
            self.assertEqual(captions[2]["text"], "Goodbye moon")
            self.assertEqual(captions[3]["text"], "Goodbye moon")
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


class NarrationFreeSceneStructureTests(TestCase):
    def create_silent_project(self, base_dir, name="silent_edit"):
        base_dir = Path(base_dir)
        (base_dir / "scripts").mkdir(parents=True)
        (base_dir / "prompts").mkdir(parents=True)
        (base_dir / "captions").mkdir(parents=True)
        media = base_dir / "assets" / "media" / name
        media.mkdir(parents=True)
        (base_dir / "assets" / "background_music_1.mp3").write_bytes(b"music")
        (base_dir / "scripts" / f"{name}.txt").write_text(" ### ", encoding="utf-8")
        (base_dir / "prompts" / f"{name}.json").write_text(json.dumps([
            {"filename": "scene_01.png", "prompt": "First", "narration": "", "hold_after_seconds": 3, "use_original_audio": False},
            {"filename": "scene_02.png", "prompt": "Second", "narration": "", "hold_after_seconds": 4, "use_original_audio": False},
        ]), encoding="utf-8")
        (base_dir / "captions" / f"captions_{name}.json").write_text("[]", encoding="utf-8")
        (media / "0.png").write_bytes(b"first-media")
        (media / "1.png").write_bytes(b"second-media")
        return media

    def test_edit_page_offers_structure_controls_and_upload_preview(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            self.create_silent_project(directory)
            job = VideoJob.objects.create(file_name="silent_edit", status="completed")
            response = self.client.get(f"/job/{job.id}/edit/")

        self.assertContains(response, "Add scene")
        self.assertContains(response, "move-up")
        self.assertContains(response, "URL.createObjectURL")

    def test_reorders_existing_scenes_and_adds_uploaded_scene(self):
        upload = SimpleUploadedFile("added.jpg", b"new-media", content_type="image/jpeg")
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            media = self.create_silent_project(directory)
            job = VideoJob.objects.create(file_name="silent_edit", status="completed")
            response = self.client.post(f"/job/{job.id}/edit/", {
                "music_track": "1",
                "scene_order": json.dumps(["1", "0", "new_test"]),
                "prompt_1": "Second", "hold_after_seconds_1": "4",
                "prompt_0": "First", "hold_after_seconds_0": "3",
                "prompt_new_test": "Added", "hold_after_seconds_new_test": "5",
                "media_new_test": upload,
            })

            self.assertEqual(response.status_code, 302)
            prompts = json.loads((Path(directory) / "prompts" / "silent_edit.json").read_text(encoding="utf-8"))
            self.assertEqual([item["prompt"] for item in prompts], ["Second", "First", "Added"])
            self.assertEqual([item["hold_after_seconds"] for item in prompts], [4.0, 3.0, 5.0])
            self.assertEqual((media / "0.png").read_bytes(), b"second-media")
            self.assertEqual((media / "1.png").read_bytes(), b"first-media")
            self.assertEqual((media / "2.jpg").read_bytes(), b"new-media")
            self.assertEqual((Path(directory) / "captions" / "captions_silent_edit.json").read_text(encoding="utf-8"), "[]")
            job.refresh_from_db()
            self.assertTrue(job.render_required)

    def test_narrated_project_does_not_offer_structure_controls(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            ExistingVideoEditorTests().create_legacy_project(directory)
            job = VideoJob.objects.create(file_name="editable", status="completed")
            response = self.client.get(f"/job/{job.id}/edit/")

        self.assertNotContains(response, "Add scene")
        self.assertContains(response, "const narrationFree = false")

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


class MusicSelectionTests(TestCase):
    def test_music_preview_serves_available_asset(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets_dir = Path(directory) / "assets"
            assets_dir.mkdir()
            (assets_dir / "background_music_7.mp3").write_bytes(b"preview music")

            response = self.client.get("/music/7/")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "audio/mpeg")
            response.close()

    def test_editor_saves_selected_music_track(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            helper = ExistingVideoEditorTests()
            helper.create_legacy_project(directory)
            (Path(directory) / "assets" / "background_music_2.mp3").write_bytes(b"music two")
            job = VideoJob.objects.create(file_name="editable", status="completed", music_track="1")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "music_track": "2",
                "prompt_0": "First visual",
                "subtitle_0": "Hello world",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            job.refresh_from_db()
            self.assertEqual(job.music_track, "2")
            self.assertTrue(job.render_required)


class MusicAndVoiceSelectionTests(TestCase):
    def test_shared_voice_registry_resolves_existing_ids(self):
        self.assertEqual(resolve_voice_id("George"), VOICES["George"])
        self.assertEqual(resolve_voice_id("Eddie"), "VsQmyFHffusQDewmHB5v")
        with self.assertRaises(ValueError):
            resolve_voice_id("not-a-real-voice")

    @patch("pipeline.voice_samples.requests.post")
    def test_voice_preview_generates_constant_script_once_and_reuses_cache(self, post_mock):
        provider_response = MagicMock(content=b"sample mp3")
        provider_response.raise_for_status.return_value = None
        post_mock.return_value = provider_response
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            (Path(directory) / ".env").write_text("ELEVENLABS_API_KEY=test-key\n", encoding="utf-8")

            first = self.client.get("/voice/Eddie/sample/")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(b"".join(first.streaming_content), b"sample mp3")
            first.close()
            second = self.client.get("/voice/Eddie/sample/")
            self.assertEqual(second.status_code, 200)
            second.close()

            self.assertEqual(post_mock.call_count, 1)
            self.assertEqual(post_mock.call_args.kwargs["json"]["text"], VOICE_SAMPLE_TEXT)
            self.assertIn(VOICES["Eddie"], post_mock.call_args.args[0])
            self.assertEqual(
                (Path(directory) / "assets" / "voice_samples" / "Eddie.mp3").read_bytes(),
                b"sample mp3",
            )

    def test_voice_preview_rejects_unknown_voice(self):
        response = self.client.get("/voice/not-a-real-voice/sample/")
        self.assertEqual(response.status_code, 404)

    def test_editor_voice_change_invalidates_audio_and_restarts_from_voiceover(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            helper = ExistingVideoEditorTests()
            helper.create_legacy_project(directory)
            voiceover_dir = Path(directory) / "assets" / "voiceovers"
            voiceover_dir.mkdir(parents=True)
            audio_path = voiceover_dir / "editable.mp3"
            timing_path = voiceover_dir / "captions_editable.json"
            audio_path.write_bytes(b"old voice")
            timing_path.write_text("[]", encoding="utf-8")
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "voice_key": "George",
                "music_track": "1",
                "prompt_0": "First visual",
                "subtitle_0": "Hello world",
                "prompt_1": "Second visual",
                "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            job.refresh_from_db()
            self.assertEqual(job.voice_key, "George")
            self.assertEqual(job.render_start_script, "generate_voiceover_with_timing.py")
            self.assertFalse(audio_path.exists())
            self.assertFalse(timing_path.exists())
            self.assertEqual(job.edit_revisions.get(number=1).snapshot["voice_key"], "George")

    def test_uploaded_music_is_saved_and_available_to_future_projects(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets_dir = Path(directory) / "assets"
            assets_dir.mkdir()
            (assets_dir / "background_music_1.mp3").write_bytes(b"existing music")
            upload = SimpleUploadedFile("my-song.mp3", b"new music", content_type="audio/mpeg")

            response = self.client.post("/music/upload/", {
                "music_name": "My Calm Track",
                "music_file": upload,
            })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["track"]["id"], "2")
            self.assertEqual((assets_dir / "background_music_2.mp3").read_bytes(), b"new music")
            asset = BackgroundMusicAsset.objects.get(track_id=2)
            self.assertEqual(asset.display_name, "My Calm Track")
            self.assertEqual(asset.original_filename, "my-song.mp3")

            future_page = self.client.get("/")
            self.assertContains(future_page, "My Calm Track")
            self.assertContains(future_page, 'value="2"')

    def test_music_upload_rejects_non_mp3_files(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            upload = SimpleUploadedFile("not-music.wav", b"audio", content_type="audio/wav")

            response = self.client.post("/music/upload/", {
                "music_name": "Wrong format",
                "music_file": upload,
            })

            self.assertEqual(response.status_code, 400)
            self.assertIn("Only MP3", response.json()["error"])
            self.assertFalse(BackgroundMusicAsset.objects.exists())


class CaptionEffectTests(TestCase):
    @patch("create_video.ImageClip")
    def test_static_caption_has_no_fade_scale_or_movement_effect(self, image_clip_class):
        clip = MagicMock()
        image_clip_class.return_value = clip
        clip.set_start.return_value = clip
        clip.set_end.return_value = clip
        clip.set_position.return_value = clip
        generator = VideoGenerator()

        result = generator.create_caption_animation(
            {"start": 1.0, "end": 2.0}, MagicMock(), caption_animation="static"
        )

        self.assertIs(result, clip)
        clip.fadein.assert_not_called()
        clip.fadeout.assert_not_called()
        clip.resize.assert_not_called()
        clip.set_position.assert_called_once_with(("center", generator.CAPTION_Y))

class SceneAudioAndHoldFeatureTests(TestCase):
    def test_form_accepts_scene_audio_and_hold_settings(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets = Path(directory) / "assets"
            assets.mkdir()
            (assets / "background_music_1.mp3").write_bytes(b"music")
            form = VideoProjectSubmissionForm(data={
                "file_name": "audio_hold",
                "fps": 30,
                "music_track": "1",
                "scenes_json": json.dumps([{
                    "narration": "Words here",
                    "prompt": "A scene",
                    "use_original_audio": True,
                    "hold_after_seconds": 2.5,
                }]),
            })
            self.assertTrue(form.is_valid(), form.errors)
            self.assertTrue(form.cleaned_data["scenes_json"][0]["use_original_audio"])
            self.assertEqual(form.cleaned_data["scenes_json"][0]["hold_after_seconds"], 2.5)

    def test_form_preserves_fit_mode_and_rounds_time_to_hundredths(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets = Path(directory) / "assets"
            assets.mkdir()
            (assets / "background_music_1.mp3").write_bytes(b"music")
            form = VideoProjectSubmissionForm(data={
                "file_name": "precise_fit",
                "fps": 30,
                "music_track": "1",
                "scenes_json": json.dumps([{
                    "narration": "",
                    "prompt": "Wide view",
                    "use_original_audio": False,
                    "fit_with_borders": True,
                    "hold_after_seconds": 5.559,
                }]),
            })
            self.assertTrue(form.is_valid(), form.errors)
            scene = form.cleaned_data["scenes_json"][0]
            self.assertEqual(scene["hold_after_seconds"], 5.56)
            self.assertTrue(scene["fit_with_borders"])

    def test_fit_mode_preserves_wide_image_with_black_borders(self):
        generator = VideoGenerator()
        wide_pixels = np.full((90, 160, 3), 255, dtype=np.uint8)
        source = ImageClip(wide_pixels).set_duration(1)
        fitted = generator._motion_clip(source, "slow_push", 1, fit_with_borders=True)
        frame = fitted.get_frame(0.5)
        self.assertEqual(frame.shape[:2], (generator.VIDEO_HEIGHT, generator.VIDEO_WIDTH))
        self.assertTrue(np.all(frame[0, generator.VIDEO_WIDTH // 2] == 0))
        self.assertTrue(np.all(frame[generator.VIDEO_HEIGHT // 2, generator.VIDEO_WIDTH // 2] == 255))
        fitted.close()
        source.close()
    def test_form_allows_silent_scene_with_explicit_duration(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets = Path(directory) / "assets"
            assets.mkdir()
            (assets / "background_music_1.mp3").write_bytes(b"music")
            form = VideoProjectSubmissionForm(data={
                "file_name": "silent_scene",
                "fps": 30,
                "music_track": "1",
                "scenes_json": json.dumps([{
                    "narration": "",
                    "prompt": "A quiet landscape",
                    "use_original_audio": False,
                    "hold_after_seconds": 4,
                }]),
            })
            self.assertTrue(form.is_valid(), form.errors)

    def test_generated_silence_mixes_with_stereo_audio(self):
        generator = VideoGenerator()
        silence = generator._silence(0.1)
        stereo = AudioClip(
            lambda t: np.zeros((len(t), 2), dtype=float) if isinstance(t, np.ndarray) else np.zeros(2),
            duration=0.1,
            fps=44100,
        )
        mixed = CompositeAudioClip([silence, stereo])
        samples = mixed.get_frame(np.array([0.0, 0.01, 0.02]))
        self.assertEqual(samples.shape, (3, 2))
        mixed.close()
        silence.close()
        stereo.close()
    def test_scene_timeline_inserts_hold_and_shifts_following_captions(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            prompts = base / "prompts.json"
            script = base / "script.txt"
            prompts.write_text(json.dumps([
                {"narration": "Hello world", "hold_after_seconds": 2, "use_original_audio": True},
                {"narration": "Next scene", "hold_after_seconds": 1, "use_original_audio": False},
            ]), encoding="utf-8")
            script.write_text("Hello world ### Next scene", encoding="utf-8")
            captions = [
                {"text": "Hello", "start": 0, "end": .5},
                {"text": "world", "start": .5, "end": 1},
                {"text": "Next", "start": 1, "end": 1.5},
                {"text": "scene", "start": 1.5, "end": 2},
            ]
            generator = VideoGenerator()
            generator.PROMPTS_PATH = str(prompts)
            generator.SCRIPT_PATH = str(script)
            timeline = generator.build_scene_timeline(captions)

            self.assertEqual(timeline[0]["start"], 0)
            self.assertEqual(timeline[0]["end"], 3)
            self.assertEqual(timeline[1]["start"], 3)
            self.assertEqual(timeline[1]["captions"][0]["start"], 3)
            self.assertEqual(timeline[1]["end"], 5.0)
            self.assertTrue(timeline[0]["use_original_audio"])

    def test_negative_caption_offset_keeps_narration_instead_of_using_negative_subclip(self):
        generator = VideoGenerator()
        raw_audio = MagicMock(duration=2.0)
        narration_segment = MagicMock(duration=0.9)
        raw_audio.subclip.return_value = narration_segment
        timeline = [{
            "raw_start": -0.05,
            "raw_end": 0.9,
            "hold_after_seconds": 0,
            "end": 0.95,
        }]

        with patch("create_video.concatenate_audioclips") as concatenate:
            generator.build_narration_track(raw_audio, timeline)

        raw_audio.subclip.assert_called_once_with(0.0, 0.9)
        parts = concatenate.call_args.args[0]
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(parts[0].duration, 0.05)


class VideoRangeSelectionTests(TestCase):
    def test_form_persists_two_decimal_video_range_and_rejects_reversed_range(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            assets = Path(directory) / "assets"
            assets.mkdir()
            (assets / "background_music_1.mp3").write_bytes(b"music")
            scene = {
                "narration": "A narrated scene",
                "prompt": "A video",
                "hold_after_seconds": 0,
                "video_start_seconds": 1.234,
                "video_end_seconds": 5.678,
            }
            form = VideoProjectSubmissionForm(data={
                "file_name": "trimmed_video", "fps": 30, "music_track": "1",
                "scenes_json": json.dumps([scene]),
            })
            self.assertTrue(form.is_valid(), form.errors)
            cleaned = form.cleaned_data["scenes_json"][0]
            self.assertEqual(cleaned["video_start_seconds"], 1.23)
            self.assertEqual(cleaned["video_end_seconds"], 5.68)

            scene["video_end_seconds"] = 1.0
            invalid = VideoProjectSubmissionForm(data={
                "file_name": "reversed_video", "fps": 30, "music_track": "1",
                "scenes_json": json.dumps([scene]),
            })
            self.assertFalse(invalid.is_valid())
            self.assertIn("must be after", invalid.errors["scenes_json"][0])

    def test_creator_exposes_live_video_range_preview(self):
        response = self.client.get("/")
        self.assertContains(response, "Choose the part of the video to use")
        self.assertContains(response, "video-range-preview")
        self.assertContains(response, "video_start_seconds")

    def test_timeline_carries_video_range_to_renderer(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            prompts = base / "prompts.json"
            script = base / "script.txt"
            prompts.write_text(json.dumps([{
                "narration": "Hello world", "hold_after_seconds": 1,
                "video_start_seconds": 2.25, "video_end_seconds": 6.75,
            }]), encoding="utf-8")
            script.write_text("Hello world", encoding="utf-8")
            generator = VideoGenerator()
            generator.PROMPTS_PATH = str(prompts)
            generator.SCRIPT_PATH = str(script)
            timeline = generator.build_scene_timeline([
                {"text": "Hello", "start": 0, "end": .5},
                {"text": "world", "start": .5, "end": 1},
            ])
            self.assertEqual(timeline[0]["video_start_seconds"], 2.25)
            self.assertEqual(timeline[0]["video_end_seconds"], 6.75)

    @patch("create_video.VideoFileClip")
    def test_video_loader_trims_before_scene_looping(self, video_file_clip):
        source = MagicMock(duration=10)
        trimmed = MagicMock(duration=3)
        trimmed.audio = MagicMock()
        trimmed.without_audio.return_value.set_duration.return_value = MagicMock()
        source.subclip.return_value = trimmed
        video_file_clip.return_value = source
        generator = VideoGenerator()

        generator._load_media_clip("source.mp4", 2, 2, 5)

        source.subclip.assert_called_once_with(2.0, 5.0)

    def test_editor_saves_range_for_existing_video(self):
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            helper = ExistingVideoEditorTests()
            media_dir = helper.create_legacy_project(directory)
            (media_dir / "0.png").unlink()
            (media_dir / "0.mp4").write_bytes(b"video placeholder")
            job = VideoJob.objects.create(file_name="editable", status="completed")

            response = self.client.post(f"/job/{job.id}/edit/", {
                "music_track": "1",
                "prompt_0": "First visual", "subtitle_0": "Hello world",
                "video_start_seconds_0": "1.25", "video_end_seconds_0": "4.75",
                "prompt_1": "Second visual", "subtitle_1": "Goodbye moon",
            })

            self.assertEqual(response.status_code, 302)
            prompts = json.loads(
                (Path(directory) / "prompts" / "editable.json").read_text(encoding="utf-8")
            )
            self.assertEqual(prompts[0]["video_start_seconds"], 1.25)
            self.assertEqual(prompts[0]["video_end_seconds"], 4.75)
