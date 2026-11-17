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
                 visible=True, iconic=False, root=None, rect=(10, 20, 330, 260), dpi=96):
        self.style, self.ex_style, self.class_name = style, ex_style, class_name
        self.visible, self.iconic, self.root, self.rect = visible, iconic, root, rect
        self.dpi = dpi
        self.dpi_context = 0x1234
        self.dpi_context_calls = []

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

    def capture(window_id):
        calls.append(window_id)
        if len(calls) == 1:
            return b"first-frame"
        raise winapps.WinAppError("That window is not on screen anymore")

    monkeypatch.setattr(winapps, "winapps_window_screenshot", capture)
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)
    assert list(winapps.winapps_window_stream(1234, 2.0)) == [b"first-frame"]
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
    monkeypatch.setattr(winapps, "winapps_window_screenshot", lambda _window_id: b"frame")
    monkeypatch.setattr(winapps.time, "sleep", lambda _seconds: None)
    winapps.winapps_control_arm(True, "panel-a")
    stream = winapps.winapps_window_stream(1234, 2.0)
    assert next(stream) == b"frame"
    stopped = winapps.winapps_panic_stop()
    assert stopped["disarmed"] is True
    assert list(stream) == []
    assert winapps.winapps_control_state()["armed"] is False


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
    monkeypatch.setattr(winapps, "_uia_read_elements", lambda _hwnd, _window: ([dict(current)], False))

    first = winapps.winapps_window_elements("1234")
    current["x"] = 20
    second = winapps.winapps_window_elements(1234, first["revision"])

    assert first["bounds"] == {"x": 10, "y": 20, "width": 320, "height": 240}
    assert first["elements"][0]["x"] == 10
    assert second["diff"]["changed"][0]["x"] == 20
    assert second["diff"]["changed"][0]["movedFrom"] == {"x": 10, "y": 12}


def test_elements_refuse_stale_windows_and_report_unsupported_uia(host, monkeypatch):
    monkeypatch.setattr(winapps, "_uia_read_elements", lambda *_args: (_ for _ in ()).throw(
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
    monkeypatch.setattr(winapps, "_uia_read_elements", lambda _hwnd, _window: (elements, False))
    result = winapps.winapps_search_elements(1234, "button")
    assert result["count"] == winapps.MAX_UIA_SEARCH_RESULTS
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
    assert winapps.winapps_control_arm(False)["armed"] is False


def test_click_requires_arm_owner_and_preview_confirmation(host, monkeypatch):
    window = {"windowId": 1234, "app": "Example", "x": 10, "y": 20, "width": 320, "height": 240}
    clicks = []
    monkeypatch.setattr(winapps, "_visible_window", lambda _window_id: (1234, window))
    monkeypatch.setattr(winapps, "_focus_window", lambda _hwnd: None)
    monkeypatch.setattr(winapps, "_send_mouse_click", lambda *args: clicks.append(args))
    action = {"windowId": 1234, "x": 10, "y": 20, "owner": "panel-a", "confirm": True}

    with pytest.raises(winapps.WinAppError, match="not armed"):
        winapps.winapps_control_click(action)
    winapps.winapps_control_arm(True, "panel-a")
    with pytest.raises(winapps.WinAppError, match="Confirm"):
        winapps.winapps_control_click({**action, "confirm": False})
    with pytest.raises(winapps.WinAppError, match="Another dashboard"):
        winapps.winapps_control_click({**action, "owner": "panel-b"})
    assert clicks == []

    result = winapps.winapps_control_click(action)
    assert result["actionSent"] is True and result["x"] == 10 and len(clicks) == 1


def test_input_allowlist_and_audit_never_store_typed_text(host, monkeypatch):
    window = {"windowId": 1234, "app": "Example", "x": 10, "y": 20, "width": 320, "height": 240}
    inputs = []
    monkeypatch.setattr(winapps, "_visible_window", lambda _window_id: (1234, window))
    monkeypatch.setattr(winapps, "_focus_window", lambda _hwnd: None)
    monkeypatch.setattr(winapps, "_send_keyboard_input", lambda *args: inputs.append(args))
    winapps.winapps_control_arm(True, "panel-a")

    with pytest.raises(winapps.WinAppError, match="key must be one of"):
        winapps.winapps_control_input({
            "windowId": 1234, "kind": "key", "key": "alt-f4", "owner": "panel-a", "confirm": True,
        })
    with pytest.raises(winapps.WinAppError, match="key must be one of"):
        winapps.winapps_control_input({
            "windowId": 1234, "kind": "key", "key": "space", "owner": "panel-a", "confirm": True,
        })
    with pytest.raises(winapps.WinAppError, match="printable characters"):
        winapps.winapps_control_input({
            "windowId": 1234, "kind": "type", "text": "x" * (winapps.MAX_INPUT_TEXT_CHARS + 1),
            "owner": "panel-a", "confirm": True,
        })

    secret = "local text"
    result = winapps.winapps_control_input({
        "windowId": 1234, "kind": "type", "text": secret, "owner": "panel-a", "confirm": True,
    })
    assert result["actionSent"] is True and result["textLength"] == len(secret)
    assert inputs == [(1234, "type", secret, None)]
    assert secret not in repr(winapps._AUDIT_ROWS)


@pytest.mark.parametrize("kind", ["double_click", "right_click", "scroll"])
def test_mouse_input_actions_require_arm_and_confirmation(host, monkeypatch, kind):
    window = {"windowId": 1234, "app": "Example", "x": 10, "y": 20, "width": 320, "height": 240}
    gestures = []
    monkeypatch.setattr(winapps, "_visible_window", lambda _window_id: (1234, window))
    monkeypatch.setattr(winapps, "_focus_window", lambda _hwnd: None)
    monkeypatch.setattr(winapps, "_send_mouse_gesture", lambda *args: gestures.append(args))
    winapps.winapps_control_arm(True, "panel-a")
    request = {
        "windowId": 1234, "kind": kind, "x": 40, "y": 50,
        "owner": "panel-a", "confirm": True,
    }
    if kind == "scroll":
        request.update({"deltaX": -120, "deltaY": 240})
    with pytest.raises(winapps.WinAppError, match="Confirm"):
        winapps.winapps_control_input({**request, "confirm": False})
    response = winapps.winapps_control_input(request)
    assert response["actionSent"] is True and response["kind"] == kind
    assert gestures[-1][1:5] == (40, 50, window, kind)


@pytest.mark.parametrize("payload", [
    {"kind": "scroll", "x": 10, "y": 10, "deltaX": 0, "deltaY": 0},
    {"kind": "scroll", "x": 10, "y": 10, "deltaX": 0, "deltaY": 1201},
    {"kind": "right_click", "x": "1", "y": 10},
])
def test_mouse_input_coordinates_and_scroll_deltas_are_bounded(host, payload):
    with pytest.raises(winapps.WinAppError):
        winapps._validated_input({
            "windowId": 1234, "owner": "panel-a", "confirm": True, **payload,
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
