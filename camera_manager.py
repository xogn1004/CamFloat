"""Camera registry drafts and layout assignments, with private connection details."""
import copy
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QAbstractTableModel, QEvent, QIODevice, QModelIndex, QSaveFile, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QTableView, QTabWidget, QToolButton,
    QVBoxLayout, QWidget)

from camera_model import (camera_display_name, camera_url, default_config,
                          ensure_layout_slots, fill_empty_slots, supports_quality, reset_settings)
from camera_editor import CameraEditor
from icons import icon
from privacy import PrivacyController, SensitiveField
from ui_theme import CAMERA_STYLE
from feedback import Feedback, confirm_action
from camera_archive import encode, read_file, import_candidates
from camera_transfer import ImportPreview
from hover_tips import HoverTips
from ptz_control import DirectionControl, camera_key, eligible
from ptz_metadata import support_state, validated as validated_control


DIRECTION_LABELS = {'unchecked': '미확인', 'supported': '지원', 'unknown': '알 수 없음',
                    'unsupported': '앱 미지원', 'checking': '확인 중…'}


class CameraListModel(QAbstractTableModel):
    def __init__(self, cameras, parent):
        super().__init__(parent)
        self.cameras = cameras

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cameras)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 6

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ['번호', '카메라', '화질', '방향 조작', '사용', ''][section]
        if orientation == Qt.Orientation.Horizontal and section == 3 and role == Qt.ItemDataRole.ToolTipRole:
            return '카메라가 제공한 정보로 판단합니다.'
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        camera = self.cameras[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return camera['id']  # Only stable identifiers, never connection URLs.
        if role == Qt.ItemDataRole.DisplayRole:
            parent = self.parent()
            state = parent.direction_support(camera) if hasattr(parent, 'direction_support') else support_state(camera)
            return [f"{camera['number']:02}", camera_display_name(camera), camera['quality'],
                    DIRECTION_LABELS[state], '사용' if camera.get('enabled', True) else '사용 안 함', '⋯'][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 3:
            return '카메라가 제공한 정보로 판단합니다.'
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() != 1:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def refresh(self, cameras):
        self.beginResetModel()
        self.cameras = cameras
        self.endResetModel()


class CameraTable(QTableView):
    def currentRow(self):
        return self.currentIndex().row()


class CameraManager(QDialog):
    def __init__(self, cameras, parent=None, slots=None, layout_slots=None, layout=4,
                 *, verify_connection_info=None, commit_callback=None, statuses=None):
        super().__init__(parent)
        self.tips = HoverTips(self)
        self.settings_reset = False
        self.cameras = copy.deepcopy(cameras)
        self.support_control = DirectionControl(self, diagnostics_enabled=False)
        self.support_control.metadata_ready.connect(self.store_direction_support)
        self.support_control.lookup_changed.connect(self.refresh_direction_support)
        self._support_opened = False
        self._support_requested = set()
        self.finished.connect(lambda *_: self.support_control.shutdown())
        support_control = self.support_control
        self.destroyed.connect(lambda *_: support_control.shutdown())
        self.edit_layout = layout
        self.commit_callback = commit_callback
        host_config = getattr(parent, 'config', {})
        # Required disclosure is enforced per sensitive field, including old profiles.
        self.verify_connection_info = True
        self.split_orientation = host_config.get('split_orientation', 'horizontal')
        config = default_config()
        config.update(cameras=self.cameras, layout=layout, layout_slots=copy.deepcopy(layout_slots),
                      slots=list(slots) if slots is not None else [c['id'] for c in cameras[:4]])
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(layout)]
        self.assignment_changed = False
        self.setWindowTitle('카메라 관리')
        self.setStyleSheet(CAMERA_STYLE)
        self.resize(760, 500)
        self.setMinimumSize(700, 460)
        self.privacy = PrivacyController(self)
        self.buttons = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel('카메라 관리')
        title.setStyleSheet('font-size:18px;font-weight:600;')
        header.addWidget(title)
        header.addStretch()
        self.file_menu_button = QToolButton()
        self.file_menu_button.setIcon(icon('more'))
        self.file_menu_button.setToolTip('목록 메뉴')
        self.file_menu_button.setAccessibleName('목록 메뉴')
        self.tips.add(self.file_menu_button)
        self.file_menu_button.clicked.connect(self.file_menu)
        header.addWidget(self.file_menu_button)
        add = self.action_button('add', '카메라 추가', self.add_camera, 'add')
        add.setObjectName('primary')
        header.addWidget(add)
        root.addLayout(header)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.build_registry_tab()
        self.build_assignments_tab()
        self.tabs.currentChanged.connect(lambda *_: self.privacy.hide_all())
        self.feedback = Feedback(self)
        self.notice = self.feedback
        self.privacy.feedback.connect(self.show_notice)
        self.privacy.cleared.connect(self.feedback.clear_message)
        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet('color:#96a9c3;')
        footer.addWidget(self.count_label)
        footer.addStretch()
        self.dirty_label = QLabel()
        self.dirty_label.setStyleSheet('color:#d6c69f;font-size:11px;')
        footer.addWidget(self.dirty_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장')
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)
        self.refresh()
        self._baseline = self.snapshot()
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))

    def action_button(self, key, text, callback, symbol):
        button = QPushButton(text)
        button.setIcon(icon(symbol))
        button.clicked.connect(callback)
        self.buttons[key] = button
        return button

    def build_registry_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = CameraTable()
        self.model = CameraListModel(self.cameras, self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 40), (2, 42), (3, 84), (4, 68), (5, 28)):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.update_buttons())
        self.table.doubleClicked.connect(lambda index: self.edit_camera() if index.column() != 5 else None)
        self.table.clicked.connect(lambda index: self.row_menu(index) if index.column() == 5 else None)
        left_layout.addWidget(self.table, 1)
        self.empty_label = QLabel('등록된 카메라가 없습니다.', self.table.viewport())
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet('color:#96a9c3;padding:10px;')
        self.table.viewport().installEventFilter(self)
        order = QHBoxLayout()
        order.addWidget(self.action_button('up', '위로', lambda: self.move_camera(-1), 'up'))
        order.addWidget(self.action_button('down', '아래로', lambda: self.move_camera(1), 'down'))
        order.addStretch()
        left_layout.addLayout(order)
        splitter.addWidget(left)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumWidth(290)
        detail = QFrame()
        detail.setObjectName('detail')
        details = QVBoxLayout(detail)
        details.setContentsMargins(14, 12, 14, 12)
        details.setSpacing(8)
        self.detail_title = QLabel('카메라를 선택하세요')
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet('font-size:15px;font-weight:600;')
        details.addWidget(self.detail_title)
        self.details = {}
        self.detail_groups = []
        for key, label in [('host', '주소'), ('username', '아이디'), ('password', '비밀번호'),
                            ('url', 'RTSP 주소'), ('sd_url', 'RTSP 주소2 (SD)')]:
            container = QWidget()
            group = QVBoxLayout(container)
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(4)
            caption = QLabel(label)
            caption.setObjectName('fieldCaption')
            group.addWidget(caption)
            field = SensitiveField(self.privacy, label, required=key not in ('host', 'username'))
            self.details[key] = field
            group.addWidget(field)
            self.detail_groups.append(container)
            details.addWidget(container)
        details.addStretch()
        self.buttons['edit'] = QAction(icon('edit'), '카메라 수정', self)
        self.buttons['edit'].triggered.connect(self.edit_camera)
        self.buttons['enable'] = QAction(icon('camera'), '사용 안 함', self)
        self.buttons['enable'].triggered.connect(self.toggle_enabled)
        self.buttons['delete'] = QAction(icon('close'), '카메라 삭제', self)
        self.buttons['delete'].triggered.connect(self.delete_camera)
        detail_scroll.setWidget(detail)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([440, 330])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, '카메라 목록')

    def build_assignments_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel('화면 구성'))
        self.layout_choice = QComboBox()
        for count in (1, 2, 4):
            self.layout_choice.addItem(f'{count}분할', count)
        self.layout_choice.setCurrentIndex(self.layout_choice.findData(self.edit_layout))
        self.layout_choice.currentIndexChanged.connect(self.change_layout)
        row.addWidget(self.layout_choice)
        row.addStretch()
        layout.addLayout(row)
        info = QToolButton()
        info.setIcon(icon('info'))
        info.setToolTip('분할마다 표시할 카메라를 저장합니다.\n2분할 좌우·상하는 같은 설정을 사용합니다.\n사용 안 함으로 바꾸면 화면에서 빠지고, 다시 사용하면 빈 화면부터 채웁니다.')
        info.setAccessibleName('화면별 카메라 도움말')
        self.tips.add(info, click=True)
        row.addWidget(info)
        self.assignments = QGridLayout()
        self.screen_choices, self.screen_labels, self.screen_cards = [], [], []
        for index in range(4):
            card = QFrame(page)
            card.setObjectName('screenCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            label = QLabel(f'SCREEN {index + 1}')
            label.setStyleSheet('color:#90baff;font-size:12px;font-weight:600;')
            card_layout.addWidget(label)
            choice = QComboBox()
            choice.setMinimumContentsLength(12)
            choice.setToolTip(f'SCREEN {index + 1}에 표시할 카메라')
            choice.currentIndexChanged.connect(lambda _, i=index: self.assign_screen(i))
            card_layout.addWidget(choice)
            clear = QPushButton('화면 비우기')
            clear.clicked.connect(lambda _, i=index: self.clear_screen(i))
            card_layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
            card_layout.addStretch()
            self.screen_labels.append(label)
            self.screen_choices.append(choice)
            self.screen_cards.append(card)
        layout.addLayout(self.assignments, 1)
        self.tabs.addTab(page, '화면별 카메라')

    def snapshot(self):
        cameras = [{key: value for key, value in camera.items() if key != 'ptz'} for camera in self.cameras]
        return copy.deepcopy((cameras, self.layout_slots, self.verify_connection_info, self.settings_reset))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._support_opened:
            self._support_opened = True
            self.query_direction_support()

    def direction_support(self, camera):
        key = camera_key(camera)
        if key == self.support_control.active_lookup or key in self.support_control.lookups:
            return 'checking'
        return support_state(camera)

    def query_direction_support(self):
        if not self._support_opened or self.support_control.closed:
            return
        for camera in self.cameras:
            key = camera_key(camera)
            if eligible(camera) and key not in self._support_requested:
                self._support_requested.add(key)
                self.support_control.discover(camera, force=True)

    def refresh_direction_support(self):
        if hasattr(self, 'model') and self.cameras:
            self.model.dataChanged.emit(self.model.index(0, 3), self.model.index(len(self.cameras) - 1, 3),
                                        [Qt.ItemDataRole.DisplayRole])

    def store_direction_support(self, key, info):
        camera = next((camera for camera in self.cameras if camera_key(camera) == key), None)
        if camera is not None:
            checked = validated_control(info, camera)
            if checked:
                camera['ptz'] = checked
                self.refresh_direction_support()

    def selected_camera(self):
        row = self.table.currentRow()
        return self.cameras[row] if 0 <= row < len(self.cameras) else None

    def refresh(self, selected=0):
        config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh_screen_choices()
        self.model.refresh(self.cameras)
        if self.cameras:
            self.table.selectRow(max(0, min(selected, len(self.cameras) - 1)))
        self.filter_rows()
        self.query_direction_support()

    def refresh_screen_choices(self):
        for card in self.screen_cards:
            self.assignments.removeWidget(card)
        columns = 1 if self.edit_layout == 1 or (self.edit_layout == 2 and self.split_orientation == 'vertical') else 2
        for index, choice in enumerate(self.screen_choices):
            choice.blockSignals(True)
            choice.clear()
            choice.addItem('없음', None)
            for camera in self.cameras:
                if camera.get('enabled', True):
                    choice.addItem(f"{camera['number']}. {camera_display_name(camera)}", camera['id'])
                    if camera.get('connection_locked'):
                        choice.model().item(choice.count() - 1).setEnabled(False)
            choice.setCurrentIndex(max(0, choice.findData(self.slots[index])))
            choice.blockSignals(False)
            visible = index < self.edit_layout
            self.screen_cards[index].setVisible(visible)
            if visible:
                self.assignments.addWidget(self.screen_cards[index], index // columns, index % columns)

    def change_layout(self):
        self.privacy.hide_all()
        self.edit_layout = self.layout_choice.currentData()
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh(max(0, self.table.currentRow()))

    def filter_rows(self):
        used = sum(c.get('enabled', True) for c in self.cameras)
        if hasattr(self, 'count_label'):
            self.count_label.setText(f'등록 {len(self.cameras)}대 · 사용 {used}대')
        self.empty_label.setGeometry(self.table.viewport().rect())
        self.empty_label.setVisible(not self.cameras)
        self.update_buttons()

    def eventFilter(self, watched, event):
        if hasattr(self, 'table') and watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self.empty_label.setGeometry(self.table.viewport().rect())
        return super().eventFilter(watched, event)

    def update_buttons(self):
        if not hasattr(self, 'details') or 'edit' not in self.buttons:
            return
        row = self.table.currentRow()
        camera = self.selected_camera()
        valid = camera is not None
        for container in self.detail_groups:
            container.setVisible(valid)
        for key in ('edit', 'enable', 'delete'):
            self.buttons[key].setEnabled(valid)
        locked = bool(camera and camera.get('connection_locked'))
        self.buttons['edit'].setEnabled(valid)
        self.buttons['edit'].setText('연결 정보 다시 입력' if locked else '카메라 수정')
        self.buttons['up'].setEnabled(row > 0)
        self.buttons['down'].setEnabled(0 <= row < len(self.cameras) - 1)
        for key in ('up', 'down'):
            self.buttons[key].setToolTip('목록 순서 변경')
        if hasattr(self, '_baseline'):
            self.dirty_label.setText('저장하지 않음' if self.snapshot() != self._baseline else '')
        self.privacy.hide_all()
        if not camera:
            self.detail_title.setText('카메라 정보')
            for field in self.details.values():
                field.set_value('')
            return
        self.buttons['enable'].setText('사용 안 함' if camera.get('enabled', True) else '사용')
        self.detail_title.setText(f"CAMERA {camera['number']:02} · {camera_display_name(camera)}")
        try:
            p = urlsplit(camera['url'])
            host = ('[' + p.hostname + ']' if p.hostname and ':' in p.hostname else p.hostname or '')
            host = f'{host}:{p.port or 554}' if host else ''
            values = dict(host=host, username=unquote(p.username or ''), password=unquote(p.password or ''),
                          url=camera['url'], sd_url=camera_url(dict(camera, quality='SD')) if supports_quality(camera) else '')
        except ValueError:
            values = {}
        for key, field in self.details.items():
            field.set_value(values.get(key, ''))

    def show_notice(self, text, anchor=None):
        owner = QApplication.activeModalWidget()
        if owner is not None and owner is not self and self.isAncestorOf(owner):
            # Export/authentication feedback belongs to the still-open delete
            # confirmation, rather than appearing hidden behind it.
            if not hasattr(owner, '_camfloat_feedback'):
                owner._camfloat_feedback = Feedback(owner)
                self.privacy.cleared.connect(owner._camfloat_feedback.clear_message)
            owner._camfloat_feedback.show_message(text)
        else:
            self.feedback.show_message(text, anchor)

    def add_camera(self):
        number = max([c.get('number', 0) for c in self.cameras] + [0]) + 1
        self.privacy.hide_all()
        dialog = CameraEditor(parent=self, others=self.cameras, number=number)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cameras.append(dialog.camera)
            config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
            fill_empty_slots(config, [dialog.camera['id']])
            self.layout_slots = config['layout_slots']
            self.refresh(len(self.cameras) - 1)
        dialog.deleteLater()

    def edit_camera(self):
        camera = self.selected_camera()
        if not camera:
            return
        identifier = camera['id']
        def edit():
            if self.selected_camera() is None or self.selected_camera()['id'] != identifier:
                return
            row = self.table.currentRow()
            locked = self.cameras[row].get('connection_locked', False)
            if locked and not confirm_action(self, '카메라 정보 다시 입력',
                    '저장된 정보를 읽을 수 없습니다. 다시 입력할까요?', '다시 입력'):
                return
            self.privacy.hide_all()
            dialog = CameraEditor(None if locked else self.cameras[row], self,
                                  others=self.cameras, number=self.cameras[row]['number'])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if locked:
                    for key in ('id', 'number', 'volume', 'muted', 'enabled'):
                        dialog.camera[key] = self.cameras[row][key]
                self.cameras[row] = dialog.camera
                self.refresh(row)
            dialog.deleteLater()
        self.privacy.authorize(edit)

    def toggle_enabled(self):
        camera = self.selected_camera()
        if camera is None:
            return
        row = self.table.currentRow()
        camera['enabled'] = not camera.get('enabled', True)
        config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
        ensure_layout_slots(config)
        if camera['enabled']:
            fill_empty_slots(config, [camera['id']])
        self.layout_slots = config['layout_slots']
        self.assignment_changed = True
        self.refresh(row)

    def assign_screen(self, index):
        identifier = self.screen_choices[index].currentData()
        if identifier is not None and identifier in self.slots:
            other = self.slots.index(identifier)
            self.slots[other], self.slots[index] = self.slots[index], self.slots[other]
        else:
            self.slots[index] = identifier
        self.assignment_changed = True
        self.refresh(max(0, self.table.currentRow()))

    def clear_screen(self, index):
        self.screen_choices[index].setCurrentIndex(0)

    def delete_camera(self):
        camera = self.selected_camera()
        if camera is None:
            return
        row = self.table.currentRow()
        box = QMessageBox(self)
        box.setWindowTitle('카메라 삭제')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f'‘{camera_display_name(camera)}’ 카메라를 삭제할까요?')
        remove = box.addButton('삭제', QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton('취소', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is remove:
            self.cameras.pop(row)
            self.refresh(row)

    def move_camera(self, delta):
        row = self.table.currentRow()
        target = row + delta
        if 0 <= row < len(self.cameras) and 0 <= target < len(self.cameras):
            self.cameras[row], self.cameras[target] = self.cameras[target], self.cameras[row]
            self.refresh(target)

    def build_row_menu(self):
        if not self.selected_camera():
            return None
        menu = QMenu(self)
        menu.addAction(self.buttons['edit'])
        menu.addAction(self.buttons['enable'])
        menu.addSeparator()
        menu.addAction(self.buttons['delete'])
        return menu

    def row_menu(self, index):
        menu = self.build_row_menu()
        if menu is None:
            return
        menu.exec(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))
        menu.deleteLater()

    def file_menu(self):
        self.tips.clear()
        menu = QMenu(self)
        menu.addAction('목록 불러오기…', self.import_file)
        menu.addAction('목록 내보내기…', self.export_file).setEnabled(bool(self.cameras))
        menu.addSeparator()
        menu.addAction('카메라 전체 삭제…', self.delete_all).setEnabled(bool(self.cameras))
        menu.addAction('설정 초기화…', self.reset_preferences)
        menu.exec(self.file_menu_button.mapToGlobal(self.file_menu_button.rect().bottomLeft()))
        menu.deleteLater()

    def delete_all(self):
        self.privacy.hide_all()
        self.tips.clear()
        box = QDialog(self)
        box.setWindowTitle('카메라 전체 삭제')
        content = QVBoxLayout(box)
        content.setContentsMargins(20, 20, 20, 16)
        message = QLabel('등록된 카메라가 모두 삭제됩니다.\n필요하면 먼저 내보내기로 백업하세요.')
        message.setTextFormat(Qt.TextFormat.PlainText)
        content.addWidget(message)
        buttons = QHBoxLayout()
        backup = QPushButton('내보내기…', box)
        cancel = QPushButton('취소', box)
        delete = QPushButton('전체 삭제', box)
        buttons.addWidget(backup)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(delete)
        for button in (backup, cancel, delete):
            button.setAutoDefault(False)
        cancel.setDefault(True)
        cancel.setFocus()
        backup.clicked.connect(self.export_file)
        self.privacy.busy_changed.connect(backup.setDisabled)
        delete.clicked.connect(box.accept)
        cancel.clicked.connect(box.reject)
        content.addLayout(buttons)
        result = box.exec()
        self.privacy.hide_all()
        if result == QDialog.DialogCode.Accepted:
            self.cameras.clear()
            self.layout_slots = {str(n): [None] * 4 for n in (1, 2, 4)}
            self.refresh()
            self.show_notice('저장하면 모든 카메라가 삭제됩니다.')
        box.deleteLater()

    def reset_preferences(self):
        self.privacy.hide_all()
        if not confirm_action(self, '설정 초기화',
                '카메라 목록을 제외한 모든 설정을 처음 상태로 되돌립니다.', '초기화'):
            return
        config = reset_settings(self.cameras)
        self.cameras = config['cameras']
        self.layout_slots = config['layout_slots']
        self.edit_layout = 1
        self.split_orientation = 'horizontal'
        self.settings_reset = True
        self.layout_choice.setCurrentIndex(self.layout_choice.findData(1))
        self.refresh()
        self.show_notice('저장하면 설정이 초기화됩니다.')

    def export_file(self):
        if not self.cameras:
            return
        self.privacy.hide_all()
        snapshot = copy.deepcopy(self.cameras)
        def save():
            try:
                blob = encode(snapshot)
            except ValueError as error:
                self.show_notice(str(error))
                return
            parent = QApplication.activeModalWidget()
            parent = parent if parent is not None and self.isAncestorOf(parent) else self
            path, _ = QFileDialog.getSaveFileName(parent, '목록 내보내기', '내 카메라.camfloat', 'CamFloat 카메라 목록 (*.camfloat)')
            if not path:
                return
            if not path.lower().endswith('.camfloat'):
                path += '.camfloat'
            target = QSaveFile(path)
            target.setDirectWriteFallback(False)
            if not target.open(QIODevice.OpenModeFlag.WriteOnly):
                self.show_notice('파일을 저장하지 못했습니다. 다른 위치를 선택하세요.')
                return
            if target.write(blob) != len(blob) or not target.commit():
                target.cancelWriting()
                self.show_notice('파일을 저장하지 못했습니다. 다시 시도하세요.')
                return
            self.show_notice('목록을 내보냈습니다.')
        self.privacy.authorize(save, required=True, anchor=self.file_menu_button)

    def import_file(self):
        self.privacy.hide_all()
        path, _ = QFileDialog.getOpenFileName(self, '목록 불러오기', '', 'CamFloat 카메라 목록 (*.camfloat)')
        if not path:
            return
        try:
            candidates, duplicates = import_candidates(read_file(path), self.cameras)
        except (OSError, ValueError) as error:
            self.show_notice(str(error) if isinstance(error, ValueError) else '파일을 읽을 수 없습니다. 다른 파일을 선택하세요.')
            return
        preview = ImportPreview(candidates, duplicates, self)
        if preview.exec() == QDialog.DialogCode.Accepted:
            selected = preview.selected_cameras()
            if selected:
                self.cameras.extend(selected)
                config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
                fill_empty_slots(config, [c['id'] for c in selected if c['enabled']])
                self.layout_slots = config['layout_slots']
                self.refresh(len(self.cameras) - len(selected))
        preview.deleteLater()

    def accept(self):
        self.privacy.hide_all()
        options = {'reset': True} if self.settings_reset else {}
        if self.commit_callback and not self.commit_callback(self.cameras, self.layout_slots, self.verify_connection_info, **options):
            self.show_notice('저장하지 못했습니다. 다시 시도하세요.')
            return
        super().accept()

    def reject(self):
        if hasattr(self, '_baseline') and self.snapshot() != self._baseline:
            box = QMessageBox(self)
            box.setWindowTitle('저장하지 않은 변경')
            box.setText('변경한 카메라 설정을 저장할까요?')
            save = box.addButton('저장', QMessageBox.ButtonRole.AcceptRole)
            discard = box.addButton('저장 안 함', QMessageBox.ButtonRole.DestructiveRole)
            box.addButton('계속 편집', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is save:
                self.accept()
                return
            if box.clickedButton() is not discard:
                return
        super().reject()
