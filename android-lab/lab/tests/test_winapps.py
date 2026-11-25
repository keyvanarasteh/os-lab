"""Offline contracts for the read-only native Windows app mirror.

Every Win32 call is faked, so these run (and mean the same thing) on any host.
"""

import ctypes
import os
import struct
import sys
import threading
import zlib

import pytest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "console")))

import winapps


class FakeUser32:
    """One top-level window; each knob flips a single filter."""

    def __init__(self, *, style=winapps.WS_CAPTION, ex_style=0, class_name="ApplicationFrameWindow",
                 visible=True, iconic=False, root=None, rect=(10, 20, 330, 260),
                 dpi=96, above=0, thread_id=99):
        self.style, self.ex_style, self.class_name = style, ex_style, class_name
        self.visible, self.iconic, self.root, self.rect = visible, iconic, root, rect
        self.dpi = dpi
        self.dpi_context = 0x1234
        self.dpi_context_calls = []
        self.above = above
        self.thread_id = thread_id
        self.capture_messages = []
        self.desktop_dc_requests = 0

    def IsWindowVisible(self, _hwnd):
        return self.visible

    def IsIconic(self, _hwnd):
        return self.iconic

    def GetWindowLongPtrW(self, _hwnd, index):
        return self.style if index == -16 else self.ex_style

    def GetWindowThreadProcessId(self, _hwnd, out_pid):
        if out_pid is not None:
            out_pid.value = 42
        return self.thread_id

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

    def GetDpiForWindow(self, _hwnd):
        return self.dpi

    def SetThreadDpiAwarenessContext(self, context):
        self.dpi_context_calls.append(context.value if hasattr(context, "value") else context)
        previous, self.dpi_context = self.dpi_context, context
        return previous

    def EnumWindows(self, proc, _lparam):
        return proc(1234, 0)

    def GetAncestor(self, hwnd, _flag):
        return hwnd if self.root is None else self.root

    def GetWindow(self, hwnd, _command):
        return self.above if hwnd == 1234 else 0

    def GetWindowDC(self, _hwnd):
        return 8

    def GetDC(self, hwnd):
        assert hwnd == 0
        self.desktop_dc_requests += 1
        return 9

    def ReleaseDC(self, _hwnd, _dc):
        return 1

    def SendMessageTimeoutW(self, hwnd, message, _dc, flags, options, timeout, _result):
        self.capture_messages.append((hwnd, message, flags, options, timeout))
        return 0


class FakeGdi:
    def __init__(self):
        self.desktop_blits = 0

    def CreateCompatibleDC(self, _dc):
        return 10

    def CreateCompatibleBitmap(self, _dc, _width, _height):
        return 11

    def SelectObject(self, _dc, _bitmap):
        return 12

    def PatBlt(self, *_args):
        return True

    def BitBlt(self, *_args):
        self.desktop_blits += 1
        return True

    def GetDIBits(self, _dc, _bitmap, _start, height, pixels, _info, _usage):
        ctypes.memset(pixels, 0, 320 * 240 * 4)
        return height

    def DeleteObject(self, _bitmap):
        return True

    def DeleteDC(self, _dc):
        return True


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
    monkeypatch.setattr(winapps, "_UIA_ELEMENTS", {})
    monkeypatch.setattr(winapps, "_CONTROL_STATE", {"armed": False, "armedAt": 0.0, "owner": None})
    monkeypatch.setattr(winapps, "_ACTION_CACHE", {})
    monkeypatch.setattr(winapps, "_WINAPPS_STREAM_EPOCH", 0)
    monkeypatch.setattr(winapps, "_AUDIT_ROWS", [])
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
    assert windows[0]["dpi"] == 96


def test_window_bounds_are_read_in_physical_dpi_context(host):
    user32 = FakeUser32(dpi=144)
    observed_contexts = []
    get_rect = user32.GetWindowRect

    def get_rect_in_context(hwnd, out_rect):
        observed_contexts.append(user32.dpi_context_calls[-1])
        return get_rect(hwnd, out_rect)

    user32.GetWindowRect = get_rect_in_context
    host.setattr(winapps, "_user32", user32)
    window = winapps._window(1234)
    assert window["dpi"] == 144
    assert observed_contexts == [winapps.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.value]
    assert user32.dpi_context_calls[-1] == 0x1234


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


