"""Shared disclosure lifetime and clipboard policy for camera management."""
import ctypes
import time
import uuid
import weakref
from ctypes import wintypes
from shiboken6 import isValid

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QEvent, QMimeData, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QMenu, QToolButton, QWidget

from icons import icon
from native_window import app_is_foreground
from windows_consent import ConsentRequest


class SecureClipboard(QObject):
    def __init__(self):
        super().__init__(QApplication.instance())
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.clear_owned)
        self.token = ''
        QApplication.instance().aboutToQuit.connect(self.clear_owned)

    def copy(self, text):
        mime = QMimeData()
        mime.setText(text)
        self.token = uuid.uuid4().hex
        mime.setData('application/x-camfloat-copy', QByteArray(self.token.encode()))
        for name in ('CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard'):
            mime.setData(f'application/x-qt-windows-mime;value="{name}"', QByteArray(b'\0' * 4))
        QApplication.clipboard().setMimeData(mime)
        self.timer.start()

    def clear_owned(self):
        mime = QApplication.clipboard().mimeData()
        if self.token and mime and bytes(mime.data('application/x-camfloat-copy')) == self.token.encode():
            QApplication.clipboard().clear()
        self.token = ''


def secure_clipboard():
    app = QApplication.instance()
    if not hasattr(app, '_secure_clipboard'):
        app._secure_clipboard = SecureClipboard()
    return app._secure_clipboard


class SessionLockFilter(QAbstractNativeEventFilter):
    def __init__(self, controller):
        super().__init__()
        self.controller = weakref.ref(controller)
        self.hwnd = 0
        self.installed = False
        self.registered = False
        self.wts = ctypes.WinDLL('wtsapi32')
        self.wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.wts.WTSRegisterSessionNotification.restype = wintypes.BOOL
        self.wts.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        self.wts.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

    def start(self):
        if self.installed:
            return
        controller = self.controller()
        if controller is None or not isValid(controller):
            return
        self.hwnd = int(controller.parent().winId())
        self.registered = bool(self.wts.WTSRegisterSessionNotification(self.hwnd, 0))
        QApplication.instance().installNativeEventFilter(self)
        self.installed = True

    def nativeEventFilter(self, event_type, message):
        if not self.installed or bytes(event_type) not in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            return False, 0
        if not int(message):
            return False, 0
        native = wintypes.MSG.from_address(int(message))
        controller = self.controller()
        if (native.message == 0x02B1 and native.wParam == 7 and native.hWnd == self.hwnd
                and controller is not None and isValid(controller)):
            controller.hide_all()
            if controller.request is not None:
                controller.request.cancel()
        return False, 0

    def close(self):
        app = QApplication.instance()
        if self.installed and app is not None:
            app.removeNativeEventFilter(self)
        self.installed = False
        if self.registered:
            self.wts.WTSUnRegisterSessionNotification(self.hwnd)
            self.registered = False
        self.hwnd = 0


