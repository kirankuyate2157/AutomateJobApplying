import unittest

from jobpilot.core.registry import Registry
from jobpilot.core.stage import Stage, StageResult


class RegistryTests(unittest.TestCase):
    def test_register_get_and_duplicates(self):
        reg: Registry = Registry("thing")

        @reg.register("a")
        def a(): return 1

        self.assertEqual(reg.get("a")(), 1)
        self.assertIn("a", reg)
        with self.assertRaises(ValueError):
            reg.register("a")(lambda: 2)           # shadowing is refused
        with self.assertRaises(KeyError) as cm:
            reg.get("zzz")
        self.assertIn("Available: a", str(cm.exception))

    def test_stage_protocol_is_structural(self):
        class Mine:
            name, description = "mine", "demo"
            def run(self, ctx): return StageResult("mine", counts={"x": 1})
        self.assertIsInstance(Mine(), Stage)
        self.assertEqual(str(Mine().run(None)), "[mine] ok x=1")


if __name__ == "__main__":
    unittest.main()
