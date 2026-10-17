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



class ProjectPluginTests(unittest.TestCase):
    def test_config_plugin_registers_command_and_stage(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                Path("config").mkdir()
                Path("config/settings.yaml").write_text("plugins: [demo_plugin_xyz]\n", encoding="utf-8")
                Path("demo_plugin_xyz.py").write_text(
                    "from jobpilot.core.registry import commands\n"
                    "from jobpilot.core.command import Command\n"
                    "commands.register('hello-xyz')(Command('hello-xyz', 'demo', "
                    "lambda ctx, args: print('hello from plugin') or 0, needs_context=False))\n", encoding="utf-8")
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = cli.main(["--config", "config/settings.yaml", "hello-xyz"])
                self.assertEqual(code, 0)
                self.assertIn("hello from plugin", buf.getvalue())
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
