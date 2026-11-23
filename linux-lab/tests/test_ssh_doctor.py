"""OS-17 ssh_doctor.py regression tests; pure functions, no network."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "os17_ssh_doctor", Path(__file__).resolve().parents[1] / "scripts/ssh_doctor.py")
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


class DiagnoseTest(unittest.TestCase):
    def kind(self, message):
        return doctor.diagnose(message)[0]

    def test_five_original_categories(self):
        self.assertEqual(self.kind("Connection timed out"), "TIMEOUT")
        self.assertEqual(self.kind("Permission denied"), "AUTHENTICATION")
        self.assertEqual(self.kind("127.0.1.1"), "LOOPBACK")
        self.assertEqual(self.kind("Firewall blocked"), "FIREWALL")
        self.assertEqual(self.kind("Wrong adapter"), "ADAPTER")

    def test_any_loopback_form_and_it_wins_over_timeout(self):
        for text in ("connect to host 127.0.0.1 port 22: Connection timed out",
                     "ssh: connect to host ::1 port 22: refused", "localhost: timeout",
                     "127.0.1.1 connection timed out"):
            self.assertEqual(self.kind(text), "LOOPBACK", text)

    def test_non_loopback_addresses_are_not_loopback(self):
        for text in ("connect to host 10.127.0.1.5 port 22: Connection timed out",
                     "192.168.127.1.2 timed out", "1127.0.0.1 timed out"):
            self.assertEqual(self.kind(text), "TIMEOUT", text)

    def test_password_messages_are_authentication(self):
        self.assertEqual(self.kind("wrong password"), "AUTHENTICATION")
        self.assertEqual(self.kind("Incorrect password, try again"), "AUTHENTICATION")

    def test_unknown_message(self):
        self.assertEqual(self.kind("something else"), "UNKNOWN")
        self.assertEqual(self.kind(""), "UNKNOWN")


class HostTest(unittest.TestCase):
    def test_valid_and_loopback_hosts(self):
        self.assertEqual(doctor.check_host("192.168.1.20"), "Hedef IP: 192.168.1.20")
        self.assertIn("Loopback", doctor.check_host("127.0.0.1"))
        self.assertIn("Loopback", doctor.check_host("::1"))

    def test_control_bytes_and_scope_ids_are_never_echoed(self):
        for host in ("fe80::1%eth0\x1b]52;c;ZXZpbA==\x07", "fe80::1%eth0", "10.0.0.1\x1b[2J", "not-an-ip"):
            note = doctor.check_host(host)
            self.assertEqual(note, "UYARI: Gecersiz IP adresi.")
            self.assertNotIn("\x1b", note)

    def test_main_prints_report_and_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.main(["Connection timed out", "--host", "10.0.0.5"])
        self.assertEqual(code, 0)
        self.assertIn("Kategori : TIMEOUT", out.getvalue())
        self.assertIn("Hedef IP: 10.0.0.5", out.getvalue())


if __name__ == "__main__":
    unittest.main()
