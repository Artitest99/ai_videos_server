from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from helper import get_array_type, to_float
from pipeline.models import VideoJob
from pipeline.tasks import update_env_variable


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


class HelperTests(TestCase):
    def test_array_type_detection(self):
        self.assertEqual(get_array_type([1, 2]), "integers")
        self.assertEqual(get_array_type(["one", "two"]), "strings")
        self.assertEqual(get_array_type([1, "two"]), "Mixed")

    def test_to_float_uses_default_for_invalid_value(self):
        self.assertEqual(to_float("invalid", default=24), 24.0)
