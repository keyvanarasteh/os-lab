"""Offline contracts for the read-only native Windows app mirror.

Every Win32 call is faked, so these run (and mean the same thing) on any host.
"""

import os
import struct
import sys
import zlib

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")))

import winapps


class FakeUser32:
    """One top-level window; each knob flips a single filter."""

    def __init__(self, *, style=winapps.WS_CAPTION, ex_style=0, class_name="ApplicationFrameWindow",
                 visible=True, iconic=False, root=None, rect=(10, 20, 330, 260)):
        self.style, self.ex_style, self.class_name = style, ex_style, class_name
        self.visible, self.iconic, self.root, self.rect = visible, iconic, root, rect

    def IsWindowVisible(self, _hwnd):
        return self.visible

    def IsIconic(self, _hwnd):
        return self.iconic

    def GetWindowLongPtrW(self, _hwnd, index):
        return self.style if index == -16 else self.ex_style

    def GetWindowThreadProcessId(self, _hwnd, out_pid):
        out_pid.value = 42
        return 0

    def GetWindowTextLengthW(self, _hwnd):
        return 5

    def GetWindowTextW(self, _hwnd, buffer, _length):
        buffer.value = "hello"
        return 5

    def GetClassNameW(self, _hwnd, buffer, _length):
        buffer.value = self.class_name
        return len(self.class_name)

    def GetWindowRect(self, _hwnd, out_rect):
        out_rect.left, out_rect.top, out_rect.right, out_rect.bottom = self.rect
        return True

    def EnumWindows(self, proc, _lparam):
        return proc(1234, 0)

    def GetAncestor(self, hwnd, _flag):
        return hwnd if self.root is None else self.root


class FakeKernel32:
    def __init__(self, session=1):
        self.session = session

    def OpenProcess(self, _access, _inherit, _pid):
        return 1

    def QueryFullProcessImageNameW(self, _handle, _flags, buffer, out_size):
        buffer.value = "C:/Some/App/Example.exe"
        out_size.value = len("C:/Some/App/Example.exe")
        return True

    def CloseHandle(self, _handle):
        return True

    def GetCurrentProcess(self):
        return 7

    def GetCurrentProcessId(self):
        return 4242

    def ProcessIdToSessionId(self, _pid, out_session):
        out_session._obj.value = self.session
        return True


class FakeDwm:
    def __init__(self, cloaked=0):
        self.cloaked = cloaked

    def DwmGetWindowAttribute(self, _hwnd, _attribute, out_value, _size):
        out_value._obj.value = self.cloaked
        return 0


class FakeAdvapi32:
    """`elevated=None` models Windows refusing the token query."""

    def __init__(self, elevated=False):
        self.elevated = elevated

    def OpenProcessToken(self, _process, _access, _out_token):
        return self.elevated is not None

    def GetTokenInformation(self, _token, _cls, out_info, _size, _out_returned):
        out_info._obj.value = int(bool(self.elevated))
        return True


@pytest.fixture
def host(monkeypatch):
    """Install hermetic fakes as if on Windows; tests swap individual pieces."""
    monkeypatch.setattr(winapps.sys, "platform", "win32")
    monkeypatch.setattr(winapps, "_user32", FakeUser32())
    monkeypatch.setattr(winapps, "_gdi32", object())
    monkeypatch.setattr(winapps, "_kernel32", FakeKernel32())
    monkeypatch.setattr(winapps, "_dwmapi", FakeDwm())
    monkeypatch.setattr(winapps, "_advapi32", FakeAdvapi32())
    return monkeypatch


