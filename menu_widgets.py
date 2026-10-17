"""A visible on/off switch for settings embedded in menus."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget, QWidgetAction

from icons import icon


class SwitchButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggled.connect(self.update)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#568fce' if self.isChecked() else '#3b475a'))
        painter.drawRoundedRect(QRectF(0, 1, 40, 20), 10, 10)
        painter.setBrush(QColor('#edf3fc'))
        painter.drawEllipse(QRectF(22 if self.isChecked() else 3, 4, 14, 14))
        if self.hasFocus():
            painter.setPen(QColor('#c4ddff'))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(.5, .5, 39, 21), 10, 10)


def switch_action(menu, name, enabled, callback):
    action = QWidgetAction(menu)
    action.setText(name)
    widget = QWidget()
    widget.setStyleSheet('QWidget{background:transparent;color:#dae5f5;}')
    row = QHBoxLayout(widget)
    row.setContentsMargins(10, 6, 10, 6)
    row.setSpacing(9)
    glyph = QLabel()
    glyph.setPixmap(icon('chip').pixmap(16, 16))
    row.addWidget(glyph)
    row.addWidget(QLabel(name))
    row.addStretch()
    state = QLabel('ON' if enabled else 'OFF')
    state.setFixedWidth(25)
    row.addWidget(state)
    switch = SwitchButton()
    switch.setAccessibleName(name)
    switch.setChecked(enabled)
    switch.toggled.connect(lambda checked: (state.setText('ON' if checked else 'OFF'), callback(checked)))
    row.addWidget(switch)
    action.setDefaultWidget(widget)
    action.switch = switch
    menu.addAction(action)
    return action