def test_window_stream_yields_frames_and_stops_when_the_window_disappears(host, monkeypatch):
    calls = []
    png = winapps._png(1, 1, bytes(4))

    def capture(window_id):
        calls.append(window_id)
        if len(calls) == 1:
            return png
        raise winapps.WinAppError("That window is not on screen anymore")

    monkeypatch.setattr(winapps, "winapps_window_screenshot", capture)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)
    assert list(winapps.winapps_window_stream(1234, 2.0)) == [png]
    assert calls == [1234, 1234]


@pytest.mark.parametrize("fps", [0, -1, 0.49, 8.01, float("nan"), float("inf")])
def test_window_stream_rejects_unbounded_frame_rates(host, fps):
    with pytest.raises(winapps.WinAppError, match="Frame rate"):
        next(winapps.winapps_window_stream(1234, fps))


def test_window_stream_refuses_a_stale_hwnd_before_the_first_frame(host, monkeypatch):
    def stale(_window_id):
        raise winapps.WinAppError("That window is not on screen anymore")

    monkeypatch.setattr(winapps, "winapps_window_screenshot", stale)
    with pytest.raises(winapps.WinAppError, match="not on screen"):
        next(winapps.winapps_window_stream(1234, 2.0))


def test_panic_stop_disarms_and_ends_an_open_stream(host, monkeypatch):
    png = winapps._png(1, 1, bytes(4))
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda _window_id: png)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)
    winapps.winapps_control_arm(True, "panel-a")
    stream = winapps.winapps_window_stream(1234, 2.0)
    assert next(stream) == png
    stopped = winapps.winapps_panic_stop()
    assert stopped["disarmed"] is True
    assert list(stream) == []
    assert winapps.winapps_control_state()["armed"] is False


def test_window_stream_stops_when_hwnd_is_reused_for_another_window(host, monkeypatch):
    png = winapps._png(1, 1, bytes(4))
    window = {"pid": 42, "app": "Example", "className": "Editor", "title": "first"}
    captures = []
    monkeypatch.setattr(winapps, "_validated_window", lambda _window_id: (1234, dict(window)))
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda hwnd: captures.append(hwnd) or png)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)

    stream = winapps.winapps_window_stream(1234, 2.0)
    assert next(stream) == png
    window["pid"] = 43
    with pytest.raises(StopIteration):
        next(stream)
    assert captures == [1234]


def test_window_stream_stops_when_hwnd_is_reused_on_another_thread(host, monkeypatch):
    png = winapps._png(1, 1, bytes(4))
    window = {"pid": 42, "app": "Example", "className": "Editor", "title": "same"}
    user32 = winapps._user32
    captures = []
    monkeypatch.setattr(winapps, "_validated_window", lambda _window_id: (1234, dict(window)))
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda hwnd: captures.append(hwnd) or png)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)

    stream = winapps.winapps_window_stream(1234, 2.0)
    assert next(stream) == png
    user32.thread_id += 1
    with pytest.raises(StopIteration):
        next(stream)
    assert captures == [1234]


def test_concurrent_window_streams_are_limited_and_release_their_slot(host, monkeypatch):
    png = winapps._png(1, 1, bytes(4))
    window = {"pid": 42, "app": "Example", "className": "Editor", "title": "first"}
    monkeypatch.setattr(winapps, "_STREAM_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(winapps, "_validated_window", lambda _window_id: (1234, window))
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda _hwnd: png)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)

    active = winapps.winapps_window_stream(1234, 2.0)
    assert next(active) == png
    rejected = winapps.winapps_window_stream(1234, 2.0)
    with pytest.raises(winapps.WinAppError, match="maximum number") as caught:
        next(rejected)
    assert caught.value.status == 429
    active.close()

    resumed = winapps.winapps_window_stream(1234, 2.0)
    assert next(resumed) == png
    resumed.close()


