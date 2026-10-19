"""Per-user shell links and supported, consent-based Windows taskbar pinning.

No elevation, taskbar registry edits, or undocumented pin verbs are used.
COM/WinRT slots follow IShellLinkW, IPersistFile, IPropertyStore, IAsyncInfo
and Windows.UI.Shell.ITaskbarManager in Microsoft's SDK/windows-rs metadata.
"""
import ctypes
import os
from pathlib import Path
import uuid
import winreg

from PySide6.QtCore import QObject, QEventLoop, QTimer
from camfloat.camera_model import APP_TITLE, APP_USER_MODEL_ID
from camfloat.windows_consent import GUID, method, checked


def release(pointer):
    if pointer:
        method(pointer, 2, ctypes.c_ulong)(pointer)
        pointer.value = None


def query(pointer, iid):
    result = ctypes.c_void_p()
    checked(method(pointer, 0, ctypes.c_long, ctypes.POINTER(GUID),
                   ctypes.POINTER(ctypes.c_void_p))(pointer, ctypes.byref(GUID(iid)), ctypes.byref(result)))
    return result


class Apartment:
    def __init__(self):
        self.runtime = ctypes.OleDLL('ole32')
        self.runtime.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.runtime.CoInitializeEx.restype = ctypes.c_long
        hr = self.runtime.CoInitializeEx(None, 2)
        self.initialized = hr >= 0
        if hr != ctypes.c_long(0x80010106).value:
            checked(hr)

    def close(self):
        if self.initialized:
            self.runtime.CoUninitialize()
            self.initialized = False


def known_folder(identifier):
    shell = ctypes.WinDLL('shell32')
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint,
                                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    value = ctypes.c_void_p()
    checked(shell.SHGetKnownFolderPath(ctypes.byref(GUID(identifier)), 0, None, ctypes.byref(value)))
    try:
        return Path(ctypes.wstring_at(value))
    finally:
        ole = ctypes.OleDLL('ole32')
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole.CoTaskMemFree(value)


def desktop_shortcut():
    return known_folder('B4BFCC3A-DB2C-424C-B029-7FE99A87C641') / 'CamFloat.lnk'


def start_menu_shortcut():
    return known_folder('A77F5D77-2E2B-44C3-A6A2-ABA601054A51') / 'CamFloat' / 'CamFloat.lnk'


class PropertyKey(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', ctypes.c_ulong)]


class VariantValue(ctypes.Union):
    _fields_ = [('pointer', ctypes.c_void_p), ('storage', ctypes.c_ubyte * 16)]


class PropVariant(ctypes.Structure):
    _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3), ('value', VariantValue)]


