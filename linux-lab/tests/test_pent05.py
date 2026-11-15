"""PENT-05 hardening audit + crash triage: runs the offline bash suite.

The suite uses a fake readelf and a fake crash target from fixtures/pent05,
so it needs only bash and coreutils (timeout), not a compiler or AFL++.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

SUITE = Path(__file__).resolve().parent / 'pent05_test.sh'


@unittest.skipUnless(shutil.which('bash') and shutil.which('timeout'), 'bash and timeout are required')
class Pent05Suite(unittest.TestCase):
    def test_offline_suite(self):
        proc = subprocess.run(['bash', str(SUITE)], capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('0 başarısız', proc.stdout)


if __name__ == '__main__':
    unittest.main()