def test_hung_window_capture_uses_a_bounded_print_and_desktop_fallback(host, monkeypatch):
    user32 = FakeUser32()
    gdi32 = FakeGdi()
    host.setattr(winapps, "_user32", user32)
    host.setattr(winapps, "_gdi32", gdi32)

    result = winapps.winapps_window_screenshot(1234)

    winapps.validate_png_frame(result)
    assert user32.capture_messages == [
        (1234, winapps.WM_PRINT,
         winapps.PRF_CHECKVISIBLE | winapps.PRF_NONCLIENT | winapps.PRF_CLIENT
         | winapps.PRF_ERASEBKGND | winapps.PRF_CHILDREN,
         winapps.SMTO_BLOCK | winapps.SMTO_ABORTIFHUNG, winapps.CAPTURE_MESSAGE_TIMEOUT_MS)
    ]
    assert user32.desktop_dc_requests == 1 and gdi32.desktop_blits == 1


def test_hung_covered_window_fails_without_copying_other_windows(host, monkeypatch):
    user32 = FakeUser32(above=5678)
    gdi32 = FakeGdi()
    host.setattr(winapps, "_user32", user32)
    host.setattr(winapps, "_gdi32", gdi32)

    with pytest.raises(winapps.WinAppError, match="covered") as caught:
        winapps.winapps_window_screenshot(1234)

    assert caught.value.status == 504
    assert user32.desktop_dc_requests == 0 and gdi32.desktop_blits == 0


def test_png_frame_validation_rejects_bad_crc_and_oversized_dimensions():
    png = bytearray(winapps._png(1, 1, bytes(4)))
    png[-5] ^= 0x01
    with pytest.raises(winapps.WinAppError, match="corrupt PNG"):
        winapps.validate_png_frame(bytes(png))

    oversized = bytearray(winapps._png(1, 1, bytes(4)))
    oversized[16:24] = struct.pack(">II", winapps.MAX_CAPTURE_PIXELS + 1, 1)
    oversized[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + oversized[16:29]))
    with pytest.raises(winapps.WinAppError, match="dimensions"):
        winapps.validate_png_frame(bytes(oversized))


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


class FakeCaptureUser32(FakeUser32):
    def __init__(self, print_results):
        super().__init__()
        self.print_results = iter(print_results)
        self.print_flags = []
        self.gdi = None
        self.frame_pixel = (30, 20, 10, 0)

    def GetWindowDC(self, _hwnd):
        return 1

    def GetDC(self, _hwnd):
        return 2

    def ReleaseDC(self, _hwnd, _dc):
        return 1

    def PrintWindow(self, _hwnd, _dc, flags):
        self.print_flags.append(flags)
        captured = next(self.print_results, False)
        if captured and self.gdi:
            self.gdi.pixel = self.frame_pixel
        return captured


class FakeCaptureGdi:
    def __init__(self, *, pixel=(30, 20, 10, 0), desktop_pixel=(90, 80, 70, 0)):
        self.pixel = pixel
        self.desktop_pixel = desktop_pixel
        self.blit_calls = 0

    def CreateCompatibleDC(self, _dc):
        return 3

    def CreateCompatibleBitmap(self, _dc, _width, _height):
        return 4

    def SelectObject(self, _dc, _obj):
        return 5

    def PatBlt(self, _dc, _x, _y, _width, _height, _mode):
        self.pixel = (0, 0, 0, 0)
        return True

    def GetDIBits(self, _dc, _bitmap, _start, height, output, _info, _usage):
        for index in range(len(output)):
            output[index] = self.pixel[index % 4]
        return height

    def BitBlt(self, *_args):
        self.blit_calls += 1
        self.pixel = self.desktop_pixel
        return True

    def DeleteObject(self, _bitmap):
        return True

    def DeleteDC(self, _dc):
        return True


def test_screenshot_retries_printwindow_with_full_content_for_occluded_windows(host):
    user32 = FakeCaptureUser32([False, True])
    gdi32 = FakeCaptureGdi()
    user32.gdi = gdi32
    host.setattr(winapps, "_user32", user32)
    host.setattr(winapps, "_gdi32", gdi32)
    png = winapps.winapps_window_screenshot(1234)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert user32.print_flags == [0, winapps.PW_RENDERFULLCONTENT]
    assert gdi32.blit_calls == 0


