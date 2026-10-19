"""Windows operations that preserve the native HWND hosting VLC."""
import ctypes
import os
from ctypes import wintypes
from camfloat.camera_model import APP_USER_MODEL_ID

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND


def keep_above_owned_windows(widget, siblings):
    """Repair sibling activation order without activating or moving the owner.

    Only raise when one of our visible video input windows is above the tools.
    Never make a non-topmost app topmost or reorder it on every timer tick.
    """
    hwnd = int(widget.winId())
    siblings = {int(s.winId()) for s in siblings if s.isVisible()}
    previous = user32.GetWindow(hwnd, 3)  # GW_HWNDPREV
    seen = set()
    while previous and previous not in seen:
        if previous in siblings:
            if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                       0x0001 | 0x0002 | 0x0010 | 0x0200):
                raise ctypes.WinError(ctypes.get_last_error())
            return True
        seen.add(previous)
        previous = user32.GetWindow(previous, 3)
    return False


def app_is_foreground():
    process = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(process))
    return process.value == os.getpid()


def configure_app_identity():
    """Stable taskbar identity; call before creating QApplication/windows."""
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    result = shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    if result < 0:
        raise OSError(f'AppUserModelID failed: {result:#x}')


def taskbar_icon_state(widget):
    """Read actual HWND icons/styles, rather than just checking a QIcon object."""
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    hwnd = int(widget.winId())
    icons = [bool(user32.SendMessageW(hwnd, 0x007F, kind, 0)) for kind in (0, 1, 2)]
    return dict(small=icons[0], large=icons[1], small2=icons[2],
                tool_window=bool(user32.GetWindowLongW(hwnd, -20) & 0x80))


def set_topmost(widget, enabled):
    # Owned overlays must not reorder/demote their owner as a side effect.
    # Match Qt's use of SWP_NOOWNERZORDER when changing native topmost state.
    if not user32.SetWindowPos(int(widget.winId()), ctypes.c_void_p(-1 if enabled else -2),
                              0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200):
        raise ctypes.WinError(ctypes.get_last_error())


def is_topmost(widget):
    return bool(user32.GetWindowLongW(int(widget.winId()), -20) & 0x00000008)


def ensure_taskbar_minimize(widget):
    """Frameless Qt windows need WS_MINIMIZEBOX/SYSMENU for shell toggling.

    Apply styles in place: never recreate the HWND which owns the VLC children.
    """
    hwnd = int(widget.winId())
    style = user32.GetWindowLongW(hwnd, -16)
    wanted = style | 0x00020000 | 0x00080000
    if wanted != style:
        ctypes.set_last_error(0)
        previous = user32.SetWindowLongW(hwnd, -16, wanted)
        if previous == 0 and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020):
            raise ctypes.WinError(ctypes.get_last_error())


def taskbar_can_minimize(widget):
    return bool(user32.GetWindowLongW(int(widget.winId()), -16) & 0x00020000)


def system_minimize(widget):
    """Exercise the native minimize command also used by the Windows shell."""
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW(int(widget.winId()), 0x0112, 0xF020, 0)
