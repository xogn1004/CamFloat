"""Predictable tooltips for independent, nonactivating video/tool windows."""
import weakref
from shiboken6 import isValid
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QToolTip


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
                             | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.bubble.setTextFormat(Qt.TextFormat.PlainText)
        self.bubble.setWordWrap(True)
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.bubble.setStyleSheet('background:#1b2432;color:#e4ecf8;border:1px solid #536781;'
                                 'border-radius:5px;padding:6px 8px;font-size:11px;')
        self.bubble.hide()
        self.lifetime = QTimer(self)
        self.lifetime.setSingleShot(True)
        self.lifetime.timeout.connect(self.bubble.hide)
        owner.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        owner.installEventFilter(self)

    def add(self, widget, *, click=False):
        widget.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        widget.installEventFilter(self)
        if click:
            widget.clicked.connect(lambda: self.show_for(widget))

    def show_for(self, widget):
        self.clear()
        self.target = weakref.ref(widget)
        self.show_tip(require_hover=False)

    def clear(self):
        self.timer.stop()
        self.target = None
        self.lifetime.stop()
        self.bubble.hide()
        QToolTip.hideText()

    def show_tip(self, *, require_hover=True):
        widget = self.target() if self.target else None
        modal = QApplication.activeModalWidget()
        if (widget is None or not isValid(widget) or not widget.isVisible() or not widget.toolTip()
                or QApplication.activePopupWidget()
                or (modal and modal is not self.parent() and not modal.isAncestorOf(self.parent()))
                or (require_hover and not widget.rect().contains(widget.mapFromGlobal(QCursor.pos())))):
            return
        # Qt's QTipLabel can disappear immediately for an inactive owned HWND.
        # An explicit nonactivating owned label avoids that active-window policy.
        self.bubble.hide()
        area = widget.screen().availableGeometry()
        self.bubble.setMinimumSize(0, 0)
        self.bubble.setMaximumSize(max(120, min(520, area.width() - 16)), 16777215)
        self.bubble.setText(widget.toolTip())
        # Polish, size and stacking are final before the first visible paint.
        self.bubble.ensurePolished()
        self.bubble.setFixedSize(self.bubble.sizeHint())
        point = widget.mapToGlobal(QPoint(0, widget.height() + 6))
        x = max(area.left(), min(point.x(), area.right() - self.bubble.width()))
        y = point.y() if point.y() + self.bubble.height() <= area.bottom() else widget.mapToGlobal(QPoint(0, 0)).y() - self.bubble.height() - 6
        self.bubble.move(x, max(area.top(), y))
        self.bubble.show()
        self.lifetime.start(5000)

    def eventFilter(self, watched, event):
        if watched is self.parent():
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self.clear()
            return False
        if event.type() == QEvent.Type.Enter:
            self.clear()
            self.target = weakref.ref(watched)
            self.timer.start()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.MouseButtonPress):
            if self.target and self.target() is watched:
                self.clear()
        elif event.type() == QEvent.Type.ToolTip:
            return True  # A single delay, independent of Qt's active-window heuristics.
        return False
