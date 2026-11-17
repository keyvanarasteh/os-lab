"""Native Windows app mirror with guarded UI Automation observation and input.

The macOS Lab uses CoreGraphics through ctypes; this is the Windows counterpart.
It deliberately stays standard-library ctypes only and needs no elevated process.
Input is disabled until a single-owner, expiring arm lock is explicitly enabled.
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
from ctypes import wintypes
from pathlib import Path
from typing import Any, Iterator

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
MIN_STREAM_FPS = 0.5
MAX_STREAM_FPS = 8.0
DEFAULT_STREAM_FPS = 1.2
MAX_STREAM_SECONDS = 600
MAX_UIA_ELEMENTS = 150
MAX_UIA_SEARCH_RESULTS = 50
MAX_UIA_QUERY_CHARS = 120
CONTROL_TIMEOUT_SECONDS = 600
CONTROL_AUDIT_MAX = 200
MAX_INPUT_TEXT_CHARS = 200
INPUT_KEYS = {
    "tab": 0x09,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "space": 0x20,
    "enter": 0x0D,
}
TOOL_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "ThumbnailDeviceHelperWnd",
    "PseudoConsoleWindow",
}


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
    _user32.GetWindowDC.argtypes = [wintypes.HWND]
    _user32.GetWindowDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _user32.PrintWindow.restype = wintypes.BOOL
    if hasattr(_user32, "SetProcessDpiAwarenessContext"):  # Windows 10 1703+; older hosts use Shcore
        _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL

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
    rect = _RECT()
    if not _user32.GetWindowRect(hwnd, rect):
        return None
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
    """The panel's read-only window inventory."""
    if sys.platform != "win32":
        return unavailable("Native Windows app mirror needs a Windows host")
    try:
        windows = _win_windows()
    except WinAppError as exc:
        return unavailable(str(exc))
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


def winapps_window_screenshot(window_id: int) -> bytes:
    """A PNG of one on-screen window. Raises WinAppError when the id is stale or capture fails."""
    if sys.platform != "win32" or _user32 is None or _gdi32 is None:
        raise WinAppError("Native Windows app mirror needs a Windows host")
    try:
        hwnd = int(window_id)
    except (TypeError, ValueError):
        raise WinAppError("Invalid window id") from None
    # An HWND carries 32 significant bits. Anything outside that range cannot be a window, and
    # handing it to ctypes would raise (an HTTP 500) instead of failing cleanly.
    if not 0 < hwnd <= 0xFFFFFFFF:
        raise WinAppError("Invalid window id")
    # Re-check just this window (same filters as the inventory) instead of enumerating every
    # window and opening every process again for each screenshot.
    window = _window(hwnd) if _user32.GetAncestor(hwnd, GA_ROOT) == hwnd else None
    if window is None:
        raise WinAppError("That window is not on screen anymore; refresh the mirror")
    width, height = window["width"], window["height"]
    if width * height > MAX_CAPTURE_PIXELS:
        raise WinAppError("That window is too large to capture")

    screen_dc = _user32.GetWindowDC(hwnd)
    if not screen_dc:
        raise WinAppError("Could not open the window display context")
    memory_dc = bitmap = None
    try:
        memory_dc = _gdi32.CreateCompatibleDC(screen_dc)
        bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not memory_dc or not bitmap:
            raise WinAppError("Could not create the window capture surface")
        old_bitmap = _gdi32.SelectObject(memory_dc, bitmap)
        captured = _user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        # GetDIBits requires that the bitmap is not selected into a DC while it reads it.
        _gdi32.SelectObject(memory_dc, old_bitmap)
        bitmap_info = _BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height  # negative: top-down rows
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = 0
        bitmap_info.bmiHeader.biSizeImage = width * height * 4
        pixels = (ctypes.c_ubyte * (width * height * 4))()
        rows = _gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(bitmap_info), 0)
    finally:
        if bitmap:
            _gdi32.DeleteObject(bitmap)
        if memory_dc:
            _gdi32.DeleteDC(memory_dc)
        _user32.ReleaseDC(hwnd, screen_dc)
    if not captured or rows != height:
        raise WinAppError("Could not capture that window; try another application window")
    return _png(width, height, bytes(pixels))