def test_non_windows_hosts_report_native_availability(monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    result = winapps.winapps_windows()
    assert result["available"] is False and result["windows"] == []
    assert "Windows host" in result["reason"]


def test_non_windows_hosts_refuse_screenshots(monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    with pytest.raises(winapps.WinAppError, match="Windows host"):
        winapps.winapps_window_screenshot(1234)


def test_invalid_window_ids_are_refused(host):
    with pytest.raises(winapps.WinAppError, match="Invalid window id"):
        winapps.winapps_window_screenshot("not-a-window")


@pytest.mark.parametrize("window_id", ["0", "-5", str(2**32), str(2**64), str(2**80), "1e3", ""])
def test_out_of_range_window_ids_are_refused_before_ctypes(host, window_id):
    # An id ctypes cannot convert to an HWND used to escape as an unhandled error (HTTP 500).
    with pytest.raises(winapps.WinAppError, match="Invalid window id"):
        winapps.winapps_window_screenshot(window_id)


def test_a_captioned_window_is_listed_with_its_process(host):
    windows = winapps._win_windows()
    assert len(windows) == 1
    assert windows[0]["windowId"] == 1234
    assert windows[0]["app"] == "Example"
    assert windows[0]["title"] == "hello"
    assert windows[0]["className"] == "ApplicationFrameWindow"
    assert (windows[0]["width"], windows[0]["height"]) == (320, 240)
    assert windows[0]["elevated"] is False


@pytest.mark.parametrize("user32", [
    FakeUser32(style=0),                                     # no caption
    FakeUser32(ex_style=winapps.WS_EX_TOOLWINDOW),           # tool window
    FakeUser32(class_name="Shell_TrayWnd"),                  # known shell class
    FakeUser32(visible=False),                               # hidden
    FakeUser32(iconic=True),                                 # minimized
    FakeUser32(rect=(0, 0, 0, 0)),                           # empty rect
])
def test_shell_tool_hidden_and_minimized_windows_are_not_listed(host, user32):
    host.setattr(winapps, "_user32", user32)
    assert winapps._win_windows() == []


def test_cloaked_windows_are_not_listed(host):
    # Suspended UWP frames stay "visible" to Win32 but are not on screen.
    host.setattr(winapps, "_dwmapi", FakeDwm(cloaked=2))
    assert winapps._win_windows() == []


def test_elevation_is_reported_and_unknown_is_not_guessed(host):
    host.setattr(winapps, "_advapi32", FakeAdvapi32(elevated=True))
    assert winapps._win_windows()[0]["elevated"] is True
    host.setattr(winapps, "_advapi32", FakeAdvapi32(elevated=None))
    assert winapps._win_windows()[0]["elevated"] is None


def test_a_stale_window_id_is_refused(host):
    host.setattr(winapps, "_user32", FakeUser32(root=999))  # no longer its own root
    with pytest.raises(winapps.WinAppError, match="not on screen"):
        winapps.winapps_window_screenshot(1234)
    host.setattr(winapps, "_user32", FakeUser32(visible=False))
    with pytest.raises(winapps.WinAppError, match="not on screen"):
        winapps.winapps_window_screenshot(1234)


def test_oversized_windows_are_refused_before_any_capture(host):
    host.setattr(winapps, "_user32", FakeUser32(rect=(0, 0, 20000, 20000)))
    with pytest.raises(winapps.WinAppError, match="too large"):
        winapps.winapps_window_screenshot(1234)


def _chunks(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    position = 8
    while position < len(png):
        length, kind = struct.unpack(">I4s", png[position:position + 8])
        body = png[position + 8:position + 8 + length]
        (crc,) = struct.unpack(">I", png[position + 8 + length:position + 12 + length])
        assert crc == zlib.crc32(kind + body), f"bad CRC in {kind!r}"
        yield kind, body
        position += 12 + length


def test_png_encoder_round_trips_a_bgra_buffer():
    # 2x2, BGRA, alpha deliberately 0 as GDI often leaves it.
    bgra = bytes([
        10, 20, 30, 0,    40, 50, 60, 0,
        70, 80, 90, 0,    100, 110, 120, 0,
    ])
    chunks = list(_chunks(winapps._png(2, 2, bgra)))
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", chunks[0][1]) == (2, 2, 8, 6, 0, 0, 0)
    raw = zlib.decompress(chunks[1][1])
    stride = 1 + 2 * 4
    assert len(raw) == 2 * stride
    assert raw[0] == 0 and raw[stride] == 0  # filter type None on every row
    assert raw[1:stride] == bytes([30, 20, 10, 255, 60, 50, 40, 255])      # RGBA, opaque
    assert raw[stride + 1:] == bytes([90, 80, 70, 255, 120, 110, 100, 255])


def test_doctor_on_a_non_windows_host(monkeypatch):
    monkeypatch.setattr(winapps.sys, "platform", "linux")
    result = winapps.doctor()
    assert result["available"] is False and result["capture"] is False
    assert result["elevated"] is None and "Windows host" in result["reason"]


def test_doctor_reports_session_elevation_and_a_capture_probe(host):
    host.setattr(winapps, "_user32", type("U", (FakeUser32,), {"GetShellWindow": lambda self: 1})())
    host.setattr(winapps, "_advapi32", FakeAdvapi32(elevated=True))
    host.setattr(winapps, "winapps_window_screenshot", lambda _hwnd: b"\x89PNG\r\n\x1a\n")
    result = winapps.doctor()
    assert result["desktop"] is True and result["sessionId"] == 1
    assert result["elevated"] is True
    assert result["windows"] == 1 and result["capture"] is True and result["reason"] is None


def test_doctor_refuses_to_probe_without_an_interactive_desktop(host):
    host.setattr(winapps, "_kernel32", FakeKernel32(session=0))
    result = winapps.doctor()
    assert result["desktop"] is False and result["available"] is False
    assert "interactive desktop" in result["reason"]
