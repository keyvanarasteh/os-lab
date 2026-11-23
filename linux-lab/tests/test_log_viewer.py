"""OS-29 log-viewer.sh regression tests; local temp files only, no network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/log-viewer.sh"


def run(args, stdin, cwd=None):
    return subprocess.run(["bash", str(SCRIPT), *args], input=stdin, text=True,
                          capture_output=True, timeout=10, cwd=cwd)


class LogViewerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.log = self.dir / "sample.log"
        self.log.write_text("".join(f"line {i}\n" for i in range(1, 31)), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_last_and_count(self):
        out = run([str(self.log)], "1\n2\n4\n7\n").stdout
        self.assertIn("line 1\n", out)
        self.assertIn("line 20\n", out)
        self.assertIn("line 30\n", out)
        self.assertIn("30\n", out)

    def test_eof_exits_instead_of_looping(self):
        proc = run([str(self.log)], "")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.count("OS-29 LOG VIEWER"), 1)

    def test_missing_file_fails(self):
        proc = run([str(self.dir / "nope.log")], "7\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("bulunamadi", proc.stdout)

    @unittest.skipIf(os.geteuid() == 0, "root can read everything")
    def test_unreadable_file_fails_with_hint(self):
        self.log.chmod(0)
        try:
            proc = run([str(self.log)], "7\n")
        finally:
            self.log.chmod(0o600)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("okunamiyor", proc.stdout)

    def test_control_bytes_are_removed(self):
        self.log.write_bytes(b"ok\n\x1b]52;c;ZXZpbA==\x07evil\n\x1b[2Jclear\n")
        out = run([str(self.log)], "1\n7\n").stdout
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertIn("evil", out)

    def test_dash_prefixed_relative_path(self):
        (self.dir / "-x.log").write_text("a\nb\nc\n", encoding="utf-8")
        out = run(["./-x.log"], "4\n7\n", cwd=self.dir).stdout
        self.assertIn("3\n", out)
        out = run(["-x.log"], "4\n7\n", cwd=self.dir).stdout
        self.assertIn("3\n", out)

    def test_search_is_case_insensitive_and_literal(self):
        self.log.write_text("Error: disk\nok\na.b[1]\n", encoding="utf-8")
        out = run([str(self.log)], "6\nERROR\n6\na.b[1]\n6\nzzz\n7\n").stdout
        self.assertIn("1:Error: disk", out)
        self.assertIn("3:a.b[1]", out)
        self.assertIn("Eslesme yok", out)

    def test_invalid_choice_message(self):
        self.assertIn("Gecersiz secim", run([str(self.log)], "x\n7\n").stdout)


if __name__ == "__main__":
    unittest.main()