def winapps_window_stream(window_id: int | str, fps: float) -> Iterator[bytes]:
    """Yield bounded PNG frames for one still-visible window.

    The first capture happens before the HTTP handler sends stream headers, so a stale
    HWND can still be reported as a normal client error. If it disappears later, the
    stream ends cleanly and the dashboard can fall back to individual captures.
    """
    if not math.isfinite(fps) or not MIN_STREAM_FPS <= fps <= MAX_STREAM_FPS:
        raise WinAppError(f"Frame rate must be between {MIN_STREAM_FPS:g} and {MAX_STREAM_FPS:g} FPS")

    deadline = time.monotonic() + MAX_STREAM_SECONDS
    epoch = _WINAPPS_STREAM_EPOCH
    yield winapps_window_screenshot(window_id)
    interval = 1.0 / fps
    while True:
        if epoch != _WINAPPS_STREAM_EPOCH:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(interval, remaining))
        if time.monotonic() >= deadline:
            return
        try:
            yield winapps_window_screenshot(window_id)
        except WinAppError:
            return


_UIA_ELEMENTS: dict[int, dict[str, Any]] = {}
_UIA_ELEMENTS_LOCK = threading.Lock()
_CONTROL_STATE = {"armed": False, "armedAt": 0.0, "owner": None}
_CONTROL_LOCK = threading.Lock()
_WINAPPS_STREAM_EPOCH = 0
_AUDIT_ROWS: list[dict[str, Any]] = []
_AUDIT_LOCK = threading.Lock()

_UIA_PROPERTY_NAME = 30005
_UIA_PROPERTY_CONTROL_TYPE = 30003
_UIA_PROPERTY_BOUNDING_RECTANGLE = 30001
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
        return None
    finally:
        _oleaut32.VariantClear(ctypes.byref(value))


