"""OS-23 offline regression tests; no host dpkg or network calls."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "os23_inventory", Path(__file__).resolve().parents[1] / "scripts/dpkg_inventory.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

LISTING = '''Desired=Unknown/Install/Remove/Purge/Hold
| Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
|/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
||/ Name Version Architecture Description
+++-====-====-====-====
ii  bash 5.2 amd64 GNU shell with spaces
rc  old-package 1.0 all Residual configuration
hi  libc6:amd64 2.40 amd64 C library
iU  pending 1 all Not yet configured
'''

class InventoryTests(unittest.TestCase):
    def invoke(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = m.main(args)
        return code, json.loads(stream.getvalue())

    def test_list_states_description_and_multiarch(self):
        with patch.object(m, "run_dpkg", return_value=LISTING) as run:
            code, result = self.invoke(["-l"])
        run.assert_called_once_with("-l")
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["installed_count"], 2)
        self.assertEqual(result["data"]["count"], 4)
        self.assertEqual(result["data"]["packages"][0]["description"], "GNU shell with spaces")
        self.assertFalse(result["data"]["packages"][1]["installed"])
        self.assertEqual(result["schema_version"], 1)

    def test_empty_valid_database(self):
        self.assertEqual(m.parse_inventory("+++-===\n"), [])
        self.assertEqual(m.parse_inventory(""), [])

    def test_malformed_listing_is_not_silent_success(self):
        for text in ["not dpkg", "+++-===\nbad\n", "+++-===\nii  bash\n"]:
            with self.subTest(text=text), self.assertRaises(m.InventoryError):
                m.parse_inventory(text)

    def test_files_preserve_spaces_and_ignore_diversion_notes(self):
        with patch.object(m, "run_dpkg", return_value="/.\n/usr/bin/a file\n\ndiverted by other to: /elsewhere\n") as run:
            result = m.files("libc6:amd64")
        run.assert_called_once_with("-L", "--", "libc6:amd64")
        self.assertEqual(result["files"], ["/.", "/usr/bin/a file"])

    def test_owner_multiple_packages_multiarch_and_colon_path(self):
        path = "/usr/share/a: file"
        with patch.object(m, "run_dpkg", return_value=f"libc6:amd64, bash: {path}\nlocal diversion from: {path}\nbash: /different\n"):
            self.assertEqual(m.owners(path)["packages"], ["bash", "libc6:amd64"])

    def test_literal_glob_characters_not_expanded(self):
        path = "/tmp/a[*]?"
        with patch.object(m, "run_dpkg", return_value=f"bash: {path}\n") as run:
            self.assertEqual(m.owners(path)["packages"], ["bash"])
        run.assert_called_once_with("-S", "--", "/tmp/a[[][*][]][?]")

    def test_nonmatching_owner_is_error(self):
        with patch.object(m, "run_dpkg", return_value="bash: /usr/bin/other\n"):
            with self.assertRaises(m.InventoryError):
                m.owners("/usr/bin/bash")

    def test_usage_rejects_options_patterns_and_relative_paths(self):
        for args in [["-L", "--root=/tmp"], ["-L", "bash*"], ["-S", "relative"],
                     ["-S", "/tmp/a\nfile"], [], ["-l", "-L", "bash"]]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    m.main(args)
                self.assertEqual(error.exception.code, 2)

    def test_command_is_shell_free_localized_and_bounded(self):
        with patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, LISTING, "")) as run:
            m.inventory()
        argv = run.call_args.args[0]
        kw = run.call_args.kwargs
        self.assertEqual(argv, ["dpkg", "-l"])
        self.assertNotIn("shell", kw)
        self.assertEqual(kw["env"]["LC_ALL"], "C")
        self.assertEqual(kw["timeout"], 20)

    def test_failures_produce_json_and_nonzero_exit(self):
        for error in [FileNotFoundError(), PermissionError("denied"), subprocess.TimeoutExpired("dpkg", 20)]:
            with self.subTest(error=error), patch.object(m.subprocess, "run", side_effect=error):
                code, result = self.invoke(["-l"])
                self.assertEqual(code, 1)
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"])

    def test_unknown_package_error_preserved(self):
        completed = subprocess.CompletedProcess([], 1, "", "dpkg-query: no packages found matching absent")
        with patch.object(m.subprocess, "run", return_value=completed):
            code, result = self.invoke(["-L", "absent"])
        self.assertEqual(code, 1)
        self.assertIn("no packages found", result["error"])

@unittest.skipUnless(shutil.which("dpkg"), "dpkg unavailable")
class RealDpkgTests(unittest.TestCase):
    """Real dpkg against a temporary synthetic database, never the host db."""

    def test_three_modes_and_unknown_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "info").mkdir()
            (root / "status").write_text(
                "Package: oslab-demo\nStatus: install ok installed\n"
                "Architecture: all\nVersion: 1.0\nMaintainer: Lab <lab@example.invalid>\n"
                "Description: Synthetic OS-23 fixture\n\n")
            (root / "info/oslab-demo.list").write_text(
                "/.\n/usr/share/oslab-demo\n/usr/share/oslab-demo/a file\n/usr/share/oslab-demo/a[*]?\n")
            def cli(*args):
                result = subprocess.run([sys.executable, str(Path(m.__file__)),
                    "--admindir", tmp, *args], text=True, capture_output=True, timeout=10)
                return result.returncode, json.loads(result.stdout)
            code, result = cli("-l")
            self.assertEqual(code, 0)
            self.assertEqual(result["data"]["installed_count"], 1)
            self.assertEqual(result["data"]["packages"][0]["package"], "oslab-demo")
            code, result = cli("-L", "oslab-demo")
            self.assertEqual(code, 0)
            self.assertIn("/usr/share/oslab-demo/a file", result["data"]["files"])
            for path in ["/usr/share/oslab-demo/a file", "/usr/share/oslab-demo/a[*]?"]:
                code, result = cli("-S", path)
                self.assertEqual(code, 0, result)
                self.assertEqual(result["data"]["packages"], ["oslab-demo"])
            code, result = cli("-L", "absent")
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])

if __name__ == "__main__":
    unittest.main()
