import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import test_app as fixtures
from camfloat.camera_model import new_camera
from camfloat.camera_manager import CameraManager
from camfloat.camera_editor import CameraEditor
from camfloat.camera_archive import decode, encode
from camfloat.camera_transfer import ImportPreview


class NoPromptConsent(QObject):
    finished = Signal(bool, str)
    def start(self, hwnd):
        pass
    def cancel(self):
        self.finished.emit(False, '')


class DialogUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.camera = new_camera('테스트', 'rtsp://viewer:synthetic%21@127.0.0.1:8554/onvif1')
        self.camera['number'] = 1
        self.manager = CameraManager([self.camera])
        self.manager.show()
        QTest.qWait(25)
        self.consent_patch = patch('camfloat.privacy.ConsentRequest', NoPromptConsent)
        self.consent_patch.start()

    def tearDown(self):
        self.manager.done(QDialog.DialogCode.Rejected)
        self.manager.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.consent_patch.stop()

    def test_feedback_never_reflows_and_clears_between_tabs_and_cameras(self):
        self.assertFalse(hasattr(self.manager, 'search'))
        self.assertFalse(hasattr(self.manager, 'filter'))
        geometry = self.manager.table.geometry()
        field_geometry = self.manager.details['password'].geometry()
        size = self.manager.size()
        self.manager.show_notice('본인 확인을 다시 시도하세요.')
        self.app.processEvents()
        self.assertTrue(self.manager.notice.isVisible())
        self.assertEqual(self.manager.table.geometry(), geometry)
        self.assertEqual(self.manager.details['password'].geometry(), field_geometry)
        self.assertEqual(self.manager.size(), size)
        self.manager.tabs.setCurrentIndex(1)
        self.assertFalse(self.manager.notice.isVisible())
        self.manager.tabs.setCurrentIndex(0)
        self.manager.show_notice('이전 안내')
        self.manager.update_buttons()
        self.assertFalse(self.manager.notice.isVisible())

    def test_switching_tabs_cancels_auth_and_stale_failure_does_not_appear(self):
        self.manager.details['password'].toggle()
        self.assertIsNotNone(self.manager.privacy.request)
        self.assertFalse(self.manager.details['password'].eye.isEnabled())
        self.manager.privacy.request.finished.emit(False, '본인 확인을 다시 시도하세요.')
        self.manager.tabs.setCurrentIndex(1)
        QTest.qWait(180)
        self.assertFalse(self.manager.notice.isVisible())
        self.assertIsNone(self.manager.privacy.request)

    def test_editor_feedback_and_auth_are_independent(self):
        editor = CameraEditor(self.camera, self.manager)
        editor.show()
        QTest.qWait(20)
        self.assertIsNot(editor.privacy, self.manager.privacy)
        editor.show_error('입력값을 확인하세요.')
        self.assertTrue(editor.error.isVisible())
        self.assertFalse(self.manager.notice.isVisible())
        editor.mode.setCurrentIndex(1)
        self.assertFalse(editor.fields['path'].isEnabled())
        editor.check.setText('연결됨')
        editor.input_changed()
        self.assertEqual(editor.check.text(), '연결 확인')
        self.assertFalse(editor.error.isVisible())
        editor.done(QDialog.DialogCode.Rejected)
        editor.deleteLater()

    def test_export_requires_auth_then_writes_encrypted_file_without_password_prompt(self):
        before = self.manager.snapshot()
        with tempfile.TemporaryDirectory() as folder, patch.object(self.manager.privacy, 'authorize') as auth:
            path = Path(folder) / 'cameras.camfloat'
            with patch('camfloat.camera_manager.QFileDialog.getSaveFileName', return_value=(str(path), '')) as picker:
                self.manager.export_file()
                self.assertTrue(auth.call_args.kwargs['required'])
                picker.assert_not_called()
                self.assertFalse(path.exists())
                auth.call_args.args[0]()
            self.assertEqual(decode(path.read_bytes())[0]['url'], self.camera['url'])
        self.assertEqual(self.manager.snapshot(), before)

    def test_preview_is_optional_and_displays_no_connection_details(self):
        other = dict(self.camera, number=2, id='new')
        preview = ImportPreview([other], 1, self.manager)
        for row in range(preview.table.rowCount()):
            for col in range(preview.table.columnCount()):
                self.assertNotIn('127.0.0.1', preview.table.item(row, col).text())
                self.assertNotIn('synthetic', preview.table.item(row, col).text())
        self.assertEqual(len(preview.selected_cameras()), 1)
        preview.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(preview.selected_cameras())
        self.assertFalse(preview.add.isEnabled())
        preview.deleteLater()

    def test_import_cancel_and_append_preserve_existing_cameras_and_skip_disabled_slots(self):
        original = copy.deepcopy(self.manager.cameras)
        new = new_camera('다른 카메라', 'rtsp://viewer:test@127.0.0.2:8554/onvif1')
        new['enabled'] = False
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'import.camfloat'
            path.write_bytes(encode([self.camera, new]))
            with patch('camfloat.camera_manager.QFileDialog.getOpenFileName', return_value=(str(path), '')), patch('camfloat.camera_manager.ImportPreview') as Preview:
                preview = Preview.return_value
                preview.exec.return_value = QDialog.DialogCode.Rejected
                self.manager.import_file()
                self.assertEqual(self.manager.cameras, original)
                preview.exec.return_value = QDialog.DialogCode.Accepted
                preview.selected_cameras.side_effect = lambda: Preview.call_args.args[0]
                self.manager.import_file()
                self.assertEqual(len(self.manager.cameras), 2)
                self.assertEqual(self.manager.cameras[0], original[0])
                added = self.manager.cameras[-1]
                self.assertNotEqual(added['id'], original[0]['id'])
                for slots in self.manager.layout_slots.values():
                    self.assertNotIn(added['id'], slots)
                self.assertEqual(self.manager.dirty_label.text(), '저장하지 않음')

    def test_delete_confirmation_is_plain_text_and_cancel_preserves_list(self):
        self.manager.cameras[0]['name'] = '<b>카메라</b>'
        def answer(label):
            box = self.app.activeModalWidget()
            self.assertIsInstance(box, QMessageBox)
            self.assertEqual(box.textFormat(), Qt.TextFormat.PlainText)
            self.assertIn('<b>카메라</b>', box.text())
            next(button for button in box.buttons() if button.text() == label).click()
        QTimer.singleShot(40, lambda: answer('취소'))
        self.manager.delete_camera()
        self.assertEqual(len(self.manager.cameras), 1)
        QTimer.singleShot(40, lambda: answer('삭제'))
        self.manager.delete_camera()
        self.assertEqual(self.manager.cameras, [])
        self.assertTrue(all(group.isHidden() for group in self.manager.detail_groups))


