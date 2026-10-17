import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jobpilot import cli
from jobpilot.core.registry import stages
from jobpilot.core.stage import StageResult


class CliEndToEnd(unittest.TestCase):
    """Drives the real CLI against a temp project (no browser, no network)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.cfg = "config/settings.yaml"

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def call(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--config", self.cfg, *argv])
        return code, buf.getvalue()

    def test_init_then_answers_roundtrip_and_run_with_fake_stage(self):
        code, out = self.call("init")
        self.assertEqual(code, 0)
        self.assertTrue(Path("config/settings.yaml").exists() and Path("config/templates/application_email.txt").exists())

        # the example profile/settings must load as-is
        code, out = self.call("report")
        self.assertEqual(code, 0)
        self.assertIn("applied today", out)

        self.call("answers", "set", "What is your favourite colour?", "Blue")
        code, out = self.call("answers", "list", "--status", "user")
        self.assertIn("Blue", out)

        class Fake:
            name, description = "fake", "test stage"
            def run(self, ctx): return StageResult("fake", True, {"n": 3})
        if "fake" not in stages:
            stages.register("fake")(Fake())
        code, out = self.call("run", "--only", "fake", "--skip-export")
        self.assertEqual(code, 0)
        self.assertIn("[fake] ok n=3", out)

        code, out = self.call("run", "--only", "does-not-exist", "--skip-export")
        self.assertEqual(code, 1)

    def test_doctor_without_config_fails_helpfully(self):
        code, out = self.call("doctor")
        self.assertEqual(code, 1)
        self.assertIn("jobpilot init", out)

    def test_export_writes_excel(self):
        self.call("init")
        code, out = self.call("export", "--format", "xlsx")
        self.assertEqual(code, 0)
        self.assertTrue(list(Path("data/exports").glob("*.xlsx")))


if __name__ == "__main__":
    unittest.main()
