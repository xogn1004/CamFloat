"""Short dialog feedback that never participates in the form layout."""
import weakref
from shiboken6 import isValid
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QLabel, QMessageBox


def confirm_action(owner, title, text, action):
    box = QMessageBox(owner)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    confirm = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton('취소', QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is confirm


class Feedback(QLabel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.anchor = None
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet('background:#29364b;color:#edf4ff;border:1px solid #52647e;'
                           'border-radius:6px;padding:8px 10px;font-size:11px;')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.clear_message)
        owner.installEventFilter(self)
        self.hide()

    def show_message(self, text, anchor=None):
        if not text or not self.owner.isVisible():
            return
        self.anchor = weakref.ref(anchor) if anchor is not None else None
        self.setText(text)
        natural_width = max(self.fontMetrics().horizontalAdvance(line) for line in text.splitlines()) + 28
        self.setFixedWidth(min(350, self.owner.width() - 40, max(150, natural_width)))
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(4500)

    def place(self):
        anchor = self.anchor() if self.anchor else None
        if anchor is not None and isValid(anchor) and anchor.isVisible():
            point = self.owner.mapFromGlobal(anchor.mapToGlobal(QPoint(0, anchor.height() + 5)))
        else:
            point = QPoint((self.owner.width() - self.width()) // 2, self.owner.height() - self.height() - 52)
        self.move(max(12, min(point.x(), self.owner.width() - self.width() - 12)),
                  max(12, min(point.y(), self.owner.height() - self.height() - 12)))

    def clear_message(self, *_):
        self.timer.stop()
        self.hide()
        self.setText('')
        self.anchor = None

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        elif event.type() == QEvent.Type.Hide:
            self.clear_message()
        return False
