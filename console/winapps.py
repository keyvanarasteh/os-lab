"""Native Windows app mirror with guarded UI Automation observation and input.

The macOS Lab uses CoreGraphics through ctypes; this is the Windows counterpart.
It uses a bounded WM_PRINT request with a visibility-checked desktop fallback,
uses only standard-library ctypes, and needs no elevated process. Input stays
disabled until a single-owner, expiring arm lock is explicitly enabled.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import struct
import sys
import threading
import time
import unicodedata
import zlib
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Iterator

PW_RENDERFULLCONTENT = 0x00000002
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
GA_ROOT = 2
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation
MAX_TITLE_CHARS = 512
MAX_WINDOW_CHARS = 200
# 8K at 32 bits is ~130 MB of pixels; anything larger is refused instead of exhausting memory.
MAX_CAPTURE_PIXELS = 7680 * 4320
MAX_PNG_FRAME_BYTES = MAX_CAPTURE_PIXELS * 4 + 1024 * 1024
MIN_STREAM_FPS = 0.5
MAX_STREAM_FPS = 8.0
DEFAULT_STREAM_FPS = 1.2
MAX_STREAM_SECONDS = 600
MAX_ACTIVE_STREAMS = 2
CAPTURE_MESSAGE_TIMEOUT_MS = 1500
WM_PRINT = 0x0317
PRF_CHECKVISIBLE = 0x00000001
PRF_NONCLIENT = 0x00000002
PRF_CLIENT = 0x00000004
PRF_ERASEBKGND = 0x00000008
PRF_CHILDREN = 0x00000010
SMTO_BLOCK = 0x00000001
SMTO_ABORTIFHUNG = 0x00000002
GW_HWNDPREV = 3
MAX_UIA_ELEMENTS = 150
MAX_UIA_SEARCH_RESULTS = 50
MAX_UIA_QUERY_CHARS = 120
MAX_UIA_WORKERS = 2
UIA_READ_TIMEOUT_SECONDS = 3.0
CONTROL_TIMEOUT_SECONDS = 600
CONTROL_AUDIT_MAX = 200
CONTROL_AUDIT_DISPLAY_MAX = 12
MAX_INPUT_TEXT_CHARS = 200
MAX_SCROLL_DELTA = 1200
MAX_ACTION_CACHE = CONTROL_AUDIT_MAX
INPUT_KEYS = {
    "tab": 0x09,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "enter": 0x0D,
}
INPUT_MOUSE_KINDS = {"double_click", "right_click", "scroll"}
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
TOOL_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "ThumbnailDeviceHelperWnd",
    "PseudoConsoleWindow",
}


DESKTOP_SWITCHDESKTOP = 0x0100  # OpenInputDesktop access: fails while the lock screen or a UAC prompt is up

class WinAppError(Exception):
    """A safe, user-presentable native window inventory/capture failure."""

    def __init__(self, message: str, *, status: int = 400, code: str = "WINAPP_ERROR"):
        super().__init__(message)
        self.status = status
        self.code = code


# Keep the Win32 data layout available to the offline tests on other hosts.
class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_ubyte * 4)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", _INPUTUNION)]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _VARIANTUNION(ctypes.Union):
    _fields_ = [
        ("lVal", ctypes.c_int32), ("llVal", ctypes.c_int64), ("boolVal", ctypes.c_int16),
        ("bstrVal", ctypes.c_void_p), ("parray", ctypes.c_void_p), ("dblVal", ctypes.c_double),
    ]


class _VARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_uint16), ("wReserved1", ctypes.c_uint16),
        ("wReserved2", ctypes.c_uint16), ("wReserved3", ctypes.c_uint16),
        ("value", _VARIANTUNION),
    ]


_ENUM_WINDOWS_PROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_COM_CALL = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_CLSID_CUIAUTOMATION = _GUID(0xFF48DBA4, 0x60EF, 0x4201,
                             (ctypes.c_ubyte * 8)(0xAA, 0x87, 0x54, 0x10, 0x3E, 0xEF, 0x59, 0x4E))
_IID_IUIAUTOMATION = _GUID(0x30CBE57D, 0xD9D0, 0x452A,
                           (ctypes.c_ubyte * 8)(0xAB, 0x13, 0x7A, 0xC5, 0xAC, 0x48, 0x25, 0xEE))


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
    try:
        _uia_core = ctypes.WinDLL("UIAutomationCore", use_last_error=True)
    except OSError:
        _uia_core = None

    _user32.EnumWindows.argtypes = [_ENUM_WINDOWS_PROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    if not hasattr(_user32, "GetWindowLongPtrW"):  # 32-bit user32 exports only GetWindowLongW
        _user32.GetWindowLongPtrW = _user32.GetWindowLongW
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetWindowDC.argtypes = [wintypes.HWND]
    _user32.GetWindowDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    _user32.SendMessageTimeoutW.restype = ctypes.c_size_t
    if hasattr(_user32, "SetProcessDpiAwarenessContext"):  # Windows 10 1703+; older hosts use Shcore
        _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if hasattr(_user32, "SetThreadDpiAwarenessContext"):
            _user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            _user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        if hasattr(_user32, "GetDpiForWindow"):
            _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            _user32.GetDpiForWindow.restype = wintypes.UINT

    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HBITMAP]
    _gdi32.SelectObject.restype = wintypes.HBITMAP
    _gdi32.DeleteObject.argtypes = [wintypes.HBITMAP]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.DeleteDC.restype = wintypes.BOOL
    _gdi32.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.PatBlt.restype = wintypes.BOOL
    _gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    _gdi32.BitBlt.restype = wintypes.BOOL
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), ctypes.c_uint,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcessId.argtypes = []
    _kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    _kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    _user32.GetShellWindow.argtypes = []
    _user32.GetShellWindow.restype = wintypes.HWND
    _user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _user32.OpenInputDesktop.restype = wintypes.HANDLE
    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.CloseDesktop.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.WindowFromPoint.argtypes = [_POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = ctypes.c_uint

    _ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    _ole32.CoCreateInstance.restype = ctypes.c_long
    _oleaut32.VariantClear.argtypes = [ctypes.POINTER(_VARIANT)]
    _oleaut32.VariantClear.restype = ctypes.c_long
    _oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
    _oleaut32.SysStringLen.restype = ctypes.c_uint
    _oleaut32.SafeArrayGetDim.argtypes = [ctypes.c_void_p]
    _oleaut32.SafeArrayGetDim.restype = ctypes.c_uint
    _oleaut32.SafeArrayGetLBound.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
    _oleaut32.SafeArrayGetLBound.restype = ctypes.c_long
    _oleaut32.SafeArrayGetUBound.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
    _oleaut32.SafeArrayGetUBound.restype = ctypes.c_long
    _oleaut32.SafeArrayGetElement.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_long), ctypes.c_void_p]
    _oleaut32.SafeArrayGetElement.restype = ctypes.c_long

    _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT

    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
    ]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
else:
    _user32 = _gdi32 = _kernel32 = _dwmapi = _advapi32 = None
    _ole32 = _oleaut32 = _uia_core = None

_STREAM_SLOTS = threading.BoundedSemaphore(MAX_ACTIVE_STREAMS)


def _set_dpi_awareness() -> None:
    """Set per-monitor DPI awareness once, so coordinates stay physical pixels."""
    if sys.platform != "win32":
        return
    if _user32 is not None and hasattr(_user32, "SetProcessDpiAwarenessContext") and (
        _user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    ):
        return
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        # The Shcore API only knows PROCESS_PER_MONITOR_DPI_AWARE (2), i.e. v1 per-monitor awareness.
        shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass


_set_dpi_awareness()


@contextmanager
def _physical_dpi_context():
    """Use physical screen pixels for Win32 bounds and input, even with a host manifest."""
    set_context = getattr(_user32, "SetThreadDpiAwarenessContext", None)
    if not callable(set_context):
        yield
        return
    previous = set_context(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    if not previous:
        yield
        return
    try:
        yield
    finally:
        set_context(previous)


def _window_dpi(hwnd: int) -> int | None:
    get_dpi = getattr(_user32, "GetDpiForWindow", None)
    if not callable(get_dpi):
        return None
    dpi = int(get_dpi(hwnd))
    return dpi if 48 <= dpi <= 768 else None


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "windows": []}


def _token_elevated(process: Any) -> bool | None:
    """Whether a process handle's token is elevated; None when Windows will not tell us.

    A standard-user console may be refused the token of an elevated process, so None is an
    honest "unknown" and never a silent False.
    """
    if _advapi32 is None:
        return None
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        elevation = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not _advapi32.GetTokenInformation(
            token, TOKEN_ELEVATION, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(returned)
        ):
            return None
        return bool(elevation.value)
    finally:
        _kernel32.CloseHandle(token)


def _process_info(pid: int) -> tuple[str, bool | None]:
    """The executable basename and elevation for one pid, without command-line data."""
    if _kernel32 is None:
        return "", None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "", None
    try:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(1024)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, path, size):
            return "", None
        return Path(path.value).stem, _token_elevated(handle)
    finally:
        _kernel32.CloseHandle(handle)


def _cloaked(hwnd: int) -> bool:
    """DWM-cloaked windows are 'visible' to Win32 but not on screen (suspended UWP, other desktops)."""
    if _dwmapi is None:
        return False
    cloaked = wintypes.DWORD()
    if _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) != 0:
        return False
    return bool(cloaked.value)


def _window(hwnd: int) -> dict[str, Any] | None:
    """One on-screen, non-iconic top-level window, or None for shell/tool/cloaked windows."""
    if _user32 is None or not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return None
    if _cloaked(hwnd):
        return None
    style = int(_user32.GetWindowLongPtrW(hwnd, -16)) & 0xFFFFFFFF
    if not style & WS_CAPTION:
        return None
    ex_style = int(_user32.GetWindowLongPtrW(hwnd, -20)) & 0xFFFFFFFF
    if ex_style & WS_EX_TOOLWINDOW:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, pid)
    if not pid.value:
        return None
    length = _user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(max(1, length + 1))
    if length:
        _user32.GetWindowTextW(hwnd, title, length + 1)
    class_name = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, class_name, 256)
    if not class_name.value or class_name.value in TOOL_CLASSES:
        return None
    with _physical_dpi_context():
        rect = _RECT()
        if not _user32.GetWindowRect(hwnd, rect):
            return None
        dpi = _window_dpi(hwnd)
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    app, elevated = _process_info(pid.value)
    if not app:
        return None
    return {
        "windowId": int(hwnd),
        "pid": int(pid.value),
        "app": app[:MAX_WINDOW_CHARS],
        "elevated": elevated,
        "title": title.value[:MAX_TITLE_CHARS],
        "className": class_name.value[:MAX_WINDOW_CHARS],
        "x": int(rect.left),
        "y": int(rect.top),
        "width": int(width),
        "height": int(height),
        "dpi": dpi,
    }


def _win_windows() -> list[dict[str, Any]]:
    """Enumerate visible top-level windows with ctypes; no Screen Recording equivalent is needed."""
    if sys.platform != "win32":
        raise WinAppError("Native Windows window inventory needs a Windows host")
    windows: list[dict[str, Any]] = []
    seen: set[int] = set()

    def callback(hwnd: int, _lparam: int) -> bool:
        # Tool windows often have no visible owner, so accept only their own root window.
        if _user32 is not None and _user32.GetAncestor(hwnd, GA_ROOT) == hwnd:
            window = _window(hwnd)
            if window and window["windowId"] not in seen:
                seen.add(window["windowId"])
                windows.append(window)
        return True

    if not _user32.EnumWindows(_ENUM_WINDOWS_PROC(callback), 0):
        raise WinAppError("Windows window enumeration failed")
    windows.sort(key=lambda window: (window["app"].casefold(), window["title"].casefold(), window["windowId"]))
    return windows


def winapps_windows() -> dict[str, Any]:
    """The panel's visible top-level window inventory."""
    if sys.platform != "win32":
        return unavailable("Native Windows app mirror needs a Windows host")
    try:
        windows = _win_windows()
    except WinAppError as exc:
        return unavailable(str(exc))
    for window in windows:
        window["windowToken"] = _window_token(window["windowId"], window)
    return {"available": True, "reason": None, "windows": windows}