def test_black_printwindow_frames_use_desktop_fallback_only_when_unoccluded(host):
    user32 = FakeCaptureUser32([True, True])
    gdi32 = FakeCaptureGdi()
    user32.gdi = gdi32
    user32.frame_pixel = (0, 0, 0, 0)
    host.setattr(winapps, "_user32", user32)
    host.setattr(winapps, "_gdi32", gdi32)
    assert winapps.winapps_window_screenshot(1234).startswith(b"\x89PNG\r\n\x1a\n")
    assert gdi32.blit_calls == 1


def test_black_printwindow_frames_do_not_fallback_through_an_occluding_window(host):
    class OccludedUser32(FakeCaptureUser32):
        def EnumWindows(self, proc, _lparam):
            return proc(99, 0) and proc(1234, 0)

        def GetWindowRect(self, hwnd, out_rect):
            if hwnd == 99:
                out_rect.left, out_rect.top, out_rect.right, out_rect.bottom = 20, 30, 80, 90
                return True
            return super().GetWindowRect(hwnd, out_rect)

    user32 = OccludedUser32([True, True])
    gdi32 = FakeCaptureGdi()
    user32.gdi = gdi32
    user32.frame_pixel = (0, 0, 0, 0)
    host.setattr(winapps, "_user32", user32)
    host.setattr(winapps, "_gdi32", gdi32)
    with pytest.raises(winapps.WinAppError, match="covered window"):
        winapps.winapps_window_screenshot(1234)
    assert gdi32.blit_calls == 0


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


def test_elements_are_window_relative_and_return_revision_diff(host, monkeypatch):
    original = {
        "elementId": "button-a", "role": "Button", "label": "Save",
        "x": 10, "y": 12, "w": 80, "h": 24, "enabled": True, "focused": False,
    }
    current = dict(original)
    monkeypatch.setattr(winapps, "_uia_read_elements",
                        lambda _hwnd, _window, **_kwargs: ([dict(current)], False))

    first = winapps.winapps_window_elements("1234")
    current["x"] = 20
    second = winapps.winapps_window_elements(1234, first["revision"])

    assert first["bounds"] == {"x": 10, "y": 20, "width": 320, "height": 240}
    assert first["elements"][0]["x"] == 10
    assert second["diff"]["changed"][0]["x"] == 20
    assert second["diff"]["changed"][0]["movedFrom"] == {"x": 10, "y": 12}


def test_element_order_and_revision_do_not_depend_on_provider_order(host, monkeypatch):
    elements = [
        {"elementId": "b", "role": "Button", "label": "B", "x": 20, "y": 10,
         "w": 20, "h": 10, "enabled": True, "focused": False},
        {"elementId": "a", "role": "Button", "label": "A", "x": 10, "y": 10,
         "w": 20, "h": 10, "enabled": True, "focused": False},
    ]
    ordered = [list(elements)]
    monkeypatch.setattr(winapps, "_uia_read_elements",
                        lambda _hwnd, _window, **_kwargs: (list(ordered[0]), False))
    window = winapps._window(1234)
    token = winapps._window_token(1234, window)

    first = winapps.winapps_window_elements(1234, expected_window_token=token)
    ordered[0].reverse()
    second = winapps.winapps_window_elements(
        1234, revision=first["revision"], expected_window_token=token,
    )

    assert [element["elementId"] for element in first["elements"]] == ["a", "b"]
    assert [element["elementId"] for element in second["elements"]] == ["a", "b"]
    assert second["revision"] == first["revision"]
    assert second["diff"] == {"added": [], "changed": [], "removed": []}


def test_elements_refuse_stale_windows_and_report_unsupported_uia(host, monkeypatch):
    monkeypatch.setattr(winapps, "_uia_read_elements", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        winapps.WinAppError("UI Automation is unavailable", status=501)
    ))
    with pytest.raises(winapps.WinAppError, match="UI Automation is unavailable") as caught:
        winapps.winapps_window_elements(1234)
    assert caught.value.status == 501

    host.setattr(winapps, "_user32", FakeUser32(visible=False))
    with pytest.raises(winapps.WinAppError, match="not on screen"):
        winapps.winapps_window_elements(1234)


