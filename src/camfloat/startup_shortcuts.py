"""A one-time shortcut offer; ordinary users never need administrator rights."""
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
from camfloat.ui_theme import CAMERA_STYLE
from camfloat.windows_shortcuts import TaskbarPinning, create_shortcut, desktop_shortcut


class ShortcutDialog(QDialog):
    def __init__(self, owner, executable, desktop, taskbar, pinned=False):
        super().__init__(owner)
        self.executable, self.destination, self.taskbar = Path(executable), desktop, taskbar
        self.setWindowTitle('CamFloat 바로가기')
        self.setStyleSheet(CAMERA_STYLE)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        title = QLabel('바로가기를 추가할까요?')
        title.setStyleSheet('font-size:17px;font-weight:600;')
        layout.addWidget(title)
        exists = bool(desktop and desktop.exists())
        self.desktop = QCheckBox('바탕화면' + (' · 이미 추가됨' if exists else ''))
        self.desktop.setChecked(not exists and desktop is not None)
        self.desktop.setEnabled(not exists and desktop is not None)
        self.desktop.setToolTip('현재 프로그램 위치를 가리키는 CamFloat 바로가기를 만듭니다.')
        layout.addWidget(self.desktop)
        self.taskbar_box = QCheckBox('작업 표시줄' + (' · 이미 고정됨' if pinned else ''))
        self.taskbar_box.setEnabled(taskbar.available and not pinned)
        self.taskbar_box.setToolTip('Windows 확인 창에서 고정을 승인합니다.')
        if not self.taskbar_box.isEnabled() and not pinned:
            self.taskbar_box.setToolTip('이 Windows에서는 실행 중인 아이콘을 오른쪽 클릭해 고정하세요.')
        layout.addWidget(self.taskbar_box)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setFixedHeight(38)
        self.status.setStyleSheet('font-size:11px;color:#aebfd5;')
        layout.addWidget(self.status)
        buttons = QDialogButtonBox()
        self.apply = buttons.addButton('추가', QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply.setObjectName('primary')
        self.skip = buttons.addButton('건너뛰기', QDialogButtonBox.ButtonRole.RejectRole)
        self.skip.setDefault(True)
        self.apply.setAutoDefault(False)
        layout.addWidget(buttons)
        self.apply.clicked.connect(self.create)
        self.skip.clicked.connect(self.reject)
        for control in (self.desktop, self.taskbar_box):
            control.toggled.connect(self.update_action)
        self.update_action()

    def update_action(self):
        self.apply.setEnabled(self.desktop.isChecked() or self.taskbar_box.isChecked())

    def create(self):
        errors = []
        if self.desktop.isChecked():
            try:
                create_shortcut(self.destination, self.executable)
            except OSError:
                errors.append('바탕화면 추가를 건너뛰었습니다.')
        if self.taskbar_box.isChecked():
            self.desktop.setEnabled(False)
            self.taskbar_box.setEnabled(False)
            self.apply.setEnabled(False)
            self.skip.setText('닫기')
            self.status.setText('Windows에서 작업 표시줄 고정을 확인해주세요.')
            def finished(result):
                if result is None:
                    errors.append('작업 표시줄 아이콘을 오른쪽 클릭해 고정하세요.')
                if errors:
                    self.status.setText('\n'.join(errors))
                else:
                    self.accept()
            self.taskbar.request(self.executable, finished)
        elif errors:
            self.status.setText('\n'.join(errors))
            self.apply.setEnabled(False)
            self.skip.setText('닫기')
        else:
            self.accept()


def offer_shortcuts(owner, executable=None):
    taskbar = TaskbarPinning(owner)
    try:
        try:
            desktop = desktop_shortcut()
        except OSError:
            desktop = None
        pinned = taskbar.is_pinned() is True
        if (desktop is None or desktop.exists()) and (pinned or not taskbar.available):
            return
        dialog = ShortcutDialog(owner, executable or sys.executable, desktop, taskbar, pinned)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
    finally:
        taskbar.close()
        taskbar.deleteLater()


def maybe_offer_shortcuts(owner):
    if owner.config.get('shortcuts_prompted', True):
        return False
    try:
        with owner.modal():
            offer_shortcuts(owner)
    except OSError:
        # Protected/redirected shell folders must not stop normal startup.
        pass
    owner.config['shortcuts_prompted'] = True
    owner.persist()
    return True