def _png(width: int, height: int, bgra: bytes) -> bytes:
    """Encode a 32-bit BGRA buffer as an opaque RGBA PNG with only the standard library.

    GDI drawing into a 32-bit bitmap routinely leaves the alpha byte at 0, which a browser would
    show as an empty image, so a window capture is always written fully opaque.
    """
    rgba = bytearray(bgra)
    rgba[0::4] = bgra[2::4]  # slice assignment keeps the channel swap in C, not a per-pixel loop
    rgba[2::4] = bgra[0::4]
    rgba[3::4] = b"\xff" * (width * height)
    stride = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 (None)
        raw += rgba[row * stride:(row + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 3)) + chunk(b"IEND", b"")


def validate_png_frame(frame: bytes) -> None:
    """Reject malformed or oversized capture frames before they reach a stream client."""
    if not isinstance(frame, bytes) or len(frame) > MAX_PNG_FRAME_BYTES or len(frame) < 57:
        raise WinAppError("The Windows window capture returned an invalid PNG frame", status=502)
    if frame[:8] != b"\x89PNG\r\n\x1a\n":
        raise WinAppError("The Windows window capture returned an invalid PNG frame", status=502)
    position = 8
    width = height = 0
    seen_ihdr = seen_idat = seen_iend = False
    while position < len(frame):
        if position + 12 > len(frame):
            raise WinAppError("The Windows window capture returned an invalid PNG frame", status=502)
        length = struct.unpack(">I", frame[position:position + 4])[0]
        kind = frame[position + 4:position + 8]
        end = position + 12 + length
        if end > len(frame):
            raise WinAppError("The Windows window capture returned an invalid PNG frame", status=502)
        payload = frame[position + 8:position + 8 + length]
        checksum = struct.unpack(">I", frame[position + 8 + length:end])[0]
        if checksum != zlib.crc32(kind + payload):
            raise WinAppError("The Windows window capture returned a corrupt PNG frame", status=502)
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                raise WinAppError("The Windows window capture returned an invalid PNG header", status=502)
            width, height = struct.unpack(">II", payload[:8])
            if width <= 0 or height <= 0 or width * height > MAX_CAPTURE_PIXELS:
                raise WinAppError("The Windows window capture returned invalid PNG dimensions", status=502)
            seen_ihdr = True
        elif kind == b"IHDR":
            raise WinAppError("The Windows window capture returned an invalid PNG header", status=502)
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            if length != 0 or end != len(frame):
                raise WinAppError("The Windows window capture returned an invalid PNG end marker", status=502)
            seen_iend = True
            break
        position = end
    if not (seen_ihdr and seen_idat and seen_iend):
        raise WinAppError("The Windows window capture returned an incomplete PNG frame", status=502)


def _window_unoccluded(hwnd: int, window: dict[str, Any]) -> bool:
    """Only allow desktop-pixel fallback when no higher window overlaps the target."""
    if _user32 is None:
        return False
    left, top = window["x"], window["y"]
    right, bottom = left + window["width"], top + window["height"]
    if hasattr(_user32, "GetWindow"):
        above = _user32.GetWindow(hwnd, GW_HWNDPREV)
        for _ in range(512):
            if not above:
                break
            if _user32.IsWindowVisible(above) and not _user32.IsIconic(above) and not _cloaked(above):
                rect = _RECT()
                if _user32.GetWindowRect(above, rect):
                    if max(left, rect.left) < min(right, rect.right) and max(top, rect.top) < min(bottom, rect.bottom):
                        return False
            above = _user32.GetWindow(above, GW_HWNDPREV)
        else:
            return False
    if hasattr(_user32, "EnumWindows"):
        found = False
        occluded = False

        def callback(candidate: int, _lparam: int) -> bool:
            nonlocal found, occluded
            if candidate == hwnd:
                found = True
                return False
            if not found and _user32.IsWindowVisible(candidate) and not _user32.IsIconic(candidate) \
                    and not _cloaked(candidate):
                rect = _RECT()
                if _user32.GetWindowRect(candidate, rect) and (
                    max(left, rect.left) < min(right, rect.right)
                    and max(top, rect.top) < min(bottom, rect.bottom)
                ):
                    occluded = True
                    return False
            return True

        _user32.EnumWindows(_ENUM_WINDOWS_PROC(callback), 0)
        return found and not occluded
    return hasattr(_user32, "GetWindow")


def _send_bounded_window_print(hwnd: int, memory_dc: Any) -> bool:
    """Ask the target to paint through a bounded WM_PRINT instead of blocking in PrintWindow."""
    result = ctypes.c_size_t()
    flags = PRF_CHECKVISIBLE | PRF_NONCLIENT | PRF_CLIENT | PRF_ERASEBKGND | PRF_CHILDREN
    return bool(_user32.SendMessageTimeoutW(
        hwnd, WM_PRINT, memory_dc, flags, SMTO_BLOCK | SMTO_ABORTIFHUNG,
        CAPTURE_MESSAGE_TIMEOUT_MS, ctypes.byref(result),
    ))


def _capture_desktop_fallback(memory_dc: Any, window: dict[str, Any]) -> bool:
    """Copy visible desktop pixels only when the target bounds are unobscured."""
    screen_dc = _user32.GetDC(0)
    if not screen_dc:
        return False
    try:
        return bool(_gdi32.BitBlt(
            memory_dc, 0, 0, window["width"], window["height"],
            screen_dc, window["x"], window["y"], 0x00CC0020 | 0x40000000,
        ))
    finally:
        _user32.ReleaseDC(0, screen_dc)


def _bitmap_pixels(memory_dc: Any, bitmap: Any, old_bitmap: Any, width: int, height: int) -> bytes:
    _gdi32.SelectObject(memory_dc, old_bitmap)
    bitmap_info = _BITMAPINFO()
    bitmap_info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bitmap_info.bmiHeader.biWidth = width
    bitmap_info.bmiHeader.biHeight = -height
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap_info.bmiHeader.biCompression = 0
    bitmap_info.bmiHeader.biSizeImage = width * height * 4
    pixels = (ctypes.c_ubyte * (width * height * 4))()
    rows = _gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(bitmap_info), 0)
    _gdi32.SelectObject(memory_dc, bitmap)
    if rows != height:
        raise WinAppError("Could not read the captured window pixels")
    return bytes(pixels)


def _black_frame(bgra: bytes) -> bool:
    """Sample every fourth pixel; a blank PrintWindow result is retried, not shown as a frame."""
    return not any(bgra[0::16]) and not any(bgra[1::16]) and not any(bgra[2::16])


def window_info(window_id: int) -> dict[str, Any] | None:
    """The current on-screen window for one id (same filters as the inventory), or None when gone.

    The policy gate (console/winapps_guard.py) reads the title through this at the moment of an
    action, so a window that turned restricted after the inventory is caught.
    """
    if sys.platform != "win32" or _user32 is None:
        return None
    if isinstance(window_id, bool) or not isinstance(window_id, int) or not 0 < window_id <= 0xFFFFFFFF:
        return None
    return _window(window_id) if _user32.GetAncestor(window_id, GA_ROOT) == window_id else None


def desktop_locked() -> bool | None:
    """True when this process cannot open the input desktop, i.e. the lock screen or a UAC prompt is up.

    A process that is not allowed to ask also gets True, which is the safe answer for an input gate.
    None means this is not a Windows host.
    """
    if sys.platform != "win32" or _user32 is None:
        return None
    desktop = _user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return True
    _user32.CloseDesktop(desktop)
    return False


def _validated_window(window_id: int | str) -> tuple[int, dict[str, Any]]:
    try:
        hwnd = int(window_id)
    except (TypeError, ValueError):
        raise WinAppError("Invalid window id", code="INVALID_WINDOW") from None
    if not 0 < hwnd <= 0xFFFFFFFF:
        raise WinAppError("Invalid window id", code="INVALID_WINDOW")
    window = window_info(hwnd)
    if window is None:
        raise WinAppError("That window is not on screen anymore; refresh the mirror", code="WINDOW_GONE")
    if window["width"] * window["height"] > MAX_CAPTURE_PIXELS:
        raise WinAppError("That window is too large to capture")
    return hwnd, window


def _window_identity(hwnd: int, window: dict[str, Any]) -> tuple[Any, ...]:
    thread_id = _user32.GetWindowThreadProcessId(hwnd, None)
    return (thread_id, window["pid"], window["app"], window["className"], window["title"])