def test_search_matches_roles_and_caps_results(host, monkeypatch):
    elements = [
        {"elementId": f"button-{index}", "role": "Button", "label": f"Action {index}",
         "x": index, "y": 0, "w": 10, "h": 10, "enabled": True, "focused": False}
        for index in range(70)
    ]
    monkeypatch.setattr(winapps, "_uia_read_elements",
                        lambda _hwnd, _window, **_kwargs: (elements, False))
    result = winapps.winapps_search_elements(1234, "button")
    assert result["count"] == winapps.MAX_UIA_SEARCH_RESULTS
    assert len(result["hits"]) == winapps.MAX_UIA_SEARCH_RESULTS
    assert all(hit["role"] == "Button" for hit in result["hits"])
    with pytest.raises(winapps.WinAppError, match="query must contain"):
        winapps.winapps_search_elements(1234, " " * (winapps.MAX_UIA_QUERY_CHARS + 1))


def test_control_lock_is_single_owner_expires_and_can_disarm(host, monkeypatch):
    armed = winapps.winapps_control_arm(True, "panel-a")
    assert armed["armed"] is True and armed["owner"] == "panel-a"
    with pytest.raises(winapps.WinAppError, match="Another dashboard") as caught:
        winapps.winapps_control_arm(True, "panel-b")
    assert caught.value.status == 409

    baseline = winapps.time.monotonic()
    monkeypatch.setattr(winapps.time, "monotonic", lambda: baseline + winapps.CONTROL_TIMEOUT_SECONDS + 1)
    expired = winapps.winapps_control_state()
    assert expired["armed"] is False and expired["owner"] is None and expired["expiresInSec"] == 0
    assert [row["kind"] for row in expired["recentActions"]] == ["arm"]
    assert expired["audit"][-1]["kind"] == "arm"
    assert winapps.winapps_control_arm(False)["armed"] is False


def _action_test_context(monkeypatch, *, focused=True):
    window = {
        "windowId": 1234, "pid": 42, "app": "Example", "className": "Editor", "title": "first",
        "x": 10, "y": 20, "width": 320, "height": 240,
    }
    element = {
        "elementId": "button-a", "role": "Button", "label": "Save",
        "x": 10, "y": 12, "w": 80, "h": 24, "enabled": True, "focused": focused,
    }
    elements = [element]
    hwnd = 1234
    token = winapps._window_token(hwnd, window)
    revision = winapps._element_revision(elements)
    monkeypatch.setattr(winapps, "_visible_window", lambda _window_id: (hwnd, window))
    monkeypatch.setattr(winapps, "_uia_read_elements_bounded",
                        lambda _hwnd, _window, **_kwargs: (elements, False))
    binding = {
        "windowId": hwnd, "windowToken": token, "revision": revision,
        "elementId": element["elementId"],
        "elementBounds": {key: element[key] for key in ("x", "y", "w", "h")},
        "owner": "panel-a", "confirm": True,
    }
    return hwnd, window, element, elements, token, binding


def test_click_requires_arm_owner_and_preview_confirmation(host, monkeypatch):
    hwnd, window, element, _elements, token, binding = _action_test_context(monkeypatch)
    clicks = []
    focuses = []
    monkeypatch.setattr(winapps, "_focus_window",
                        lambda _hwnd, _token=None: focuses.append((_hwnd, _token)))
    monkeypatch.setattr(winapps, "_send_mouse_action", lambda *args: clicks.append(args))
    action = {
        **binding, "actionId": "click-a",
        "x": element["x"] + element["w"] // 2, "y": element["y"] + element["h"] // 2,
    }

    with pytest.raises(winapps.WinAppError, match="not armed"):
        winapps.winapps_control_click(action)
    winapps.winapps_control_arm(True, "panel-a")
    with pytest.raises(winapps.WinAppError, match="Confirm"):
        winapps.winapps_control_click({**action, "confirm": False})
    with pytest.raises(winapps.WinAppError, match="Another dashboard"):
        winapps.winapps_control_click({**action, "owner": "panel-b"})
    assert clicks == []

    result = winapps.winapps_control_click(action)
    assert result["actionSent"] is True and result["x"] == 50 and len(clicks) == 1
    assert clicks[0][:6] == (hwnd, 50, 24, "click", 0, 0)
    assert clicks[0][6:] == (token, element)
    assert focuses == [(hwnd, token)]
    assert winapps.winapps_control_click(action) == result
    assert len(clicks) == 1
    with pytest.raises(winapps.WinAppError, match="already used"):
        winapps.winapps_control_click({**action, "action": "double_click"})
    assert any(
        row["kind"] == "click" and row["ok"] is True and row["windowId"] == hwnd
        for row in winapps.winapps_control_state()["audit"]
    )


