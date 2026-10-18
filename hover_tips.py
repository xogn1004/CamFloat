"""Predictable tooltips for independent, nonactivating video/tool windows."""
import weakref
from shiboken6 import isValid
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QToolTip
from native_window import set_topmost


class HoverTips(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.target = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.show_tip)
        self.bubble = QLabel(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                             | Qt.WindowType.NoDropShadowWindowHint)
        self.bubble.setTextFormat(Qt.TextFormat.PlainText)
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.bubble.setStyleSheet('background:#1b2432;color:#e4ecf8;border:1px solid #536781;'
                                 'border-radius:5px;padding:6px 8px;font-size:11px;')
        self.bubble.hide()
        self.lifetime = QTimer(self)
        self.lifetime.setSingleShot(True)
        self.lifetime.timeout.connect(self.bubble.hide)
        owner.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)

    def add(self, widget):
        widget.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        widget.installEventFilter(self)

    def clear(self):
        self.timer.stop()
        self.target = None
        self.lifetime.stop()
        self.bubble.hide()
        QToolTip.hideText()

    def show_tip(self):
        widget = self.target() if self.target else None
        if (widget is None or not isValid(widget) or not widget.isVisible() or not widget.toolTip()
                or QApplication.activePopupWidget() or QApplication.activeModalWidget()
                or not widget.rect().contains(widget.mapFromGlobal(QCursor.pos()))):
            return
        # Qt's QTipLabel can disappear immediately for an inactive owned HWND.
        # An explicit nonactivating owned label avoids that active-window policy.
        self.bubble.setText(widget.toolTip())
        self.bubble.adjustSize()
        point = widget.mapToGlobal(QPoint(0, widget.height() + 6))
        area = widget.screen().availableGeometry()
        x = max(area.left(), min(point.x(), area.right() - self.bubble.width()))
        y = point.y() if point.y() + self.bubble.height() <= area.bottom() else widget.mapToGlobal(QPoint(0, 0)).y() - self.bubble.height() - 6
        self.bubble.move(x, max(area.top(), y))
        self.bubble.show()
        set_topmost(self.bubble, True)
        self.lifetime.start(5000)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter:
            self.target = weakref.ref(watched)
            self.timer.start()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.MouseButtonPress):
            if self.target and self.target() is watched:
                self.clear()
        elif event.type() == QEvent.Type.ToolTip:
            return True  # A single delay, independent of Qt's active-window heuristics.
        return False