def _window_token(hwnd: int, window: dict[str, Any]) -> str:
    identity = json.dumps(_window_identity(hwnd, window), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _capture_window(hwnd: int, window: dict[str, Any]) -> bytes:
    width, height = window["width"], window["height"]
    screen_dc = _user32.GetWindowDC(hwnd)
    if not screen_dc:
        raise WinAppError("Could not open the window display context")
    memory_dc = bitmap = None
    old_bitmap = None
    try:
        memory_dc = _gdi32.CreateCompatibleDC(screen_dc)
        bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not memory_dc or not bitmap:
            raise WinAppError("Could not create the window capture surface")
        old_bitmap = _gdi32.SelectObject(memory_dc, bitmap)
        if not old_bitmap:
            raise WinAppError("Could not select the window capture surface")
        pixels = None
        rendered = False
        if hasattr(_user32, "PrintWindow"):
            for flags in (0, PW_RENDERFULLCONTENT):
                if hasattr(_gdi32, "PatBlt"):
                    _gdi32.PatBlt(memory_dc, 0, 0, width, height, 0x00000042)
                if _user32.PrintWindow(hwnd, memory_dc, flags):
                    try:
                        px = _bitmap_pixels(memory_dc, bitmap, old_bitmap, width, height)
                        if not _black_frame(px):
                            pixels = px
                            rendered = True
                            break
                    except WinAppError:
                        pass
        if not rendered:
            if hasattr(_gdi32, "PatBlt"):
                _gdi32.PatBlt(memory_dc, 0, 0, width, height, 0x00000042)
            rendered = _send_bounded_window_print(hwnd, memory_dc)
            if rendered:
                try:
                    px = _bitmap_pixels(memory_dc, bitmap, old_bitmap, width, height)
                    if not _black_frame(px):
                        pixels = px
                except WinAppError:
                    pass
            if pixels is None:
                if not _window_unoccluded(hwnd, window):
                    raise WinAppError(
                        "The covered window did not respond to capture before the timeout; uncover it and retry",
                        status=504,
                    )
                if not _capture_desktop_fallback(memory_dc, window):
                    raise WinAppError("The window capture timed out and desktop fallback failed", status=504)
                pixels = _bitmap_pixels(memory_dc, bitmap, old_bitmap, width, height)
        if pixels is None:
            raise WinAppError("Could not capture that window; try another application window")
        return pixels
    finally:
        if bitmap:
            if memory_dc and old_bitmap:
                _gdi32.SelectObject(memory_dc, old_bitmap)
            _gdi32.DeleteObject(bitmap)
        if memory_dc:
            _gdi32.DeleteDC(memory_dc)
        _user32.ReleaseDC(hwnd, screen_dc)


def winapps_window_screenshot(window_id: int | str, expected_token: str | None = None) -> bytes:
    """Capture a visible window in physical pixels, retrying PrintWindow with full content and safe fallback."""
    if sys.platform != "win32" or _user32 is None or _gdi32 is None:
        raise WinAppError("Native Windows app mirror needs a Windows host")
    with _physical_dpi_context():
        hwnd, window = _validated_window(window_id)
        identity = _window_identity(hwnd, window)
        if expected_token and _window_token(hwnd, window) != expected_token:
            raise WinAppError("The selected window changed; refresh the mirror",
                              status=409, code="WINDOW_CHANGED")
        pixels = _capture_window(hwnd, window)
        result = _png(window["width"], window["height"], pixels)
        validate_png_frame(result)
        current_hwnd, current_window = _validated_window(hwnd)
        if current_hwnd != hwnd or _window_identity(hwnd, current_window) != identity \
                or (expected_token and _window_token(hwnd, current_window) != expected_token):
            raise WinAppError("The selected window changed during capture; refresh the mirror",
                              status=409, code="WINDOW_CHANGED")
        return result


def winapps_window_stream(
    window_id: int | str,
    fps: float,
    expected_token: str | None = None,
) -> Iterator[bytes]:
    """Yield bounded PNG frames for one still-visible window.

    The first capture happens before the HTTP handler sends stream headers, so a stale
    HWND can still be reported as a normal client error. If it disappears later, the
    stream ends cleanly and the dashboard can fall back to individual captures.
    """
    if sys.platform != "win32" or _user32 is None or _gdi32 is None:
        raise WinAppError("Native Windows app mirror needs a Windows host", status=501)
    if not math.isfinite(fps) or not MIN_STREAM_FPS <= fps <= MAX_STREAM_FPS:
        raise WinAppError(f"Frame rate must be between {MIN_STREAM_FPS:g} and {MAX_STREAM_FPS:g} FPS")
    if not _STREAM_SLOTS.acquire(blocking=False):
        raise WinAppError("The Windows app mirror already has the maximum number of active streams",
                          status=429)
    try:
        hwnd, initial_window = _validated_window(window_id)
        identity = _window_identity(hwnd, initial_window)
        if expected_token and _window_token(hwnd, initial_window) != expected_token:
            raise WinAppError("The selected window changed; refresh the mirror",
                              status=409, code="WINDOW_CHANGED")
        epoch = _WINAPPS_STREAM_EPOCH

        def capture_bound_frame() -> bytes:
            if epoch != _WINAPPS_STREAM_EPOCH:
                raise WinAppError("The Windows app mirror was stopped", status=409, code="STREAM_STOPPED")
            _current_hwnd, before = _validated_window(hwnd)
            if _window_identity(hwnd, before) != identity:
                raise WinAppError("The selected window changed; refresh the mirror")
            frame = winapps_window_screenshot(hwnd)
            _current_hwnd, after = _validated_window(hwnd)
            if _window_identity(hwnd, after) != identity:
                raise WinAppError("The selected window changed; refresh the mirror")
            if epoch != _WINAPPS_STREAM_EPOCH:
                raise WinAppError("The Windows app mirror was stopped", status=409, code="STREAM_STOPPED")
            validate_png_frame(frame)
            return frame

        deadline = time.monotonic() + MAX_STREAM_SECONDS
        try:
            first = capture_bound_frame()
        except WinAppError as exc:
            if exc.code == "STREAM_STOPPED":
                return
            raise
        if epoch != _WINAPPS_STREAM_EPOCH:
            return
        yield first
        interval = 1.0 / fps
        while True:
            if epoch != _WINAPPS_STREAM_EPOCH:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(interval, remaining))
            if epoch != _WINAPPS_STREAM_EPOCH or time.monotonic() >= deadline:
                return
            try:
                frame = capture_bound_frame()
            except WinAppError:
                return
            if epoch != _WINAPPS_STREAM_EPOCH:
                return
            yield frame
    finally:
        _STREAM_SLOTS.release()


_UIA_ELEMENTS: dict[int, dict[str, Any]] = {}
_UIA_ELEMENTS_LOCK = threading.Lock()
_UIA_READ_LOCK = threading.Lock()
_UIA_PENDING_WINDOWS: set[int] = set()
_UIA_WORKER_SLOTS = threading.BoundedSemaphore(MAX_UIA_WORKERS)
_CONTROL_STATE = {"armed": False, "armedAt": 0.0, "owner": None}
_CONTROL_LOCK = threading.Lock()
_WINAPPS_STREAM_EPOCH = 0
_AUDIT_ROWS: list[dict[str, Any]] = []
_AUDIT_LOCK = threading.Lock()
_ACTION_CACHE: dict[tuple[str, str], dict[str, Any]] = {}

_UIA_PROPERTY_NAME = 30005
_UIA_PROPERTY_CONTROL_TYPE = 30003
_UIA_PROPERTY_BOUNDING_RECTANGLE = 30001
_UIA_PROPERTY_RUNTIME_ID = 30000
_UIA_PROPERTY_IS_ENABLED = 30010
_UIA_PROPERTY_HAS_KEYBOARD_FOCUS = 30008
_UIA_PROPERTY_IS_OFFSCREEN = 30022
_UIA_PROPERTY_IS_PASSWORD = 30019
_UIA_CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox",
    50004: "Edit", 50005: "Hyperlink", 50006: "Image", 50007: "ListItem",
    50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar",
    50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab",
    50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip",
    50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group",
    50027: "Thumb", 50028: "DataGrid", 50029: "DataItem", 50030: "Document",
    50031: "SplitButton", 50032: "Window", 50033: "Pane", 50034: "Header",
    50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator",
    50039: "SemanticZoom", 50040: "AppBar",
}

_IUIAUTOMATION_ELEMENT_FROM_HANDLE = 6
# Verified against IUIAutomation in UIAutomationClient.h: RawViewCondition is
# slot 17 and ControlViewCondition is slot 18, including IUnknown's 3 slots.
_IUIAUTOMATION_CONTROL_VIEW_CONDITION = 18
_IUIAUTOMATIONELEMENT_FIND_ALL = 6


def _com_method(interface: ctypes.c_void_p, index: int, result_type, arg_types: list, *args):
    """Call one documented COM vtable method without an external COM package."""
    table = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = table[index]
    if not address:
        raise WinAppError("Windows UI Automation returned an invalid interface", status=503)
    method = _COM_CALL(result_type, ctypes.c_void_p, *arg_types)(address)
    return method(interface, *args)


def _com_release(interface: ctypes.c_void_p | None) -> None:
    if interface:
        _com_method(interface, 2, ctypes.c_uint32, [])


