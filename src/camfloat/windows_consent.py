"""Nonblocking Windows Hello verification for a desktop HWND (WinRT ABI).

Interface IDs and slots follow Microsoft's UserConsentVerifierInterop.h,
windows.security.credentials.ui.h and AsyncInfo.h. No password is collected.
"""
import ctypes
import uuid
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


def method(pointer, slot, result, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[slot])


def checked(result):
    if result < 0:
        raise OSError('Windows verification unavailable')


class ConsentRequest(QObject):
    finished = Signal(bool, str)

    def __init__(self, owner):
        super().__init__(owner)
        self.operation = ctypes.c_void_p()
        self.info = ctypes.c_void_p()
        self.factory = ctypes.c_void_p()
        self.initialized = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(120000)
        self.timeout.timeout.connect(self.cancel)

    def start(self, hwnd):
        try:
            self.runtime = ctypes.WinDLL('combase', use_last_error=True)
            self.runtime.RoInitialize.argtypes = [ctypes.c_uint]
            self.runtime.RoInitialize.restype = ctypes.c_long
            result = self.runtime.RoInitialize(0)  # UI thread, STA
            self.initialized = result >= 0
            if result != ctypes.c_long(0x80010106).value:  # existing apartment
                checked(result)
            self.runtime.WindowsCreateString.argtypes = [wintypes.LPCWSTR, ctypes.c_uint,
                                                         ctypes.POINTER(ctypes.c_void_p)]
            self.runtime.WindowsCreateString.restype = ctypes.c_long
            self.runtime.WindowsDeleteString.argtypes = [ctypes.c_void_p]
            self.runtime.RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID),
                                                           ctypes.POINTER(ctypes.c_void_p)]
            self.runtime.RoGetActivationFactory.restype = ctypes.c_long
            name, message = ctypes.c_void_p(), ctypes.c_void_p()
            try:
                text = 'Windows.Security.Credentials.UI.UserConsentVerifier'
                checked(self.runtime.WindowsCreateString(text, len(text), ctypes.byref(name)))
                iid = GUID('39e050c3-4e74-441a-8dc0-b81104df949c')
                checked(self.runtime.RoGetActivationFactory(name, ctypes.byref(iid), ctypes.byref(self.factory)))
                text = 'CamFloat 연결 정보를 확인합니다.'
                checked(self.runtime.WindowsCreateString(text, len(text), ctypes.byref(message)))
                operation_iid = GUID('fd596ffd-2318-558f-9dbe-d21df43764a5')
                request = method(self.factory, 6, ctypes.c_long, wintypes.HWND, ctypes.c_void_p,
                                 ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
                checked(request(self.factory, hwnd, message, ctypes.byref(operation_iid),
                                ctypes.byref(self.operation)))
                info_iid = GUID('00000036-0000-0000-c000-000000000046')
                query = method(self.operation, 0, ctypes.c_long, ctypes.POINTER(GUID),
                               ctypes.POINTER(ctypes.c_void_p))
                checked(query(self.operation, ctypes.byref(info_iid), ctypes.byref(self.info)))
            finally:
                for string in (name, message):
                    if string:
                        self.runtime.WindowsDeleteString(string)
            self.timer.start()
            self.timeout.start()
        except (OSError, ValueError, AttributeError):
            self.complete(False, '본인 확인을 사용할 수 없습니다. Windows 로그인 설정을 확인하세요.')

    def poll(self):
        try:
            status = ctypes.c_int()
            checked(method(self.info, 7, ctypes.c_long, ctypes.POINTER(ctypes.c_int))(
                self.info, ctypes.byref(status)))
            if status.value == 0:
                return
            if status.value != 1:
                self.complete(False, '' if status.value == 2 else '본인 확인을 다시 시도하세요.')
                return
            result = ctypes.c_int()
            checked(method(self.operation, 8, ctypes.c_long, ctypes.POINTER(ctypes.c_int))(
                self.operation, ctypes.byref(result)))
            self.complete(result.value == 0, '' if result.value in (0, 6) else '본인 확인을 다시 시도하세요.')
        except (OSError, ValueError):
            self.complete(False, '본인 확인을 다시 시도하세요.')

    def cancel(self):
        if self.info:
            method(self.info, 9, ctypes.c_long)(self.info)
        self.complete(False, '')

    def complete(self, success, message):
        self.timer.stop()
        self.timeout.stop()
        if self.info:
            method(self.info, 10, ctypes.c_long)(self.info)
        for pointer in (self.info, self.operation, self.factory):
            if pointer:
                method(pointer, 2, ctypes.c_ulong)(pointer)
                pointer.value = None
        if self.initialized:
            self.runtime.RoUninitialize()
            self.initialized = False
        self.finished.emit(success, message)