def test_click_rejects_stale_preview_before_focusing_or_sending(host, monkeypatch):
    _hwnd, _window, _element, _elements, _token, binding = _action_test_context(monkeypatch)
    focuses = []
    clicks = []
    monkeypatch.setattr(winapps, "_focus_window",
                        lambda *_args: focuses.append(True))
    monkeypatch.setattr(winapps, "_send_mouse_action", lambda *_args: clicks.append(True))
    winapps.winapps_control_arm(True, "panel-a")
    action = {
        **binding, "actionId": "stale-click", "revision": "0" * 16,
        "x": 50, "y": 24,
    }

    with pytest.raises(winapps.WinAppError) as caught:
        winapps.winapps_control_click(action)

    assert caught.value.code == "UIA_STALE"
    assert focuses == [] and clicks == []


def test_input_allowlist_and_audit_never_store_typed_text(host, monkeypatch):
    hwnd, _window, _element, _elements, token, binding = _action_test_context(monkeypatch)
    inputs = []
    monkeypatch.setattr(winapps, "_ensure_foreground_target", lambda _hwnd, _token: {})
    monkeypatch.setattr(winapps, "_send_keyboard_input", lambda *args: inputs.append(args))
    winapps.winapps_control_arm(True, "panel-a")

    with pytest.raises(winapps.WinAppError, match="key must be one of"):
        winapps.winapps_control_input({
            **binding, "actionId": "bad-key", "kind": "key", "key": "alt-f4",
        })
    with pytest.raises(winapps.WinAppError, match="key must be one of"):
        winapps.winapps_control_input({
            **binding, "actionId": "space-key", "kind": "key", "key": "space",
        })
    with pytest.raises(winapps.WinAppError, match="printable characters"):
        winapps.winapps_control_input({
            **binding, "actionId": "too-long", "kind": "type",
            "text": "x" * (winapps.MAX_INPUT_TEXT_CHARS + 1),
        })

    secret = "local text"
    result = winapps.winapps_control_input({
        **binding, "actionId": "type-a", "kind": "type", "text": secret,
    })
    assert result["actionSent"] is True and result["textLength"] == len(secret)
    assert inputs == [(hwnd, "type", secret, None, token, _elements[0])]
    assert secret not in repr(winapps._AUDIT_ROWS)


@pytest.mark.parametrize("kind", ["double_click", "right_click", "scroll"])
def test_mouse_input_actions_require_arm_and_confirmation(host, monkeypatch, kind):
    hwnd, window, element, _elements, token, binding = _action_test_context(monkeypatch)
    gestures = []
    focuses = []
    monkeypatch.setattr(winapps, "_focus_window",
                        lambda _hwnd, _token=None: focuses.append((_hwnd, _token)))
    monkeypatch.setattr(winapps, "_send_mouse_action", lambda *args: gestures.append(args))
    winapps.winapps_control_arm(True, "panel-a")
    x, y = element["x"] + element["w"] // 2, element["y"] + element["h"] // 2
    request = {
        **binding, "actionId": f"mouse-{kind}", "kind": kind, "x": x, "y": y,
    }
    if kind == "scroll":
        request.update({"deltaX": -120, "deltaY": 240})
    with pytest.raises(winapps.WinAppError, match="Confirm"):
        winapps.winapps_control_input({**request, "confirm": False})
    response = winapps.winapps_control_input(request)
    assert response["actionSent"] is True and response["kind"] == kind
    assert focuses == [(hwnd, token)]
    assert gestures[-1][:6] == (
        hwnd, x, y, kind,
        -120 if kind == "scroll" else 0,
        240 if kind == "scroll" else 0,
    )
    assert gestures[-1][6:] == (token, element)