def _uia_variant_value(element: ctypes.c_void_p, property_id: int):
    if _oleaut32 is None:
        raise WinAppError("Windows UI Automation is not available", status=501)
    value = _VARIANT()
    result = _com_method(
        element, 10, ctypes.c_long,
        [ctypes.c_int, ctypes.POINTER(_VARIANT)], property_id, ctypes.byref(value),
    )
    if result < 0:
        raise WinAppError("UI Automation could not read a window element", status=503)
    try:
        if value.vt == 3:
            return int(value.value.lVal)
        if value.vt == 11:
            return value.value.boolVal != 0
        if value.vt == 8:
            pointer = value.value.bstrVal
            length = _oleaut32.SysStringLen(pointer) if pointer else 0
            return ctypes.wstring_at(pointer, length) if pointer and length else ""
        if value.vt == 0x2005:
            array = value.value.parray
            if not array or _oleaut32.SafeArrayGetDim(array) != 1:
                return None
            lower, upper = ctypes.c_long(), ctypes.c_long()
            if _oleaut32.SafeArrayGetLBound(array, 1, ctypes.byref(lower)) < 0 \
                    or _oleaut32.SafeArrayGetUBound(array, 1, ctypes.byref(upper)) < 0 \
                    or upper.value - lower.value != 3:
                return None
            coordinates = []
            for offset in range(4):
                index, coordinate = ctypes.c_long(lower.value + offset), ctypes.c_double()
                if _oleaut32.SafeArrayGetElement(array, ctypes.byref(index), ctypes.byref(coordinate)) < 0:
                    return None
                coordinates.append(coordinate.value)
            return coordinates
        if value.vt == 0x2003:
            array = value.value.parray
            if not array or _oleaut32.SafeArrayGetDim(array) != 1:
                return None
            lower, upper = ctypes.c_long(), ctypes.c_long()
            if _oleaut32.SafeArrayGetLBound(array, 1, ctypes.byref(lower)) < 0 \
                    or _oleaut32.SafeArrayGetUBound(array, 1, ctypes.byref(upper)) < 0 \
                    or not 1 <= upper.value - lower.value + 1 <= 32:
                return None
            values = []
            for offset in range(upper.value - lower.value + 1):
                index, item = ctypes.c_long(lower.value + offset), ctypes.c_int32()
                if _oleaut32.SafeArrayGetElement(array, ctypes.byref(index), ctypes.byref(item)) < 0:
                    return None
                values.append(item.value)
            return values
        return None
    finally:
        _oleaut32.VariantClear(ctypes.byref(value))


def _uia_sort_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(element) for element in elements),
        key=lambda element: (
            element["y"], element["x"], element["h"], element["w"],
            element["role"].casefold(), element["label"].casefold(), element["elementId"],
        ),
    )