class PlayerUI(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_background_selection_clears_but_owned_dialog_keeps_it(self):
        with patch.object(self.window, 'app_is_foreground', return_value=False):
            self.window.select_slot(0)
            self.window.clear_background_selection()
            self.assertIsNone(self.window.selected)
            self.window.select_slot(1)
            self.window.modal_depth = 1
            self.window.clear_background_selection()
            self.assertEqual(self.window.selected, 1)
            self.window.modal_depth = 0

    def test_tooltips_show_for_unselected_screen_and_toolbar(self):
        self.window.select_slot(0)
        overlay = self.window.tiles[1].overlay
        overlay.reveal_controls()
        overlay.bar.layout().activate()
        self.app.processEvents()
        button = overlay.choose
        # Simulate hover without moving the user's mouse or depending on an unlocked desktop.
        with patch('camfloat.hover_tips.QCursor.pos', return_value=button.mapToGlobal(button.rect().center())):
            overlay.tips.eventFilter(button, QEvent(QEvent.Type.Enter))
            QTest.qWait(700)
            self.assertTrue(overlay.tips.bubble.isVisible())
            self.assertEqual(overlay.tips.bubble.text(), button.toolTip())
            self.assertEqual(self.window.selected, 0)
        overlay.tips.clear()
        self.window.chrome.reveal()
        self.window.chrome.panel.layout().activate()
        self.app.processEvents()
        button = self.window.chrome.manager
        with patch('camfloat.hover_tips.QCursor.pos', return_value=button.mapToGlobal(button.rect().center())):
            self.window.chrome.tips.eventFilter(button, QEvent(QEvent.Type.Enter))
            QTest.qWait(700)
            self.assertTrue(self.window.chrome.tips.bubble.isVisible())
            self.assertEqual(self.window.chrome.tips.bubble.text(), button.toolTip())
        self.window.chrome.tips.clear()