@pytest.mark.parametrize("payload", [
    {"kind": "scroll", "x": 50, "y": 24, "deltaX": 0, "deltaY": 0},
    {"kind": "scroll", "x": 50, "y": 24, "deltaX": 0, "deltaY": 1201},
    {"kind": "right_click", "x": "1", "y": 24},
    {"kind": "right_click", "x": 4, "y": 5},
])
def test_mouse_input_coordinates_and_scroll_deltas_are_bounded(host, monkeypatch, payload):
    _hwnd, _window, _element, _elements, _token, binding = _action_test_context(monkeypatch)
    with pytest.raises(winapps.WinAppError):
        winapps._validated_input({
            **binding, "actionId": "bounded-mouse", **payload,
        })


class FakeMouseUser32:
    def __init__(self):
        self.events = []

    def GetSystemMetrics(self, index):
        return {76: -1920, 77: -100, 78: 3840, 79: 2160}[index]

    def WindowFromPoint(self, _point):
        return 1234

    def GetAncestor(self, hwnd, _flag):
        return hwnd

    def SendInput(self, count, events, _size):
        self.events = [
            (events[index].mi.dx, events[index].mi.dy, events[index].mi.mouseData, events[index].mi.dwFlags)
            for index in range(count)
        ]
        return count


def test_mouse_gestures_use_physical_virtual_desktop_coordinates_and_bounded_events(host):
    user32 = FakeMouseUser32()
    host.setattr(winapps, "_user32", user32)
    window = {"x": 0, "y": 0, "width": 320, "height": 240}
    winapps._send_mouse_gesture(1234, 50, 40, window, "double_click")
    assert len(user32.events) == 5
    expected_x = round((50 + 1920) * 65535 / 3839)
    expected_y = round((40 + 100) * 65535 / 2159)
    assert user32.events[0] == (
        expected_x, expected_y, 0,
        winapps.MOUSEEVENTF_MOVE | winapps.MOUSEEVENTF_ABSOLUTE | winapps.MOUSEEVENTF_VIRTUALDESK,
    )
    assert [event[3] for event in user32.events[1:]] == [
        winapps.MOUSEEVENTF_LEFTDOWN, winapps.MOUSEEVENTF_LEFTUP,
        winapps.MOUSEEVENTF_LEFTDOWN, winapps.MOUSEEVENTF_LEFTUP,
    ]

    winapps._send_mouse_gesture(1234, 50, 40, window, "right_click")
    assert [event[3] for event in user32.events[1:]] == [
        winapps.MOUSEEVENTF_RIGHTDOWN, winapps.MOUSEEVENTF_RIGHTUP,
    ]

    winapps._send_mouse_gesture(1234, 50, 40, window, "scroll", -120, 240)
    assert user32.events[-2][2:] == (240, winapps.MOUSEEVENTF_WHEEL)
    assert user32.events[-1][2:] == (0xFFFFFF88, winapps.MOUSEEVENTF_HWHEEL)


def test_mouse_input_refuses_a_point_covered_by_another_window(host):
    class CoveredUser32(FakeMouseUser32):
        def WindowFromPoint(self, _point):
            return 99

    user32 = CoveredUser32()
    host.setattr(winapps, "_user32", user32)
    with pytest.raises(winapps.WinAppError, match="covered by another window"):
        winapps._send_mouse_gesture(
            1234, 50, 40, {"x": 0, "y": 0, "width": 320, "height": 240}, "right_click",
        )
    assert user32.events == []


def test_control_state_returns_bounded_audit_metadata_without_typed_content(host):
    for index in range(winapps.CONTROL_AUDIT_DISPLAY_MAX + 3):
        winapps._record_audit("input", detail={
            "action": "type", "textLength": index, "ok": True, "secret": "must not be exposed",
        })
    state = winapps.winapps_control_state()
    assert len(state["recentActions"]) == winapps.CONTROL_AUDIT_DISPLAY_MAX
    assert state["recentActions"][-1]["textLength"] == winapps.CONTROL_AUDIT_DISPLAY_MAX + 2
    assert "secret" not in repr(state)


