"""Windows operations that preserve the native HWND hosting VLC."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long


def set_topmost(widget, enabled):
    if not user32.SetWindowPos(int(widget.winId()), ctypes.c_void_p(-1 if enabled else -2),
                              0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010):
        raise ctypes.WinError(ctypes.get_last_error())


def is_topmost(widget):
    return bool(user32.GetWindowLongW(int(widget.winId()), -20) & 0x00000008)