def _uia_window_relative_bounds(rectangle: list[float], window: dict[str, Any]) -> dict[str, int] | None:
    """Convert UIA physical screen bounds to the same physical client frame used by capture."""
    if len(rectangle) != 4 or not all(math.isfinite(value) for value in rectangle):
        return None
    left, top, right, bottom = rectangle
    x0 = max(0, math.floor(left - window["x"]))
    y0 = max(0, math.floor(top - window["y"]))
    x1 = min(window["width"], math.ceil(right - window["x"]))
    y1 = min(window["height"], math.ceil(bottom - window["y"]))
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _uia_read_elements(
    hwnd: int,
    window: dict[str, Any],
    *,
    focus_element_id: str | None = None,
    expected_revision: str | None = None,
    expected_bounds: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Read the visible control view for one HWND; password controls are never exposed."""
    if _uia_core is None or _ole32 is None or _oleaut32 is None:
        raise WinAppError("Windows UI Automation is not available on this host", status=501)
    initialized = _ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    if initialized < 0:
        raise WinAppError("UI Automation could not initialize COM on this request thread", status=503)

    automation = root = condition = array = None
    raw_elements: list[tuple[dict[str, Any], tuple[int, ...] | None, ctypes.c_void_p | None]] = []
    try:
        automation = ctypes.c_void_p()
        result = _ole32.CoCreateInstance(
            ctypes.byref(_CLSID_CUIAUTOMATION), None, 1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(_IID_IUIAUTOMATION), ctypes.byref(automation),
        )
        if result < 0 or not automation.value:
            raise WinAppError("Windows UI Automation could not be created", status=501)

        root = ctypes.c_void_p()
        result = _com_method(
            automation, _IUIAUTOMATION_ELEMENT_FROM_HANDLE, ctypes.c_long,
            [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)], hwnd, ctypes.byref(root),
        )  # IUIAutomation::ElementFromHandle
        if result < 0 or not root.value:
            raise WinAppError("UI Automation could not attach to that window; refresh the mirror")

        condition = ctypes.c_void_p()
        result = _com_method(
            automation, _IUIAUTOMATION_CONTROL_VIEW_CONDITION, ctypes.c_long,
            [ctypes.POINTER(ctypes.c_void_p)],
            ctypes.byref(condition),
        )  # IUIAutomation::get_ControlViewCondition
        if result < 0 or not condition.value:
            raise WinAppError("Windows UI Automation could not create a control-view filter", status=503)

        array = ctypes.c_void_p()
        result = _com_method(
            root, _IUIAUTOMATIONELEMENT_FIND_ALL, ctypes.c_long,
            [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            4, condition, ctypes.byref(array),
        )  # IUIAutomationElement::FindAll(TreeScope_Descendants, condition)
        if result < 0 or not array.value:
            raise WinAppError("UI Automation could not enumerate this window's controls", status=503)

        count = ctypes.c_int()
        result = _com_method(array, 3, ctypes.c_long, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(count))
        if result < 0 or count.value < 0:
            raise WinAppError("UI Automation returned an invalid element list", status=503)
        scan_count = min(count.value, MAX_UIA_ELEMENTS * 8)
        trimmed = count.value > scan_count
        for index in range(scan_count):
            item = ctypes.c_void_p()
            result = _com_method(
                array, 4, ctypes.c_long,
                [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(item),
            )
            if result < 0 or not item.value:
                _com_release(item)
                continue
            try:
                if _uia_variant_value(item, _UIA_PROPERTY_IS_OFFSCREEN) is not False:
                    continue
                if _uia_variant_value(item, _UIA_PROPERTY_IS_PASSWORD) is True:
                    continue
                rectangle = _uia_variant_value(item, _UIA_PROPERTY_BOUNDING_RECTANGLE)
                relative_bounds = _uia_window_relative_bounds(rectangle, window) \
                    if isinstance(rectangle, list) else None
                if relative_bounds is None:
                    continue
                control_type = _uia_variant_value(item, _UIA_PROPERTY_CONTROL_TYPE)
                if not isinstance(control_type, int):
                    continue
                role = _UIA_CONTROL_TYPES.get(control_type, "Custom")
                label_value = _uia_variant_value(item, _UIA_PROPERTY_NAME)
                label = (label_value if isinstance(label_value, str) else "")[:120]
                element = {
                    "role": role,
                    "label": label,
                    **relative_bounds,
                    "enabled": _uia_variant_value(item, _UIA_PROPERTY_IS_ENABLED) is True,
                    "focused": _uia_variant_value(item, _UIA_PROPERTY_HAS_KEYBOARD_FOCUS) is True,
                }
                runtime_value = _uia_variant_value(item, _UIA_PROPERTY_RUNTIME_ID)
                runtime_id = tuple(runtime_value) if isinstance(runtime_value, list) \
                    and runtime_value and all(type(value) is int for value in runtime_value) else None
                raw_elements.append((element, runtime_id, item if focus_element_id else None))
                if focus_element_id:
                    item = None
            finally:
                _com_release(item)
        raw_elements.sort(key=lambda pair: (
            pair[0]["y"], pair[0]["x"], pair[0]["h"], pair[0]["w"],
            pair[0]["role"].casefold(), pair[0]["label"].casefold(), pair[1] or (),
        ))
        fallback_occurrences: dict[tuple[Any, ...], int] = {}
        all_elements: list[dict[str, Any]] = []
        interfaces_by_id: dict[str, ctypes.c_void_p | None] = {}
        for element, runtime_id, interface in raw_elements:
            if runtime_id is not None:
                identity = json.dumps(runtime_id, separators=(",", ":"))
            else:
                key = (
                    element["role"], element["label"], element["x"], element["y"],
                    element["w"], element["h"],
                )
                occurrence = fallback_occurrences.get(key, 0)
                fallback_occurrences[key] = occurrence + 1
                identity = json.dumps((*key, occurrence), ensure_ascii=False, separators=(",", ":"))
            element["elementId"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            all_elements.append(element)
            interfaces_by_id[element["elementId"]] = interface
        ordered_elements = _uia_sort_elements(all_elements)
        trimmed = trimmed or len(ordered_elements) > MAX_UIA_ELEMENTS
        elements = ordered_elements[:MAX_UIA_ELEMENTS]
        if focus_element_id:
            target_element = next(
                (element for element in elements if element["elementId"] == focus_element_id), None
            )
            target_interface = interfaces_by_id.get(focus_element_id)
            if target_element is None or target_interface is None:
                raise WinAppError("The previewed UI Automation control is no longer available",
                                  status=409, code="UIA_TARGET_CHANGED")
            if not target_element["enabled"]:
                raise WinAppError("The previewed UI Automation control is disabled",
                                  status=409, code="UIA_TARGET_CHANGED")
            actual_revision = _element_revision(elements)
            if expected_revision and actual_revision != expected_revision:
                raise WinAppError("The UI changed after the action preview; review it again",
                                  status=409, code="UIA_STALE")
            if expected_bounds is not None and any(
                target_element[key] != expected_bounds[value]
                for key, value in (("x", "x"), ("y", "y"), ("w", "w"), ("h", "h"))
            ):
                raise WinAppError("The previewed UI Automation control moved; review it again",
                                  status=409, code="UIA_TARGET_CHANGED")
            result = _com_method(target_interface, 3, ctypes.c_long, [])  # IUIAutomationElement::SetFocus
            if result < 0:
                raise WinAppError("Windows could not focus the previewed UI Automation control",
                                  status=409, code="FOCUS_FAILED")
        return elements, trimmed
    finally:
        for _element, _runtime_id, interface in raw_elements:
            _com_release(interface)
        _com_release(array)
        _com_release(condition)
        _com_release(root)
        _com_release(automation)
        _ole32.CoUninitialize()


def _run_uia_bounded(hwnd: int, operation) -> Any:
    """Run provider calls on a bounded worker and refuse overlapping reads per HWND."""
    with _UIA_READ_LOCK:
        if hwnd in _UIA_PENDING_WINDOWS:
            raise WinAppError("UI Automation is still reading this window; retry shortly",
                              status=429, code="UIA_BUSY")
        if not _UIA_WORKER_SLOTS.acquire(blocking=False):
            raise WinAppError("Windows UI Automation is busy; retry shortly", status=429, code="UIA_BUSY")
        _UIA_PENDING_WINDOWS.add(hwnd)

    completed = threading.Event()
    result: dict[str, Any] = {}

    def read() -> None:
        try:
            try:
                result["value"] = operation()
            except Exception as exc:
                result["error"] = exc
        finally:
            with _UIA_READ_LOCK:
                _UIA_PENDING_WINDOWS.discard(hwnd)
                _UIA_WORKER_SLOTS.release()
            completed.set()

    worker = threading.Thread(target=read, name=f"winapps-uia-{hwnd}", daemon=True)
    try:
        worker.start()
    except RuntimeError:
        with _UIA_READ_LOCK:
            _UIA_PENDING_WINDOWS.discard(hwnd)
            _UIA_WORKER_SLOTS.release()
        raise
    if not completed.wait(UIA_READ_TIMEOUT_SECONDS):
        raise WinAppError("Windows UI Automation did not respond before the timeout",
                          status=504, code="UIA_TIMEOUT")
    if "error" in result:
        raise result["error"]
    return result["value"]


def _uia_read_elements_bounded(
    hwnd: int,
    window: dict[str, Any],
    *,
    focus_element_id: str | None = None,
    expected_revision: str | None = None,
    expected_bounds: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    return _run_uia_bounded(hwnd, lambda: _uia_read_elements(
        hwnd, window, focus_element_id=focus_element_id,
        expected_revision=expected_revision, expected_bounds=expected_bounds,
    ))


def _validate_hwnd(window_id: int | str) -> int:
    if isinstance(window_id, bool):
        raise WinAppError("Invalid window id")
    if isinstance(window_id, int):
        hwnd = window_id
    elif isinstance(window_id, str) and window_id.isascii() and window_id.isdigit():
        hwnd = int(window_id)
    else:
        raise WinAppError("Invalid window id")
    if not 0 < hwnd <= 0xFFFFFFFF:
        raise WinAppError("Invalid window id")
    return hwnd


def _visible_window(window_id: int | str) -> tuple[int, dict[str, Any]]:
    if sys.platform != "win32" or _user32 is None:
        raise WinAppError("Native Windows app control needs a Windows host", status=501)
    hwnd = _validate_hwnd(window_id)
    if _user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
        raise WinAppError("That window is not on screen anymore; refresh the mirror")
    window = _window(hwnd)
    if window is None:
        raise WinAppError("That window is not on screen anymore; refresh the mirror")
    return hwnd, window


def _element_revision(elements: list[dict[str, Any]]) -> str:
    content = json.dumps(elements, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:16]


def _diff_ui_elements(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    unused = {element["elementId"]: element for element in previous}
    added, changed = [], []
    for element in current:
        old = unused.pop(element["elementId"], None)
        if old is None:
            added.append(element)
        elif any(old[key] != element[key] for key in (
            "role", "label", "x", "y", "w", "h", "enabled", "focused"
        )):
            changed.append({**element, "movedFrom": {"x": old["x"], "y": old["y"]}})
    return {"added": added[:MAX_UIA_ELEMENTS], "changed": changed[:MAX_UIA_ELEMENTS],
            "removed": list(unused.values())[:MAX_UIA_ELEMENTS]}


def winapps_window_elements(
    window_id: int | str,
    revision: str | None = None,
    expected_window_token: str | None = None,
) -> dict[str, Any]:
    """Visible UI Automation controls in one validated window and a bounded revision diff."""
    hwnd, window = _visible_window(window_id)
    window_token = _window_token(hwnd, window)
    if expected_window_token and expected_window_token != window_token:
        raise WinAppError("The selected window changed; refresh the mirror",
                          status=409, code="WINDOW_CHANGED")
    if revision is not None and (not isinstance(revision, str) or len(revision) > 64):
        raise WinAppError("revision must be a short UI Automation revision token")
    identity = _window_identity(hwnd, window)
    elements, trimmed = _uia_read_elements_bounded(hwnd, window)
    current_hwnd, current_window = _visible_window(hwnd)
    if current_hwnd != hwnd or _window_identity(hwnd, current_window) != identity \
            or (expected_window_token and _window_token(hwnd, current_window) != expected_window_token):
        raise WinAppError("The selected window changed during UI Automation; refresh the mirror",
                          status=409, code="WINDOW_CHANGED")
    elements = _uia_sort_elements(elements)
    token = _element_revision(elements)
    window_token = _window_token(hwnd, current_window)
    if expected_window_token and window_token != expected_window_token:
        raise WinAppError("The selected window changed; refresh the mirror",
                          status=409, code="WINDOW_CHANGED")
    with _UIA_ELEMENTS_LOCK:
        cached = _UIA_ELEMENTS.get(hwnd)
        diff = _diff_ui_elements(cached["elements"], elements) if (
            revision and cached and cached["windowIdentity"] == identity
            and cached["revision"] == revision and revision != token
        ) else {"added": [], "changed": [], "removed": []}
        _UIA_ELEMENTS[hwnd] = {
            "revision": token, "elements": elements, "windowIdentity": identity, "at": time.monotonic(),
        }
        if len(_UIA_ELEMENTS) > 16:
            oldest = min(_UIA_ELEMENTS, key=lambda key: _UIA_ELEMENTS[key]["at"])
            _UIA_ELEMENTS.pop(oldest, None)
    return {
        "windowId": hwnd,
        "windowToken": window_token,
        "app": window["app"],
        "bounds": {"x": window["x"], "y": window["y"], "width": window["width"], "height": window["height"]},
        "revision": token,
        "engine": "uia",
        "trimmed": trimmed,
        "elements": elements,
        "diff": diff,
    }


def winapps_search_elements(
    window_id: int | str,
    query: str,
    expected_window_token: str | None = None,
) -> dict[str, Any]:
    """Search UIA labels and roles without returning more than fifty matching controls."""
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_UIA_QUERY_CHARS:
        raise WinAppError(f"query must contain 1-{MAX_UIA_QUERY_CHARS} characters")
    hwnd, window = _visible_window(window_id)
    if expected_window_token and _window_token(hwnd, window) != expected_window_token:
        raise WinAppError("The selected window changed; refresh the mirror",
                          status=409, code="WINDOW_CHANGED")
    identity = _window_identity(hwnd, window)
    elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
    current_hwnd, current_window = _visible_window(hwnd)
    if current_hwnd != hwnd or _window_identity(hwnd, current_window) != identity \
            or (expected_window_token and _window_token(hwnd, current_window) != expected_window_token):
        raise WinAppError("The selected window changed during UI Automation; refresh the mirror",
                          status=409, code="WINDOW_CHANGED")
    elements = _uia_sort_elements(elements)
    needle = query.strip().casefold()
    hits = [
        element for element in elements
        if needle in element["label"].casefold() or needle in element["role"].casefold()
    ][:MAX_UIA_SEARCH_RESULTS]
    return {
        "windowId": hwnd,
        "windowToken": _window_token(hwnd, current_window),
        "app": window["app"],
        "revision": _element_revision(elements),
        "engine": "uia",
        "query": query.strip(),
        "count": len(hits),
        "hits": hits,
    }


def _record_audit(kind: str, *, window: dict[str, Any] | None = None,
                  detail: dict[str, Any] | None = None) -> None:
    """Keep a bounded local-only audit ring; never retain user-entered text or window titles."""
    row: dict[str, Any] = {"time": time.time(), "kind": kind}
    if window:
        row.update({"windowId": window.get("windowId"), "app": window.get("app")})
    if detail:
        row.update(detail)
    with _AUDIT_LOCK:
        _AUDIT_ROWS.append(row)
        del _AUDIT_ROWS[:-CONTROL_AUDIT_MAX]


def _audit_summary_locked() -> list[dict[str, Any]]:
    fields = ("time", "kind", "action", "windowId", "app", "x", "y", "deltaX",
              "deltaY", "textLength", "key", "ok")
    return [
        {key: row[key] for key in fields if key in row}
        for row in _AUDIT_ROWS[-CONTROL_AUDIT_DISPLAY_MAX:]
    ]


def _audit_summary() -> list[dict[str, Any]]:
    with _AUDIT_LOCK:
        return _audit_summary_locked()


def _control_active_locked(now: float) -> bool:
    if _CONTROL_STATE["armed"] and now - _CONTROL_STATE["armedAt"] < CONTROL_TIMEOUT_SECONDS:
        return True
    _CONTROL_STATE.update({"armed": False, "armedAt": 0.0, "owner": None})
    return False


def winapps_control_state() -> dict[str, Any]:
    with _CONTROL_LOCK:
        now = time.monotonic()
        armed = _control_active_locked(now)
        expires = max(0, int(CONTROL_TIMEOUT_SECONDS - (now - _CONTROL_STATE["armedAt"]))) if armed else 0
        owner = _CONTROL_STATE["owner"] if armed else None
    with _AUDIT_LOCK:
        audit = [
            {key: row[key] for key in ("time", "kind", "windowId", "app", "ok", "reason") if key in row}
            for row in _AUDIT_ROWS[-10:]
        ]
        recent_actions = _audit_summary_locked()
    return {
        "armed": armed,
        "owner": owner,
        "expiresInSec": expires,
        "audit": audit,
        "recentActions": recent_actions,
    }


def _validated_owner(owner: Any) -> str:
    if not isinstance(owner, str) or not 1 <= len(owner) <= 64 \
            or not all(char.isascii() and (char.isalnum() or char in "-_.:") for char in owner):
        raise WinAppError("owner must be a 1-64 character local control id")
    return owner


def winapps_control_arm(armed: bool, owner: str | None = None) -> dict[str, Any]:
    if not isinstance(armed, bool):
        raise WinAppError("armed must be true or false")
    if armed and (sys.platform != "win32" or _user32 is None):
        raise WinAppError("Native Windows app control needs a Windows host", status=501)
    owner_id = _validated_owner(owner) if owner is not None else None
    if armed and owner_id is None:
        raise WinAppError("owner is required to arm Windows app control")
    with _CONTROL_LOCK:
        now = time.monotonic()
        active = _control_active_locked(now)
        if armed and active and _CONTROL_STATE["owner"] != owner_id:
            raise WinAppError("Another dashboard holds the Windows app control lock", status=409, code="ARMED_BY_OTHER")
        if not armed and active and _CONTROL_STATE["owner"] != owner_id:
            raise WinAppError("Only the control-lock owner can disarm Windows app input",
                              status=409, code="ARMED_BY_OTHER")
        _CONTROL_STATE.update({"armed": armed, "armedAt": now if armed else 0.0, "owner": owner_id})
    _record_audit("arm" if armed else "disarm")
    return winapps_control_state()


def winapps_panic_stop() -> dict[str, Any]:
    """Idempotently disarm input and end all currently open mirror streams."""
    global _WINAPPS_STREAM_EPOCH
    with _CONTROL_LOCK:
        _CONTROL_STATE.update({"armed": False, "armedAt": 0.0, "owner": None})
        _WINAPPS_STREAM_EPOCH += 1
    _record_audit("panic-stop", detail={"streamEpoch": _WINAPPS_STREAM_EPOCH})
    return {"ok": True, "disarmed": True, "streamEpoch": _WINAPPS_STREAM_EPOCH}


def _require_control_locked(owner: Any, confirm: Any) -> str:
    owner_id = _validated_owner(owner)
    if confirm is not True:
        raise WinAppError("Confirm the previewed action before sending input", code="CONFIRM_REQUIRED")
    now = time.monotonic()
    if not _control_active_locked(now):
        raise WinAppError("Control mode is not armed; arm the app mirror first", code="NOT_ARMED")
    if owner_id != _CONTROL_STATE["owner"]:
        raise WinAppError("Another dashboard holds the Windows app control lock", status=409, code="INPUT_BUSY")
    return owner_id


def _uia_focus_window(hwnd: int) -> None:
    if _uia_core is None or _ole32 is None:
        raise WinAppError("Windows UI Automation is not available on this host", status=501)
    initialized = _ole32.CoInitializeEx(None, 0)
    if initialized < 0:
        raise WinAppError("UI Automation could not initialize COM for focus", status=503)
    automation = root = None
    try:
        automation = ctypes.c_void_p()
        result = _ole32.CoCreateInstance(
            ctypes.byref(_CLSID_CUIAUTOMATION), None, 1,
            ctypes.byref(_IID_IUIAUTOMATION), ctypes.byref(automation),
        )
        if result < 0 or not automation.value:
            raise WinAppError("Windows UI Automation could not be created", status=501)
        root = ctypes.c_void_p()
        result = _com_method(
            automation, _IUIAUTOMATION_ELEMENT_FROM_HANDLE, ctypes.c_long,
            [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)], hwnd, ctypes.byref(root),
        )
        if result < 0 or not root.value:
            raise WinAppError("UI Automation could not attach to that window; refresh the mirror")
        result = _com_method(root, 3, ctypes.c_long, [])  # IUIAutomationElement::SetFocus
        if result < 0:
            raise WinAppError("Windows UI Automation could not focus the selected window",
                              status=409, code="FOCUS_FAILED")
    finally:
        _com_release(root)
        _com_release(automation)
        _ole32.CoUninitialize()


def _focus_window(hwnd: int, expected_token: str | None = None) -> None:
    _current, window = _visible_window(hwnd)
    if expected_token and _window_token(hwnd, window) != expected_token:
        raise WinAppError("The selected window changed; review the action again",
                          status=409, code="WINDOW_CHANGED")
    _run_uia_bounded(hwnd, lambda: _uia_focus_window(hwnd))
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        foreground = _user32.GetForegroundWindow()
        if foreground and _user32.GetAncestor(foreground, GA_ROOT) == hwnd:
            return
        time.sleep(0.01)
    raise WinAppError("Windows could not focus the selected window; no input was sent",
                      status=409, code="FOCUS_FAILED")


def _mouse_absolute_position(hwnd: int, x: int, y: int, window: dict[str, Any]) -> tuple[int, int]:
    screen_x, screen_y = window["x"] + x, window["y"] + y
    if not (window["x"] <= screen_x < window["x"] + window["width"]
            and window["y"] <= screen_y < window["y"] + window["height"]):
        raise WinAppError("Mouse coordinates fall outside the selected window")
    with _physical_dpi_context():
        screen_left, screen_top = _user32.GetSystemMetrics(76), _user32.GetSystemMetrics(77)
        screen_width, screen_height = _user32.GetSystemMetrics(78), _user32.GetSystemMetrics(79)
        if screen_width <= 1 or screen_height <= 1:
            raise WinAppError("Windows did not report valid desktop bounds", status=503)
        target = _user32.WindowFromPoint(_POINT(screen_x, screen_y))
        if not target or _user32.GetAncestor(target, GA_ROOT) != hwnd:
            raise WinAppError("The target point is covered by another window; refresh and retry", status=409)
    absolute_x = round((screen_x - screen_left) * 65535 / (screen_width - 1))
    absolute_y = round((screen_y - screen_top) * 65535 / (screen_height - 1))
    return absolute_x, absolute_y


def _send_mouse_gesture(hwnd: int, x: int, y: int, window: dict[str, Any], action: str,
                        delta_x: int = 0, delta_y: int = 0) -> None:
    absolute_x, absolute_y = _mouse_absolute_position(hwnd, x, y, window)
    events: list[_INPUT] = [_INPUT()]
    events[0].type = 0
    events[0].mi = _MOUSEINPUT(
        absolute_x, absolute_y, 0,
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0,
    )
    if action in ("click", "double_click"):
        count = 2 if action == "double_click" else 1
        for _ in range(count):
            for flag in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
                event = _INPUT()
                event.type = 0
                event.mi = _MOUSEINPUT(absolute_x, absolute_y, 0, flag, 0, 0)
                events.append(event)
    elif action == "right_click":
        for flag in (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP):
            event = _INPUT()
            event.type = 0
            event.mi = _MOUSEINPUT(absolute_x, absolute_y, 0, flag, 0, 0)
            events.append(event)
    elif action == "scroll":
        for delta, flag in ((delta_y, MOUSEEVENTF_WHEEL), (delta_x, MOUSEEVENTF_HWHEEL)):
            if not delta:
                continue
            event = _INPUT()
            event.type = 0
            event.mi = _MOUSEINPUT(0, 0, delta & 0xFFFFFFFF, flag, 0, 0)
            events.append(event)
    else:
        raise WinAppError("Unsupported mouse action")
    inputs = (_INPUT * len(events))(*events)
    if _user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT)) != len(inputs):
        raise WinAppError("Windows did not accept the mouse input", status=503)


def _ensure_foreground_target(hwnd: int, expected_token: str) -> dict[str, Any]:
    _current, window = _visible_window(hwnd)
    if _window_token(hwnd, window) != expected_token:
        raise WinAppError("The selected window changed; review the action again",
                          status=409, code="WINDOW_CHANGED")
    foreground = _user32.GetForegroundWindow()
    if not foreground or _user32.GetAncestor(foreground, GA_ROOT) != hwnd:
        raise WinAppError("The selected window lost focus; no input was sent",
                          status=409, code="FOCUS_LOST")
    return window


def _send_mouse_action(
    hwnd: int,
    x: int,
    y: int,
    action: str,
    delta_x: int,
    delta_y: int,
    expected_token: str,
    expected_element: dict[str, Any] | None = None,
) -> None:
    window = _ensure_foreground_target(hwnd, expected_token)
    if expected_element is not None:
        elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
        current = next(
            (element for element in elements if element["elementId"] == expected_element["elementId"]), None
        )
        if current is None or any(current[key] != expected_element[key] for key in (
            "role", "label", "x", "y", "w", "h", "enabled"
        )) or not current["enabled"]:
            raise WinAppError("The previewed UI Automation control changed; review the action again",
                              status=409, code="UIA_TARGET_CHANGED")
    rect_x, rect_y = window["x"] + x, window["y"] + y
    if not (window["x"] <= rect_x < window["x"] + window["width"]
            and window["y"] <= rect_y < window["y"] + window["height"]):
        raise WinAppError("Click coordinates fall outside the selected window")
    with _physical_dpi_context():
        screen_left, screen_top = _user32.GetSystemMetrics(76), _user32.GetSystemMetrics(77)
        screen_width, screen_height = _user32.GetSystemMetrics(78), _user32.GetSystemMetrics(79)
        if screen_width <= 1 or screen_height <= 1:
            raise WinAppError("Windows did not report valid desktop bounds", status=503)
        point = _POINT(rect_x, rect_y)
        target = _user32.WindowFromPoint(point)
        if not target or _user32.GetAncestor(target, GA_ROOT) != hwnd:
            raise WinAppError("The target point is covered by another window; refresh and retry", status=409)
    absolute_x = round((rect_x - screen_left) * 65535 / (screen_width - 1))
    absolute_y = round((rect_y - screen_top) * 65535 / (screen_height - 1))
    events: list[_INPUT] = []
    events.append(_INPUT(type=0, mi=_MOUSEINPUT(
        absolute_x, absolute_y, 0, 0x0001 | 0x8000 | 0x4000, 0, 0
    )))
    if action in ("click", "double_click", "right_click"):
        down, up = (0x0008, 0x0010) if action == "right_click" else (0x0002, 0x0004)
        count = 2 if action == "double_click" else 1
        for _index in range(count):
            events.append(_INPUT(type=0, mi=_MOUSEINPUT(absolute_x, absolute_y, 0, down, 0, 0)))
            events.append(_INPUT(type=0, mi=_MOUSEINPUT(absolute_x, absolute_y, 0, up, 0, 0)))
    elif action == "scroll":
        if delta_y:
            events.append(_INPUT(type=0, mi=_MOUSEINPUT(
                absolute_x, absolute_y, ctypes.c_uint32(delta_y).value, 0x0800, 0, 0
            )))
        if delta_x:
            events.append(_INPUT(type=0, mi=_MOUSEINPUT(
                absolute_x, absolute_y, ctypes.c_uint32(delta_x).value, 0x1000, 0, 0
            )))
    else:
        raise WinAppError("action must be click, double_click, right_click or scroll")
    batch = (_INPUT * len(events))(*events)
    _ensure_foreground_target(hwnd, expected_token)
    with _physical_dpi_context():
        target = _user32.WindowFromPoint(point)
        if not target or _user32.GetAncestor(target, GA_ROOT) != hwnd:
            raise WinAppError("The target point is covered by another window; refresh and retry", status=409)
    sent = _user32.SendInput(len(events), batch, ctypes.sizeof(_INPUT))
    if sent != len(events):
        release: list[_INPUT] = []
        release_flags = {0x0002: 0x0004, 0x0008: 0x0010}
        for index in range(min(sent, len(events))):
            flags = events[index].mi.dwFlags
            if flags in release_flags:
                release.append(_INPUT(type=0, mi=_MOUSEINPUT(
                    absolute_x, absolute_y, 0, release_flags[flags], 0, 0
                )))
        if release:
            release_batch = (_INPUT * len(release))(*release)
            _user32.SendInput(len(release), release_batch, ctypes.sizeof(_INPUT))
        raise WinAppError("Windows accepted only part of the mouse input; held buttons were released",
                          status=503, code="INPUT_PARTIAL")


def _send_mouse_click(hwnd: int, x: int, y: int, window: dict[str, Any],
                      expected_token: str | None = None) -> None:
    token = expected_token or _window_token(hwnd, window)
    _send_mouse_action(hwnd, x, y, "click", 0, 0, token)


def _send_keyboard_input(
    hwnd: int,
    kind: str,
    text: str | None = None,
    key: str | None = None,
    expected_token: str | None = None,
    expected_element: dict[str, Any] | None = None,
) -> None:
    if kind == "key":
        vk = INPUT_KEYS[key]
        events = (_INPUT * 2)()
        events[0].type = 1
        events[0].ki = _KEYBDINPUT(vk, 0, 0, 0, 0)
        events[1].type = 1
        events[1].ki = _KEYBDINPUT(vk, 0, 0x0002, 0, 0)  # KEYEVENTF_KEYUP
    else:
        code_units = text.encode("utf-16-le")
        events = (_INPUT * (len(code_units) // 2 * 2))()
        for index in range(0, len(code_units), 2):
            code_unit = int.from_bytes(code_units[index:index + 2], "little")
            event_index = index
            events[event_index].type = 1
            events[event_index].ki = _KEYBDINPUT(0, code_unit, 0x0004, 0, 0)  # KEYEVENTF_UNICODE
            events[event_index + 1].type = 1
            events[event_index + 1].ki = _KEYBDINPUT(0, code_unit, 0x0004 | 0x0002, 0, 0)
    token = expected_token
    if token is None:
        _current, window = _visible_window(hwnd)
        token = _window_token(hwnd, window)
    if expected_element is not None:
        _current, window = _visible_window(hwnd)
        elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
        current = next(
            (element for element in elements if element["elementId"] == expected_element["elementId"]), None
        )
        if current is None or any(current[key] != expected_element[key] for key in (
            "role", "label", "x", "y", "w", "h", "enabled"
        )) or not current["enabled"] or not current["focused"]:
            raise WinAppError("The previewed UI Automation control no longer has focus",
                              status=409, code="FOCUS_LOST")
    _ensure_foreground_target(hwnd, token)
    sent = _user32.SendInput(len(events), events, ctypes.sizeof(_INPUT))
    if sent != len(events):
        if sent % 2:
            held = events[sent - 1]
            release = (_INPUT * 1)()
            release[0] = held
            release[0].ki.dwFlags |= 0x0002
            _user32.SendInput(1, release, ctypes.sizeof(_INPUT))
        raise WinAppError("Windows accepted only part of the keyboard input; held keys were released",
                          status=503, code="INPUT_PARTIAL")


def _validated_action_binding(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise WinAppError("Action data must be a JSON object")
    if data.get("confirm") is not True:
        raise WinAppError("Confirm the previewed action before sending input", code="CONFIRM_REQUIRED")
    values: dict[str, Any] = {"owner": _validated_owner(data.get("owner"))}
    action_id = data.get("actionId")
    if not isinstance(action_id, str) or not 1 <= len(action_id) <= 64 \
            or not all(char.isascii() and (char.isalnum() or char in "-_.:") for char in action_id):
        raise WinAppError("actionId must be a 1-64 character idempotency key")
    values["actionId"] = action_id
    window_id = data.get("windowId")
    if type(window_id) is not int or not 0 < window_id <= 0xFFFFFFFF:
        raise WinAppError("windowId must be a valid integer window handle")
    values["windowId"] = window_id
    window_token = data.get("windowToken")
    if not isinstance(window_token, str) or len(window_token) != 24 \
            or any(char not in "0123456789abcdef" for char in window_token):
        raise WinAppError("windowToken must be a current window identity token")
    values["windowToken"] = window_token
    revision = data.get("revision")
    if not isinstance(revision, str) or len(revision) != 16 \
            or any(char not in "0123456789abcdef" for char in revision):
        raise WinAppError("revision must be a current UI Automation revision")
    values["revision"] = revision
    element_id = data.get("elementId")
    if not isinstance(element_id, str) or not 1 <= len(element_id) <= 64 \
            or not all(char.isascii() and (char.isalnum() or char in "-_.:") for char in element_id):
        raise WinAppError("elementId must identify a visible UI Automation control")
    values["elementId"] = element_id
    bounds = data.get("elementBounds")
    if not isinstance(bounds, dict) or set(bounds) != {"x", "y", "w", "h"} \
            or any(type(bounds[key]) is not int for key in ("x", "y", "w", "h")) \
            or bounds["x"] < 0 or bounds["y"] < 0 or bounds["w"] <= 0 or bounds["h"] <= 0:
        raise WinAppError("elementBounds must contain positive window-relative UI Automation bounds")
    values["elementBounds"] = dict(bounds)
    return values


def _validated_click(data: dict[str, Any]) -> dict[str, Any]:
    values = _validated_action_binding(data)
    for key in ("x", "y"):
        value = data.get(key)
        if type(value) is not int:
            raise WinAppError(f"{key} must be an integer")
        values[key] = value
    action = data.get("action", "click")
    if not isinstance(action, str) or action not in ("click", "double_click", "right_click", "scroll"):
        raise WinAppError("action must be click, double_click, right_click or scroll")
    values["action"] = action
    for key in ("deltaX", "deltaY"):
        value = data.get(key, 0)
        if type(value) is not int or not -1200 <= value <= 1200:
            raise WinAppError(f"{key} must be an integer between -1200 and 1200")
        values[key] = value
    if action != "scroll" and (values["deltaX"] or values["deltaY"]):
        raise WinAppError("Scroll deltas are only valid for a scroll action")
    if action == "scroll" and not (values["deltaX"] or values["deltaY"]):
        raise WinAppError("A scroll action needs a non-zero delta")
    if values["x"] != round(values["elementBounds"]["x"] + values["elementBounds"]["w"] / 2) \
            or values["y"] != round(values["elementBounds"]["y"] + values["elementBounds"]["h"] / 2):
        raise WinAppError("Click coordinates must be the center of the previewed UI Automation control")
    return values


def _validated_input(data: dict[str, Any]) -> dict[str, Any]:
    values = _validated_action_binding(data)
    kind = data.get("kind")
    if not isinstance(kind, str):
        raise WinAppError("kind must be type, key, double_click, right_click, or scroll")
    if kind in ("double", "right"):
        kind = {"double": "double_click", "right": "right_click"}[kind]
    values["kind"] = kind

    if values["kind"] in INPUT_MOUSE_KINDS:
        for k in ("x", "y"):
            value = data.get(k)
            if type(value) is not int:
                raise WinAppError(f"{k} must be an integer")
            values[k] = value
        bounds = values["elementBounds"]
        if not (bounds["x"] <= values["x"] < bounds["x"] + bounds["w"]
                and bounds["y"] <= values["y"] < bounds["y"] + bounds["h"]):
            raise WinAppError("Mouse coordinates must fall inside the previewed UI Automation control")
        if values["kind"] == "scroll":
            for k in ("deltaX", "deltaY"):
                value = data.get(k)
                if type(value) is not int or abs(value) > MAX_SCROLL_DELTA:
                    raise WinAppError(f"{k} must be an integer between {-MAX_SCROLL_DELTA} and {MAX_SCROLL_DELTA}")
                values[k] = value
            if not values["deltaX"] and not values["deltaY"]:
                raise WinAppError("scroll requires a non-zero deltaX or deltaY")
    elif values["kind"] == "type":
        text = data.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_INPUT_TEXT_CHARS \
                or not all(char.isprintable() and unicodedata.category(char) not in ("Cc", "Cf", "Cs")
                           for char in text):
            raise WinAppError(f"text must contain 1-{MAX_INPUT_TEXT_CHARS} printable characters")
        values["text"] = text
    elif values["kind"] == "key":
        key = data.get("key")
        if not isinstance(key, str) or key not in INPUT_KEYS:
            raise WinAppError("key must be one of: " + ", ".join(INPUT_KEYS))
        values["key"] = key
    else:
        raise WinAppError("kind must be type, key, double_click, right_click, or scroll")
    return values


def _action_fingerprint(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_action_locked(values: dict[str, Any]) -> tuple[tuple[str, str], str, dict[str, Any] | None]:
    key = (values["owner"], values["actionId"])
    fingerprint = _action_fingerprint(values)
    cached = _ACTION_CACHE.get(key)
    if cached is None:
        return key, fingerprint, None
    if cached["fingerprint"] != fingerprint:
        raise WinAppError("actionId was already used for a different action",
                          status=409, code="ACTION_ID_REUSED")
    if cached["state"] == "pending":
        raise WinAppError("This action is already being processed", status=409, code="ACTION_PENDING")
    if cached["state"] == "error":
        raise WinAppError(cached["message"], status=cached["status"], code=cached["code"])
    if cached["state"] == "unknown":
        raise WinAppError("The previous action outcome is uncertain; do not retry it",
                          status=409, code="ACTION_OUTCOME_UNKNOWN")
    return key, fingerprint, dict(cached["result"])


def _store_action_locked(key: tuple[str, str], entry: dict[str, Any]) -> None:
    _ACTION_CACHE[key] = entry
    while len(_ACTION_CACHE) > MAX_ACTION_CACHE:
        _ACTION_CACHE.pop(next(iter(_ACTION_CACHE)))


def _validated_action_snapshot(
    hwnd: int,
    window: dict[str, Any],
    values: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    identity = _window_identity(hwnd, window)
    if _window_token(hwnd, window) != values["windowToken"]:
        raise WinAppError("The selected window changed; review the action again",
                          status=409, code="WINDOW_CHANGED")
    elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
    current_hwnd, current_window = _visible_window(hwnd)
    if current_hwnd != hwnd or _window_identity(hwnd, current_window) != identity \
            or _window_token(hwnd, current_window) != values["windowToken"]:
        raise WinAppError("The selected window changed during validation; review the action again",
                          status=409, code="WINDOW_CHANGED")
    elements = _uia_sort_elements(elements)
    if _element_revision(elements) != values["revision"]:
        raise WinAppError("The UI changed after the action preview; review it again",
                          status=409, code="UIA_STALE")
    element = next(
        (candidate for candidate in elements if candidate["elementId"] == values["elementId"]), None
    )
    expected_bounds = values["elementBounds"]
    if element is None or any(
        element[key] != expected_bounds[key] for key in ("x", "y", "w", "h")
    ):
        raise WinAppError("The previewed UI Automation control moved or disappeared",
                          status=409, code="UIA_TARGET_CHANGED")
    if not element["enabled"]:
        raise WinAppError("The previewed UI Automation control is disabled",
                          status=409, code="UIA_TARGET_CHANGED")
    return current_window, elements, element


def _same_ui_except_focus(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> bool:
    def normalized(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in element.items() if key != "focused"}
            for element in _uia_sort_elements(elements)
        ]
    return normalized(first) == normalized(second)


def winapps_control_click(data: dict[str, Any]) -> dict[str, Any]:
    window = None
    values: dict[str, Any] = {}
    try:
        values = _validated_click(data)
        with _CONTROL_LOCK:
            key, fingerprint, replay = _cached_action_locked(values)
            if replay is not None:
                return replay
            _require_control_locked(values["owner"], data.get("confirm"))
            hwnd, window = _visible_window(values["windowId"])
            if not 0 <= values["x"] < window["width"] or not 0 <= values["y"] < window["height"]:
                raise WinAppError("Click coordinates are outside the selected window")
            window, elements, element = _validated_action_snapshot(hwnd, window, values)
            _focus_window(hwnd, values["windowToken"])
            hwnd, window = _visible_window(hwnd)
            if _window_token(hwnd, window) != values["windowToken"]:
                raise WinAppError("The selected window changed; review the action again",
                                  status=409, code="WINDOW_CHANGED")
            current_elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
            if not _same_ui_except_focus(elements, current_elements):
                raise WinAppError("The UI changed while focusing the selected window; review it again",
                                  status=409, code="UIA_STALE")
            current_element = next(
                (candidate for candidate in current_elements
                 if candidate["elementId"] == values["elementId"]), None
            )
            if current_element is None or any(
                current_element[field] != element[field]
                for field in ("role", "label", "x", "y", "w", "h", "enabled")
            ) or not current_element["enabled"]:
                raise WinAppError("The previewed UI Automation control changed; review it again",
                                  status=409, code="UIA_TARGET_CHANGED")
            _require_control_locked(values["owner"], data.get("confirm"))
            _store_action_locked(key, {"fingerprint": fingerprint, "state": "pending"})
            try:
                _send_mouse_action(
                    hwnd, values["x"], values["y"], values["action"],
                    values["deltaX"], values["deltaY"], values["windowToken"], element,
                )
            except WinAppError as exc:
                _store_action_locked(key, {
                    "fingerprint": fingerprint, "state": "error",
                    "message": str(exc), "status": exc.status, "code": exc.code,
                })
                raise
            finally:
                if _ACTION_CACHE.get(key, {}).get("state") == "pending":
                    _store_action_locked(key, {
                        "fingerprint": fingerprint, "state": "unknown",
                    })
            _CONTROL_STATE["armedAt"] = time.monotonic()
            result = {
                "ok": True, "actionSent": True, "windowId": hwnd, "x": values["x"],
                "y": values["y"], "action": values["action"], "actionId": values["actionId"],
            }
            _store_action_locked(key, {
                "fingerprint": fingerprint, "state": "done", "result": result,
            })
        _record_audit("click", window=window, detail={
            "action": values.get("action", "click"),
            "x": values["x"],
            "y": values["y"],
            "actionId": values.get("actionId"),
            "deltaX": values.get("deltaX"),
            "deltaY": values.get("deltaY"),
            "ok": True,
        })
        return result
    except WinAppError as exc:
        _record_audit("click", window=window, detail={
            "action": values.get("action", "click"),
            "x": values.get("x"),
            "y": values.get("y"),
            "actionId": values.get("actionId"),
            "deltaX": values.get("deltaX"),
            "deltaY": values.get("deltaY"),
            "ok": False,
            "reason": str(exc)[:120],
        })
        raise


def winapps_control_input(data: dict[str, Any]) -> dict[str, Any]:
    window = None
    values: dict[str, Any] = {}
    try:
        values = _validated_input(data)
        with _CONTROL_LOCK:
            key, fingerprint, replay = _cached_action_locked(values)
            if replay is not None:
                return replay
            _require_control_locked(values["owner"], data.get("confirm"))
            hwnd, window = _visible_window(values["windowId"])
            window, elements, element = _validated_action_snapshot(hwnd, window, values)
            is_mouse = values["kind"] in INPUT_MOUSE_KINDS
            if is_mouse:
                if not 0 <= values["x"] < window["width"] or not 0 <= values["y"] < window["height"]:
                    raise WinAppError("Mouse coordinates are outside the selected window")
                _focus_window(hwnd, values["windowToken"])
            else:
                _uia_read_elements_bounded(
                    hwnd, window, focus_element_id=values["elementId"],
                    expected_revision=values["revision"], expected_bounds=values["elementBounds"],
                )
            hwnd, window = _visible_window(hwnd)
            if _window_token(hwnd, window) != values["windowToken"]:
                raise WinAppError("The selected window changed; review the action again",
                                  status=409, code="WINDOW_CHANGED")
            current_elements, _trimmed = _uia_read_elements_bounded(hwnd, window)
            if is_mouse and not _same_ui_except_focus(elements, current_elements):
                raise WinAppError("The UI changed while focusing the selected window; review it again",
                                  status=409, code="UIA_STALE")
            current_element = next(
                (candidate for candidate in current_elements
                 if candidate["elementId"] == values["elementId"]), None
            )
            if current_element is None or any(
                current_element[field] != element[field]
                for field in ("role", "label", "x", "y", "w", "h", "enabled")
            ) or not current_element["enabled"]:
                raise WinAppError("The previewed UI Automation control changed; review it again",
                                  status=409, code="UIA_TARGET_CHANGED")
            if not is_mouse and not current_element["focused"]:
                raise WinAppError("Windows could not focus the previewed UI Automation control",
                                  status=409, code="FOCUS_FAILED")
            _require_control_locked(values["owner"], data.get("confirm"))
            _store_action_locked(key, {"fingerprint": fingerprint, "state": "pending"})
            try:
                if is_mouse:
                    _send_mouse_action(
                        hwnd, values["x"], values["y"], values["kind"],
                        values.get("deltaX", 0), values.get("deltaY", 0),
                        values["windowToken"], current_element,
                    )
                else:
                    _send_keyboard_input(
                        hwnd, values["kind"], values.get("text"), values.get("key"),
                        values["windowToken"], current_element,
                    )
            except WinAppError as exc:
                _store_action_locked(key, {
                    "fingerprint": fingerprint, "state": "error",
                    "message": str(exc), "status": exc.status, "code": exc.code,
                })
                raise
            finally:
                if _ACTION_CACHE.get(key, {}).get("state") == "pending":
                    _store_action_locked(key, {
                        "fingerprint": fingerprint, "state": "unknown",
                    })
            _CONTROL_STATE["armedAt"] = time.monotonic()
            detail = {
                "kind": values["kind"],
                "action": values["kind"],
                "ok": True,
                "textLength": len(values.get("text", "")),
                "key": values.get("key"),
                "x": values.get("x"),
                "y": values.get("y"),
                "deltaX": values.get("deltaX"),
                "deltaY": values.get("deltaY"),
                "actionId": values["actionId"],
            }
            result = {"ok": True, "actionSent": True, "windowId": hwnd, **detail}
            _store_action_locked(key, {
                "fingerprint": fingerprint, "state": "done", "result": result,
            })
        _record_audit("input", window=window, detail=detail)
        return result
    except WinAppError as exc:
        _record_audit("input", window=window, detail={
            "kind": values.get("kind"), "textLength": len(values.get("text", "")),
            "action": values.get("kind"),
            "key": values.get("key"),
            "x": values.get("x"),
            "y": values.get("y"),
            "deltaX": values.get("deltaX"),
            "deltaY": values.get("deltaY"),
            "actionId": values.get("actionId"),
            "ok": False, "reason": str(exc)[:120],
        })
        raise


def doctor(can_probe: Callable[[dict[str, Any]], bool] | None = None,
           capture: Callable[[int], bytes] | None = None) -> dict[str, Any]:
    """Desktop session, this console's elevation and one live capture probe.

    `elevated` is None when Windows would not report this process's own token. A standard-user
    console cannot capture elevated windows, so the state is reported instead of hidden.
    """
    checked_at = int(time.time())
    if sys.platform != "win32" or _user32 is None or _kernel32 is None:
        return {"available": False, "desktop": False, "sessionId": None, "elevated": None,
                "capture": False, "windows": 0, "checkedAt": checked_at,
                "reason": "Native Windows app mirror needs a Windows host"}
    session = wintypes.DWORD()
    _kernel32.ProcessIdToSessionId(_kernel32.GetCurrentProcessId(), ctypes.byref(session))
    # Session 0 and service contexts have no interactive desktop shell to mirror.
    desktop = session.value != 0 and bool(_user32.GetShellWindow())
    result: dict[str, Any] = {
        "available": False, "desktop": desktop, "sessionId": int(session.value),
        "elevated": _token_elevated(_kernel32.GetCurrentProcess()),
        "capture": False, "windows": 0, "checkedAt": checked_at, "reason": None,
    }
    if not desktop:
        result["reason"] = "No interactive desktop session is available to this console"
        return result
    try:
        windows = _win_windows()
    except WinAppError as exc:
        result["reason"] = str(exc)
        return result
    result["windows"] = len(windows)
    result["available"] = bool(windows)
    reason: str | None = None
    # The caller may exclude windows that must never be captured, even for a probe.
    candidates = [window for window in windows if can_probe is None or can_probe(window)]
    for window in candidates[:8]:
        try:
            grab = capture or winapps_window_screenshot  # the caller may supply a policy-checked capture
            result["capture"] = grab(window["windowId"]).startswith(b"\x89PNG")
            break
        except WinAppError as exc:
            reason = str(exc)
    if not result["capture"]:
        result["reason"] = reason or "No on-screen window to probe"
    return result


def main(argv: list[str] | None = None) -> int:
    """Print the JSON inventory (or `--doctor` probe); useful for a quick native check."""
    import json
    if "--doctor" in (sys.argv[1:] if argv is None else argv):
        result = doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["available"] and result["capture"] else 1
    result = winapps_windows()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