def test_keyboard_input_is_not_sent_if_the_target_loses_foreground(host, monkeypatch):
    sends = []
    monkeypatch.setattr(winapps._user32, "SendInput",
                        lambda *args: sends.append(args) or 1, raising=False)

    def lost_focus(_hwnd, _token):
        raise winapps.WinAppError("The selected window lost focus", status=409, code="FOCUS_LOST")

    monkeypatch.setattr(winapps, "_ensure_foreground_target", lost_focus)
    with pytest.raises(winapps.WinAppError) as caught:
        winapps._send_keyboard_input(1234, "type", "sensitive", expected_token="a" * 24)

    assert caught.value.code == "FOCUS_LOST"
    assert sends == []


def test_focus_uses_uia_without_requesting_foreground_from_the_browser(host, monkeypatch):
    hwnd, window, _element, _elements, token, _binding = _action_test_context(monkeypatch)

    def focus(target):
        assert target == hwnd

    monkeypatch.setattr(winapps, "_uia_focus_window", focus)
    monkeypatch.setattr(winapps._user32, "GetForegroundWindow", lambda: hwnd, raising=False)
    monkeypatch.setattr(winapps._user32, "GetAncestor", lambda target, _flag: target, raising=False)
    monkeypatch.setattr(
        winapps._user32, "SetForegroundWindow",
        lambda *_args: pytest.fail("the console must not request foreground from the browser"),
        raising=False,
    )
    monkeypatch.setattr(
        winapps._user32, "BringWindowToTop",
        lambda *_args: pytest.fail("the console must not steal foreground from the browser"),
        raising=False,
    )

    winapps._focus_window(hwnd, token)


# ── hooks used by the policy gate ────────────────────────────────────────────

def test_errors_carry_codes(host):
    assert winapps.WinAppError("x").code == "WINAPP_ERROR"
    with pytest.raises(winapps.WinAppError) as invalid:
        winapps.winapps_window_screenshot("not-a-window")
    assert invalid.value.code == "INVALID_WINDOW"
    host.setattr(winapps, "_user32", FakeUser32(root=999))
    with pytest.raises(winapps.WinAppError) as gone:
        winapps.winapps_window_screenshot(1234)
    assert gone.value.code == "WINDOW_GONE"


def test_window_info_returns_the_window_and_none_for_a_stale_id(host):
    assert winapps.window_info(1234)["app"] == "Example"
    host.setattr(winapps, "_user32", FakeUser32(root=999))
    assert winapps.window_info(1234) is None
    assert winapps.window_info(0) is None and winapps.window_info(True) is None
    assert winapps.window_info("1234") is None and winapps.window_info(2 ** 40) is None


def test_doctor_honours_can_probe(host):
    host.setattr(winapps, "_user32", type("U", (FakeUser32,), {"GetShellWindow": lambda self: 1})())
    probed = []
    host.setattr(winapps, "winapps_window_screenshot", lambda hwnd: probed.append(hwnd) or b"\x89PNG\r\n\x1a\n")
    result = winapps.doctor(can_probe=lambda window: False)
    assert probed == [] and result["capture"] is False and result["windows"] == 1
    assert result["reason"] == "No on-screen window to probe"
    assert winapps.doctor(can_probe=lambda window: True)["capture"] is True and probed == [1234]


def test_doctor_uses_the_given_capture_function(host):
    host.setattr(winapps, "_user32", type("U", (FakeUser32,), {"GetShellWindow": lambda self: 1})())
    host.setattr(winapps, "winapps_window_screenshot", lambda hwnd: (_ for _ in ()).throw(AssertionError("raw")))
    result = winapps.doctor(capture=lambda hwnd: b"\x89PNG\r\n\x1a\n")
    assert result["capture"] is True


def test_desktop_locked_is_true_when_the_input_desktop_cannot_be_opened(host):
    closed = []

    class WithDesktop(FakeUser32):
        def __init__(self, handle):
            super().__init__()
            self.handle = handle

        def OpenInputDesktop(self, _flags, _inherit, _access):
            return self.handle

        def CloseDesktop(self, handle):
            closed.append(handle)
            return True

    host.setattr(winapps, "_user32", WithDesktop(77))
    assert winapps.desktop_locked() is False and closed == [77]
    host.setattr(winapps, "_user32", WithDesktop(0))
    assert winapps.desktop_locked() is True and closed == [77]
    host.setattr(winapps.sys, "platform", "linux")
    assert winapps.desktop_locked() is None
