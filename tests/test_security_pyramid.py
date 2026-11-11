"""Unit & Adversarial Security Pyramid Tests (`tests/test_security_pyramid.py`)."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class TestEnterpriseSecurityStageAndPyramid(unittest.TestCase):
    def test_security_audit_sec01_to_sec10_all_pass(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "security_audit.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)
        self.assertIn(
            "SECURITY STAGE PASS: 10/10 security controls verified",
            proc.stdout,
        )


if __name__ == "__main__":
    unittest.main()