class PrivacyController(QObject):
    notice = Signal(str)

    def __init__(self, owner, require_verification=False):
        super().__init__(owner)
        self.require_verification = require_verification
        self.fields = weakref.WeakSet()
        self.grant_until = 0
        self.generation = 0
        self.request = None
        self.grant_timer = QTimer(self)
        self.grant_timer.setSingleShot(True)
        self.grant_timer.setInterval(30000)
        self.grant_timer.timeout.connect(self.hide_all)
        QGuiApplication.instance().applicationStateChanged.connect(self.application_changed)
        self.lock_filter = SessionLockFilter(self)
        owner.installEventFilter(self)
        owner.finished.connect(self.close)
        owner.destroyed.connect(self.lock_filter.close)

    def eventFilter(self, watched, event):
        if watched is self.parent():
            if event.type() == QEvent.Type.Show:
                self.lock_filter.start()
            elif event.type() == QEvent.Type.Hide:
                self.hide_all()
                self.lock_filter.close()
        return super().eventFilter(watched, event)

    def application_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            if self.request is not None:
                for field in self.live_fields():
                    field.conceal()
                self.grant_until = 0
            else:
                self.hide_all()

    def hide_all(self):
        self.grant_timer.stop()
        self.grant_until = 0
        self.generation += 1
        for field in self.live_fields():
            field.conceal()

    def live_fields(self):
        result = []
        for field in list(self.fields):
            if isValid(field):
                result.append(field)
            else:
                self.fields.discard(field)
        return result

    def authorize(self, callback, force=False):
        if self.request is not None:
            return
        if not force and (not self.require_verification or time.monotonic() < self.grant_until):
            callback()
            return
        self.hide_all()
        generation = self.generation
        owner = QApplication.activeWindow() or self.parent()
        request = ConsentRequest(self)
        self.request = request
        def complete(success, message):
            self.request = None
            request.deleteLater()
            def finish():
                if success and self.generation == generation and self.parent().isVisible() and app_is_foreground():
                    self.grant_until = time.monotonic() + 30
                    self.grant_timer.start()
                    callback()
                elif message:
                    self.notice.emit(message)
                elif success:
                    self.notice.emit('화면이 변경되었습니다. CamFloat에서 다시 확인하세요.')
            QTimer.singleShot(150, self, finish)
        request.finished.connect(complete)
        request.start(int(owner.winId()))

    def copy(self, value, message='정보를 복사했습니다. 30초 후 클립보드에서 지웁니다.'):
        def perform():
            secure_clipboard().copy(value)
            self.notice.emit(message)
        self.authorize(perform)

    def close(self, *_):
        self.hide_all()
        if self.request is not None:
            self.request.cancel()
        self.lock_filter.close()


class PrivateLineEdit(QLineEdit):
    def __init__(self, field):
        super().__init__(field)
        self.field = field
        self.setDragEnabled(False)
        self.setInputMethodHints(Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy) or event.matches(QKeySequence.StandardKey.Cut):
            if self.field.revealed and self.hasSelectedText():
                self.field.controller.copy(self.selectedText())
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_action = menu.addAction('복사', lambda: self.field.controller.copy(self.selectedText()))
        copy_action.setEnabled(self.field.revealed and self.hasSelectedText())
        if not self.isReadOnly():
            menu.addAction('붙여넣기', self.paste)
        menu.addAction('전체 선택', self.selectAll)
        menu.exec(event.globalPos())
        menu.deleteLater()


class SensitiveField(QWidget):
    """Read-only values use a fixed placeholder; editable fields use Qt Password."""
    def __init__(self, controller, label, value='', editable=False, parent=None):
        super().__init__(parent)
        self.controller, self.label, self.editable = controller, label, editable
        self._value = value
        self.revealed = False
        controller.fields.add(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.edit = PrivateLineEdit(self)
        self.edit.setReadOnly(not editable)
        self.edit.setAccessibleName(label)
        row.addWidget(self.edit, 1)
        self.eye = QToolButton(self)
        self.eye.setIcon(icon('eye'))
        self.eye.setFixedSize(30, 32)
        self.eye.setToolTip(f'{label} 보기 · 30초 후 숨김')
        self.eye.clicked.connect(self.toggle)
        row.addWidget(self.eye)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.conceal)
        self.set_value(value)

    def set_value(self, value):
        self._value = str(value or '')
        if self.editable:
            self.edit.setText(self._value)
        self.conceal()
        self.eye.setEnabled(bool(self._value) or self.editable)

    def value(self):
        return self.edit.text() if self.editable else self._value

    def toggle(self):
        if self.revealed:
            self.conceal()
        else:
            self.controller.authorize(self.reveal)

    def reveal(self):
        self.revealed = True
        if not self.editable:
            self.edit.setText(self._value)
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal)
        self.eye.setIcon(icon('eye_off'))
        self.eye.setToolTip(f'{self.label} 숨기기')
        self.timer.start()

    def conceal(self):
        self.revealed = False
        self.timer.stop()
        if self.editable:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        else:
            self.edit.setText('••••••••' if self._value else '설정 없음')
        self.eye.setIcon(icon('eye'))
        self.eye.setToolTip(f'{self.label} 보기 · 30초 후 숨김')

    def hideEvent(self, event):
        self.conceal()
        super().hideEvent(event)
