import tempfile
import unittest
from pathlib import Path

from jobpilot.exceptions import ConfigError
from jobpilot.settings import Settings


def _write(tmp: Path, text: str) -> Path:
    (tmp / "config").mkdir()
    p = tmp / "config" / "settings.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class SettingsTests(unittest.TestCase):
    def test_defaults_and_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "apply:\n  daily_target: 10\n")
            s = Settings.load(p)
            self.assertEqual(s.apply.daily_target, 10)
            self.assertTrue(s.apply.dry_run)            # safe default preserved
            self.assertEqual(s.root, Path(d).resolve())
            self.assertEqual(s.db_path, Path(d).resolve() / "data" / "jobpilot.db")

    def test_unknown_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "apply:\n  daily_targt: 10\n")
            with self.assertRaises(ConfigError):
                Settings.load(p)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            Settings.load("/nonexistent/config/settings.yaml")


if __name__ == "__main__":
    unittest.main()