def _uia_read_elements(hwnd: int, window: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Read the visible control view for one HWND; password controls are never exposed."""
    if _uia_core is None or _ole32 is None or _oleaut32 is None:
        raise WinAppError("Windows UI Automation is not available on this host", status=501)
    initialized = _ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    if initialized < 0:
        raise WinAppError("UI Automation could not initialize COM on this request thread", status=503)

    automation = root = condition = array = None
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
            automation, 6, ctypes.c_long,
            [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)], hwnd, ctypes.byref(root),
        )  # IUIAutomation::ElementFromHandle
        if result < 0 or not root.value:
            raise WinAppError("UI Automation could not attach to that window; refresh the mirror")

        condition = ctypes.c_void_p()
        result = _com_method(
            automation, 18, ctypes.c_long, [ctypes.POINTER(ctypes.c_void_p)],
            ctypes.byref(condition),
        )  # IUIAutomation::get_ControlViewCondition
        if result < 0 or not condition.value:
            raise WinAppError("Windows UI Automation could not create a control-view filter", status=503)

        array = ctypes.c_void_p()
        result = _com_method(
            root, 6, ctypes.c_long,
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
        elements: list[dict[str, Any]] = []
        duplicate_counts: dict[tuple[str, str], int] = {}
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
                if not rectangle or len(rectangle) != 4 or not all(math.isfinite(v) for v in rectangle):
                    continue
                left, top, width, height = rectangle
                x0 = max(0, math.floor(left - window["x"]))
                y0 = max(0, math.floor(top - window["y"]))
                x1 = min(window["width"], math.ceil(left + width - window["x"]))
                y1 = min(window["height"], math.ceil(top + height - window["y"]))
                if x1 <= x0 or y1 <= y0:
                    continue
                control_type = _uia_variant_value(item, _UIA_PROPERTY_CONTROL_TYPE)
                if not isinstance(control_type, int):
                    continue
                role = _UIA_CONTROL_TYPES.get(control_type, "Custom")
                label_value = _uia_variant_value(item, _UIA_PROPERTY_NAME)
                label = (label_value if isinstance(label_value, str) else "")[:120]
                identity = (role, label)
                occurrence = duplicate_counts.get(identity, 0)
                duplicate_counts[identity] = occurrence + 1
                element = {
                    "elementId": hashlib.sha256(
                        f"{role}\0{label}\0{occurrence}".encode("utf-8")
                    ).hexdigest()[:16],
                    "role": role,
                    "label": label,
                    "x": x0,
                    "y": y0,
                    "w": x1 - x0,
                    "h": y1 - y0,
                    "enabled": _uia_variant_value(item, _UIA_PROPERTY_IS_ENABLED) is True,
                    "focused": _uia_variant_value(item, _UIA_PROPERTY_HAS_KEYBOARD_FOCUS) is True,
                }
                elements.append(element)
                if len(elements) >= MAX_UIA_ELEMENTS:
                    trimmed = trimmed or index + 1 < count.value
                    break
            finally:
                _com_release(item)
        return elements, trimmed
    finally:
        _com_release(array)
        _com_release(condition)
        _com_release(root)
        _com_release(automation)
        _ole32.CoUninitialize()


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
        elif any(old[key] != element[key] for key in ("role", "label", "x", "y", "w", "h")):
            changed.append({**element, "movedFrom": {"x": old["x"], "y": old["y"]}})
    return {"added": added[:MAX_UIA_ELEMENTS], "changed": changed[:MAX_UIA_ELEMENTS],
            "removed": list(unused.values())[:MAX_UIA_ELEMENTS]}


def winapps_window_elements(window_id: int | str, revision: str | None = None) -> dict[str, Any]:
    """Visible UI Automation controls in one validated window and a bounded revision diff."""
    hwnd, window = _visible_window(window_id)
    if revision is not None and (not isinstance(revision, str) or len(revision) > 64):
        raise WinAppError("revision must be a short UI Automation revision token")
    elements, trimmed = _uia_read_elements(hwnd, window)
    token = _element_revision(elements)
    identity = (window["pid"], window["app"], window["className"], window["title"])
    with _UIA_ELEMENTS_LOCK:
        cached = _UIA_ELEMENTS.get(hwnd)
        diff = _diff_ui_elements(cached["elements"], elements) if (
            revision and cached and cached["identity"] == identity
            and cached["revision"] == revision and revision != token
        ) else {"added": [], "changed": [], "removed": []}
        _UIA_ELEMENTS[hwnd] = {
            "revision": token, "elements": elements, "identity": identity, "at": time.monotonic(),
        }
        if len(_UIA_ELEMENTS) > 16:
            oldest = min(_UIA_ELEMENTS, key=lambda key: _UIA_ELEMENTS[key]["at"])
            _UIA_ELEMENTS.pop(oldest, None)
    return {
        "windowId": hwnd,
        "app": window["app"],
        "bounds": {"x": window["x"], "y": window["y"], "width": window["width"], "height": window["height"]},
        "revision": token,
        "engine": "uia",
        "trimmed": trimmed,
        "elements": elements,
        "diff": diff,
    }


def winapps_search_elements(window_id: int | str, query: str) -> dict[str, Any]:
    """Search UIA labels and roles without returning more than fifty matching controls."""
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_UIA_QUERY_CHARS:
        raise WinAppError(f"query must contain 1-{MAX_UIA_QUERY_CHARS} characters")
    hwnd, window = _visible_window(window_id)
    elements, _trimmed = _uia_read_elements(hwnd, window)
    needle = query.strip().casefold()
    hits = [
        element for element in elements
        if needle in element["label"].casefold() or needle in element["role"].casefold()
    ][:MAX_UIA_SEARCH_RESULTS]
    return {
        "windowId": hwnd,
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
    return {"armed": armed, "owner": owner, "expiresInSec": expires}


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
    owner_id = _validated_owner(owner) if armed else None
    with _CONTROL_LOCK:
        now = time.monotonic()
        active = _control_active_locked(now)
        if armed and active and _CONTROL_STATE["owner"] != owner_id:
            raise WinAppError("Another dashboard holds the Windows app control lock", status=409, code="ARMED_BY_OTHER")
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


def _focus_window(hwnd: int) -> None:
    _user32.BringWindowToTop(hwnd)
    _user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        foreground = _user32.GetForegroundWindow()
        if foreground and _user32.GetAncestor(foreground, GA_ROOT) == hwnd:
            return
        time.sleep(0.01)
    raise WinAppError("Windows did not focus the selected window; activate it manually and retry", status=409)


def _send_mouse_click(hwnd: int, x: int, y: int, window: dict[str, Any]) -> None:
    rect_x, rect_y = window["x"] + x, window["y"] + y
    if not (window["x"] <= rect_x < window["x"] + window["width"]
            and window["y"] <= rect_y < window["y"] + window["height"]):
        raise WinAppError("Click coordinates fall outside the selected window")
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
    events = (_INPUT * 3)()
    events[0].type = 0
    events[0].mi = _MOUSEINPUT(absolute_x, absolute_y, 0, 0x0001 | 0x8000 | 0x4000, 0, 0)
    events[1].type = 0
    events[1].mi = _MOUSEINPUT(absolute_x, absolute_y, 0, 0x0002, 0, 0)
    events[2].type = 0
    events[2].mi = _MOUSEINPUT(absolute_x, absolute_y, 0, 0x0004, 0, 0)
    if _user32.SendInput(3, events, ctypes.sizeof(_INPUT)) != 3:
        raise WinAppError("Windows did not accept the click input", status=503)


def _send_keyboard_input(hwnd: int, kind: str, text: str | None = None, key: str | None = None) -> None:
    foreground = _user32.GetForegroundWindow()
    if not foreground or _user32.GetAncestor(foreground, GA_ROOT) != hwnd:
        raise WinAppError("The selected window lost focus; activate it manually and retry", status=409)
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
    if _user32.SendInput(len(events), events, ctypes.sizeof(_INPUT)) != len(events):
        raise WinAppError("Windows did not accept the keyboard input", status=503)


def _validated_click(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("confirm") is not True:
        raise WinAppError("Confirm the previewed click before sending it", code="CONFIRM_REQUIRED")
    values = {"owner": _validated_owner(data.get("owner"))}
    for key in ("windowId", "x", "y"):
        value = data.get(key)
        if type(value) is not int:
            raise WinAppError(f"{key} must be an integer")
        values[key] = value
    return values


def _validated_input(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("confirm") is not True:
        raise WinAppError("Confirm the previewed input before sending it", code="CONFIRM_REQUIRED")
    values: dict[str, Any] = {
        "owner": _validated_owner(data.get("owner")),
        "windowId": data.get("windowId"),
        "kind": data.get("kind"),
    }
    if type(values["windowId"]) is not int:
        raise WinAppError("windowId must be an integer")
    if values["kind"] == "type":
        text = data.get("text")
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_INPUT_TEXT_CHARS \
                or not all(char.isprintable() and unicodedata.category(char) not in ("Cc", "Cf", "Cs")
                           for char in text):
            raise WinAppError(f"text must contain 1-{MAX_INPUT_TEXT_CHARS} printable characters")
        values["text"] = text
    elif values["kind"] == "key":
        if data.get("key") not in INPUT_KEYS:
            raise WinAppError("key must be one of: " + ", ".join(INPUT_KEYS))
        values["key"] = data["key"]
    else:
        raise WinAppError("kind must be type or key")
    return values


def winapps_control_click(data: dict[str, Any]) -> dict[str, Any]:
    window = None
    values: dict[str, Any] = {}
    try:
        values = _validated_click(data)
        with _CONTROL_LOCK:
            _require_control_locked(values["owner"], data.get("confirm"))
            hwnd, window = _visible_window(values["windowId"])
            if not 0 <= values["x"] < window["width"] or not 0 <= values["y"] < window["height"]:
                raise WinAppError("Click coordinates are outside the selected window")
            _focus_window(hwnd)
            hwnd, window = _visible_window(hwnd)
            _require_control_locked(values["owner"], data.get("confirm"))
            _send_mouse_click(hwnd, values["x"], values["y"], window)
            _CONTROL_STATE["armedAt"] = time.monotonic()
        _record_audit("click", window=window, detail={
            "x": values["x"], "y": values["y"], "ok": True,
        })
        return {"ok": True, "actionSent": True, "windowId": hwnd, "x": values["x"], "y": values["y"]}
    except WinAppError as exc:
        _record_audit("click", window=window, detail={
            "x": values.get("x"), "y": values.get("y"), "ok": False, "reason": str(exc)[:120],
        })
        raise


def winapps_control_input(data: dict[str, Any]) -> dict[str, Any]:
    window = None
    values: dict[str, Any] = {}
    try:
        values = _validated_input(data)
        with _CONTROL_LOCK:
            _require_control_locked(values["owner"], data.get("confirm"))
            hwnd, window = _visible_window(values["windowId"])
            _focus_window(hwnd)
            hwnd, window = _visible_window(hwnd)
            _require_control_locked(values["owner"], data.get("confirm"))
            _send_keyboard_input(hwnd, values["kind"], values.get("text"), values.get("key"))
            _CONTROL_STATE["armedAt"] = time.monotonic()
        detail = {
            "kind": values["kind"],
            "ok": True,
            "textLength": len(values.get("text", "")),
            "key": values.get("key"),
        }
        _record_audit("input", window=window, detail=detail)
        return {"ok": True, "actionSent": True, "windowId": hwnd, **detail}
    except WinAppError as exc:
        _record_audit("input", window=window, detail={
            "kind": values.get("kind"), "textLength": len(values.get("text", "")),
            "key": values.get("key"), "ok": False, "reason": str(exc)[:120],
        })
        raise


def doctor() -> dict[str, Any]:
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
    for window in windows[:8]:
        try:
            result["capture"] = winapps_window_screenshot(window["windowId"]).startswith(b"\x89PNG")
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