def create_shortcut(destination, executable):
    """Create a real .lnk atomically; preserve any existing user shortcut."""
    destination, executable = Path(destination), Path(executable).resolve()
    if destination.exists():
        return False
    if not executable.is_file():
        raise OSError('Executable is missing')
    apartment = Apartment()
    link, persist, properties = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    temporary = destination.with_name('.CamFloat-' + uuid.uuid4().hex + '.lnk')
    try:
        apartment.runtime.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
            ctypes.c_uint, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        apartment.runtime.CoCreateInstance.restype = ctypes.c_long
        checked(apartment.runtime.CoCreateInstance(
            ctypes.byref(GUID('00021401-0000-0000-C000-000000000046')), None, 1,
            ctypes.byref(GUID('000214F9-0000-0000-C000-000000000046')), ctypes.byref(link)))
        for slot, text in ((20, str(executable)), (9, str(executable.parent)), (7, APP_TITLE)):
            checked(method(link, slot, ctypes.c_long, ctypes.c_wchar_p)(link, text))
        checked(method(link, 17, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(link, str(executable), 0))
        properties = query(link, '886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')
        key = PropertyKey(GUID('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3'), 5)
        app_id = ctypes.create_unicode_buffer(APP_USER_MODEL_ID)
        value = PropVariant()
        value.vt = 31  # VT_LPWSTR; SetValue copies the caller-owned string.
        value.value.pointer = ctypes.cast(app_id, ctypes.c_void_p).value
        checked(method(properties, 6, ctypes.c_long, ctypes.POINTER(PropertyKey),
                       ctypes.POINTER(PropVariant))(properties, ctypes.byref(key), ctypes.byref(value)))
        checked(method(properties, 7, ctypes.c_long)(properties))
        persist = query(link, '0000010B-0000-0000-C000-000000000046')
        destination.parent.mkdir(parents=True, exist_ok=True)
        checked(method(persist, 6, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(persist, str(temporary), True))
        # Windows rename is exclusive, so a concurrently created shortcut wins.
        os.rename(temporary, destination)
        return True
    finally:
        release(properties)
        release(persist)
        release(link)
        apartment.close()
        temporary.unlink(missing_ok=True)


def shortcut_target(path):
    """Read a .lnk without executing it (also used by isolated QA)."""
    apartment = Apartment()
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        apartment.runtime.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
            ctypes.c_uint, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        apartment.runtime.CoCreateInstance.restype = ctypes.c_long
        checked(apartment.runtime.CoCreateInstance(
            ctypes.byref(GUID('00021401-0000-0000-C000-000000000046')), None, 1,
            ctypes.byref(GUID('000214F9-0000-0000-C000-000000000046')), ctypes.byref(link)))
        persist = query(link, '0000010B-0000-0000-C000-000000000046')
        checked(method(persist, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_uint)(persist, str(path), 0))
        buffer = ctypes.create_unicode_buffer(32768)
        checked(method(link, 3, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_uint)(link, buffer, len(buffer), None, 4))
        return Path(buffer.value)
    finally:
        release(persist)
        release(link)
        apartment.close()


def laf_token_required():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModel\LimitedAccessFeatures\com.microsoft.windows.taskbar.pin') as key:
            return bool(winreg.QueryValueEx(key,
                '4096B239A7295B635C090E647E867B5707DA6AB6CB78340B01FE4E0C8F4953D4')[0])
    except FileNotFoundError:
        return False


class TaskbarPinning(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = False
        self.apartment = None
        self.manager = ctypes.c_void_p()
        self.operation = ctypes.c_void_p()
        self.info = ctypes.c_void_p()
        self.callback = None
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.finish(None))
        factory, marker = ctypes.c_void_p(), ctypes.c_void_p()
        name = ctypes.c_void_p()
        try:
            if laf_token_required():
                return
            self.apartment = Apartment()
            runtime = ctypes.WinDLL('combase')
            runtime.WindowsCreateString.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            runtime.WindowsCreateString.restype = ctypes.c_long
            runtime.WindowsDeleteString.argtypes = [ctypes.c_void_p]
            runtime.RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
            runtime.RoGetActivationFactory.restype = ctypes.c_long
            text = 'Windows.UI.Shell.TaskbarManager'
            checked(runtime.WindowsCreateString(text, len(text), ctypes.byref(name)))
            checked(runtime.RoGetActivationFactory(name,
                ctypes.byref(GUID('DB32AB74-DE52-4FE6-B7B6-95FF9F8395DF')), ctypes.byref(factory)))
            marker = query(factory, 'CDFEFD63-E879-4134-B9A7-8283F05F9480')
            checked(method(factory, 6, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(factory, ctypes.byref(self.manager)))
            supported = ctypes.c_ubyte()
            checked(method(self.manager, 6, ctypes.c_long, ctypes.POINTER(ctypes.c_ubyte))(self.manager, ctypes.byref(supported)))
            self.available = bool(supported.value)
        except (OSError, ValueError, AttributeError):
            self.available = False
        finally:
            if name:
                runtime.WindowsDeleteString(name)
            release(marker)
            release(factory)

    def begin(self, slot, callback, timeout=120000):
        self.cancel()
        self.callback = callback
        try:
            checked(method(self.manager, slot, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
                self.manager, ctypes.byref(self.operation)))
            self.info = query(self.operation, '00000036-0000-0000-C000-000000000046')
            self.timer.start()
            self.timeout.start(timeout)
        except OSError:
            self.finish(None)

    def poll(self):
        try:
            status = ctypes.c_int()
            checked(method(self.info, 7, ctypes.c_long, ctypes.POINTER(ctypes.c_int))(self.info, ctypes.byref(status)))
            if status.value == 0:
                return
            if status.value != 1:
                self.finish(None)
                return
            result = ctypes.c_ubyte()
            checked(method(self.operation, 8, ctypes.c_long, ctypes.POINTER(ctypes.c_ubyte))(
                self.operation, ctypes.byref(result)))
            self.finish(bool(result.value))
        except OSError:
            self.finish(None)

    def finish(self, result):
        callback = self.callback
        self.cancel()
        if callback:
            callback(result)

    def cancel(self):
        self.timer.stop()
        self.timeout.stop()
        self.callback = None
        if self.info:
            method(self.info, 9, ctypes.c_long)(self.info)  # Cancel; safe after completion.
            method(self.info, 10, ctypes.c_long)(self.info)  # Close.
        release(self.info)
        release(self.operation)

    def is_pinned(self):
        if not self.available:
            return None
        result = []
        loop = QEventLoop()
        def done(value):
            result.append(value)
            loop.quit()
        self.begin(8, done, timeout=1200)
        if not result:
            loop.exec()
        # Application shutdown can end the nested loop before an async result.
        return result[0] if result else None

    def request(self, executable, callback):
        try:
            if not self.available:
                raise OSError('Taskbar pinning unavailable')
            entry = start_menu_shortcut()
            if entry.exists():
                if shortcut_target(entry).resolve() != Path(executable).resolve():
                    raise OSError('Existing Start menu entry points to another location')
            else:
                create_shortcut(entry, executable)
            allowed = ctypes.c_ubyte()
            checked(method(self.manager, 7, ctypes.c_long, ctypes.POINTER(ctypes.c_ubyte))(
                self.manager, ctypes.byref(allowed)))
            if not allowed.value:
                raise OSError('Taskbar pinning not allowed')
            self.begin(10, callback)
        except OSError:
            callback(None)

    def close(self):
        self.cancel()
        release(self.manager)
        if self.apartment:
            self.apartment.close()
