"""The retired deployment bootstrap must never run deployment commands."""
from pathlib import Path
import subprocess
import sys
import unittest


class BootstrapTests(unittest.TestCase):
    def test_retired_bootstrap_refuses_without_reading_input(self):
        script = Path(__file__).resolve().parents[1] / "deploy/bootstrap-wikicontext.py"
        result = subprocess.run([sys.executable, str(script)], input="synthetic-private-payload", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("bootstrap retired", result.stderr)
        self.assertIn("once-pocketcontext-v2", result.stderr)
        self.assertNotIn("synthetic-private-payload", result.stderr)


if __name__ == "__main__":
    unittest.main()
