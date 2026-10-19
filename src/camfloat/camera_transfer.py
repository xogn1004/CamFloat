"""A credentials-free preview of cameras to append to the current draft."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QTableWidget,
                              QTableWidgetItem, QHeaderView, QVBoxLayout)
from camfloat.camera_model import camera_display_name
from camfloat.ui_theme import CAMERA_STYLE


class ImportPreview(QDialog):
    def __init__(self, candidates, duplicates, parent=None):
        super().__init__(parent)
        self.candidates = candidates
        self.setWindowTitle('카메라 불러오기')
        self.setStyleSheet(CAMERA_STYLE)
        self.resize(430, 340)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        title = QLabel(f'추가할 카메라 {len(candidates)}대')
        title.setStyleSheet('font-size:17px;font-weight:600;')
        root.addWidget(title)
        if duplicates:
            note = QLabel(f'이미 등록된 {duplicates}대는 제외했습니다.')
            note.setStyleSheet('color:#9eafc6;font-size:11px;')
            root.addWidget(note)
        self.table = QTableWidget(len(candidates), 2)
        self.table.setHorizontalHeaderLabels(['이름', '사용'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 85)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, camera in enumerate(candidates):
            item = QTableWidgetItem(camera_display_name(camera))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem('사용' if camera['enabled'] else '사용 안 함'))
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.add = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add.setText('추가')
        self.add.setObjectName('primary')
        self.add.setEnabled(bool(candidates))
        self.table.itemChanged.connect(lambda *_: self.add.setEnabled(bool(self.selected_cameras())))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_cameras(self):
        return [camera for row, camera in enumerate(self.candidates)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
