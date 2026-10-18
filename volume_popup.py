"""Compact volume control kept inside its SCREEN input surface."""
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QSlider, QVBoxLayout


class VolumePopup(QFrame):
    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.setObjectName('volumePopup')
        self.setStyleSheet('QFrame#volumePopup{background:rgba(19,24,33,248);'
            'border:1px solid #405069;border-radius:8px;}'
            'QSlider::groove:vertical{width:3px;background:#3b485c;border-radius:1px;}'
            'QSlider::add-page:vertical{background:#8dbbfa;border-radius:1px;}'
            'QSlider::handle:vertical{height:8px;background:#d4e6ff;margin:0 -3px;border-radius:4px;}')
        self.setFixedWidth(26)
        box = QVBoxLayout(self)
        box.setContentsMargins(7, 5, 7, 5)
        self.slider = QSlider(Qt.Orientation.Vertical, self)
        self.slider.setRange(0, 100)
        self.slider.setAccessibleName('이 영상 음량')
        self.slider.valueChanged.connect(lambda value: overlay.host.set_volume(overlay.index, value))
        box.addWidget(self.slider)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(220)
        self.hide_timer.timeout.connect(self.dismiss_if_outside)
        for widget in (self, self.slider):
            widget.installEventFilter(self)
        self.hide()

    def show_for_speaker(self):
        overlay = self.overlay
        camera = overlay.host.camera_for_slot(overlay.index)
        if not camera or overlay.expanded_controls() or not overlay.isVisible():
            return
        self.hide_timer.stop()
        self.slider.blockSignals(True)
        self.slider.setValue(camera['volume'])
        self.slider.blockSignals(False)
        anchor = overlay.mute.mapTo(overlay, QPoint(overlay.mute.width() // 2, 0))
        # Even a 150x90 pane must leave its speaker reachable below the popup.
        self.setFixedHeight(min(58, max(36, anchor.y() - 8)))
        x = max(4, min(anchor.x() - self.width() // 2, overlay.width() - self.width() - 4))
        y = max(4, min(anchor.y() - self.height() - 4, overlay.height() - self.height() - 4))
        self.move(x, y)
        self.show()
        self.raise_()
        overlay.idle_timer.start()

    def schedule_hide(self):
        if self.isVisible():
            self.hide_timer.start()

    def dismiss_if_outside(self):
        point = QCursor.pos()
        if self.slider.isSliderDown() or self.rect().contains(self.mapFromGlobal(point)):
            return
        if self.overlay.mute.rect().contains(self.overlay.mute.mapFromGlobal(point)):
            return
        self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter:
            self.hide_timer.stop()
        elif event.type() == QEvent.Type.Leave:
            self.schedule_hide()
        elif event.type() == QEvent.Type.Wheel:
            self.overlay.adjust_volume_wheel(event)
            return True
        elif event.type() == QEvent.Type.MouseButtonPress:
            self.overlay.host.select_slot(self.overlay.index)
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self.schedule_hide()
        return super().eventFilter(watched, event)
