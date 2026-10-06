"""Legacy bootstrap refuses execution without consuming private input."""
from pathlib import Path
import subprocess
import sys
import unittest


class BootstrapTests(unittest.TestCase):
    def test_retired_bootstrap_refuses_without_reading_input(self):
        script = Path(__file__).resolve().parents[1] / "deploy/bootstrap-wikicontext.py"
        for args in ([], ["unexpected-target"]):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "-I", str(script), *args],
                                        input="synthetic-private-payload", capture_output=True,
                                        text=True, timeout=5, env={"PATH": "/nonexistent"})
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("retired", result.stderr)
                self.assertIn("once-pocketcontext-v2 shared dispatcher", result.stderr)
                self.assertNotIn("synthetic-private-payload", result.stderr)


if __name__ == "__main__":
    unittest.main()
