"""Management entry and native message regression; no live camera connections."""
import ctypes
import sys
import unittest
from ctypes import wintypes
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

import test_app as fixtures
from camera_model import new_camera
from dialogs import CameraEditor, CameraManager


class ManagementEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.errors = []
        self.previous_hook = sys.excepthook
        sys.excepthook = lambda kind, error, trace: self.errors.append((kind, str(error)))
        self.camera = new_camera('테스트 카메라', 'rtsp://viewer:example%21@127.0.0.1:8554/onvif1')
        self.camera['number'] = 1

    def tearDown(self):
        self.app.processEvents()
        sys.excepthook = self.previous_hook
        self.assertEqual(self.errors, [])

    def test_manager_repeated_entry_and_filter_cleanup(self):
        for _ in range(4):
            manager = CameraManager([self.camera], layout=1)
            watch = manager.privacy.lock_filter
            self.assertFalse(watch.installed)
            manager.show()
            QTest.qWait(35)
            self.assertTrue(manager.isVisible())
            self.assertTrue(watch.installed)
            manager.tabs.setCurrentIndex(1)
            manager.tabs.setCurrentIndex(0)
            manager.done(QDialog.DialogCode.Rejected)
            self.assertFalse(watch.installed)
            self.assertFalse(watch.registered)
            manager.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_session_lock_uses_ctypes_message_field_and_conceals(self):
        manager = CameraManager([self.camera], layout=1)
        manager.show()
        QTest.qWait(35)
        field = manager.details['password']
        field.reveal()
        self.assertTrue(field.revealed)
        message = wintypes.MSG()
        message.hWnd = manager.privacy.lock_filter.hwnd
        message.message = 0x02B1
        message.wParam = 7
        self.assertEqual(manager.privacy.lock_filter.nativeEventFilter(
            b'windows_generic_MSG', ctypes.addressof(message)), (False, 0))
        self.assertFalse(field.revealed)
        manager.done(QDialog.DialogCode.Rejected)
        manager.deleteLater()

    def test_editor_entry_and_unfinished_dialog_destruction_cleanup(self):
        editor = CameraEditor(self.camera)
        editor.show()
        QTest.qWait(35)
        watch = editor.privacy.lock_filter
        self.assertTrue(watch.installed)
        editor.deleteLater()  # Destruction must clean up even without finished.
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(watch.installed)
        self.assertFalse(watch.registered)

    def test_registry_details_and_actions_are_compact(self):
        manager = CameraManager([self.camera], layout=1, statuses={self.camera['id']: '재생 중'})
        for key in ('host', 'username'):
            self.assertFalse(manager.details[key].public)
            self.assertFalse(manager.details[key].required)
            self.assertFalse(manager.details[key].revealed)
            self.assertFalse(manager.details[key].eye.isHidden())
        manager.details['host'].toggle()
        manager.details['username'].toggle()
        self.assertEqual(manager.details['host'].edit.text(), '127.0.0.1:8554')
        self.assertEqual(manager.details['username'].edit.text(), 'viewer')
        for key in ('password', 'url', 'sd_url'):
            self.assertTrue(manager.details[key].required)
            self.assertFalse(manager.details[key].revealed)
        self.assertEqual(manager.details['url'].label, 'RTSP 주소')
        self.assertEqual(manager.details['sd_url'].label, 'RTSP 주소2 (SD)')
        labels = [item.text() for item in manager.findChildren(QLabel)]
        self.assertNotIn('재생 중', labels)
        self.assertFalse(any('배정된 SCREEN' in label for label in labels))
        buttons = [item.text() for item in manager.findChildren(QPushButton)]
        for removed in ('수정', '사용 안 함', 'RTSP 주소 복사'):
            self.assertNotIn(removed, buttons)
        menu = manager.build_row_menu()
        actions = [action.text() for action in menu.actions()]
        self.assertIn('카메라 수정', actions)
        self.assertIn('사용 안 함', actions)
        self.assertFalse(any('복사' in action for action in actions))
        menu.deleteLater()
        manager.deleteLater()

    def test_empty_and_partial_url_can_return_to_simple_without_loss(self):
        editor = CameraEditor()
        editor.mode.setCurrentIndex(1)
        editor.mode.setCurrentIndex(0)
        self.assertEqual(editor.pages.currentIndex(), 0)
        self.assertEqual(editor.mode.currentIndex(), 0)
        editor.mode.setCurrentIndex(1)
        editor.full_url.setText('rtsp://unfinished')
        # Explicitly invalid port makes this an incomplete, unparseable draft.
        partial = 'rtsp://viewer:typed@localhost:not-a-port/path'
        editor.full_url.setText(partial)
        editor.mode.setCurrentIndex(0)
        self.assertEqual(editor.pages.currentIndex(), 0)
        editor.mode.setCurrentIndex(1)
        self.assertEqual(editor.full_url.text(), partial)
        editor.mode.setCurrentIndex(0)
        editor.host.setText('127.0.0.1')
        editor.mode.setCurrentIndex(1)
        self.assertIn('127.0.0.1', editor.full_url.text())
        self.assertNotIn('추가하고 계속', [b.text() for b in editor.findChildren(QPushButton)])
        editor.deleteLater()

    def test_sd_path_uses_hd_authority_and_preserves_encoded_password(self):
        editor = CameraEditor(self.camera)
        editor.sd_url.setText('/onvif2?channel=2')
        result = editor.collect()
        self.assertEqual(result['sd_url'], 'rtsp://viewer:example%21@127.0.0.1:8554/onvif2?channel=2')
        editor.mode.setCurrentIndex(1)
        editor.mode.setCurrentIndex(0)
        self.assertEqual(editor.collect()['url'], self.camera['url'])
        editor.sd_url.setText('rtsp://other:other@127.0.0.1:8555/custom')
        self.assertEqual(editor.collect()['sd_url'], editor.sd_url.text())
        editor.deleteLater()

    def test_editor_secret_fields_and_all_copy_paths_require_verification(self):
        manager = CameraManager([self.camera], verify_connection_info=False)
        editor = CameraEditor(self.camera, manager, privacy=manager.privacy)
        with patch.object(manager.privacy, 'authorize') as authorize:
            for key in ('password', 'full_url', 'sd_url'):
                editor.fields[key].toggle()
                self.assertTrue(authorize.call_args.kwargs['required'])
                self.assertFalse(editor.fields[key].revealed)
            manager.details['password'].toggle()
            self.assertTrue(authorize.call_args.kwargs['required'])
            manager.details['url'].copy_value()
            self.assertTrue(authorize.call_args.kwargs['required'])
            field = manager.details['password']
            field.reveal()  # Simulate a prior successful verification.
            field.edit.selectAll()
            field.copy_selection()
            self.assertTrue(authorize.call_args.kwargs['required'])
        editor.deleteLater()
        manager.deleteLater()

    def test_empty_fields_have_no_copy_or_reveal_action(self):
        editor = CameraEditor()
        for key in ('password', 'full_url', 'sd_url'):
            self.assertFalse(editor.fields[key].copy_button.isEnabled())
            self.assertFalse(editor.fields[key].eye.isEnabled())
        editor.password.setText('typed')
        self.assertTrue(editor.fields['password'].copy_button.isEnabled())
        self.assertTrue(editor.fields['password'].eye.isEnabled())
        editor.deleteLater()

    def test_verification_failure_success_and_expiry(self):
        class FakeConsent(QObject):
            finished = Signal(bool, str)
            def start(self, hwnd):
                pass
            def cancel(self):
                self.finished.emit(False, '취소')

        manager = CameraManager([self.camera], verify_connection_info=False)
        manager.show()
        QTest.qWait(35)
        field = manager.details['password']
        with patch('privacy.ConsentRequest', FakeConsent), patch('privacy.app_is_foreground', return_value=True):
            field.toggle()
            self.assertIsNotNone(manager.privacy.request)
            self.assertFalse(field.revealed)
            manager.privacy.request.finished.emit(False, '인증 실패')
            QTest.qWait(180)
            self.assertFalse(field.revealed)
            field.toggle()
            manager.privacy.request.finished.emit(True, '')
            QTest.qWait(180)
            self.assertTrue(field.revealed)
            self.assertEqual(field.edit.text(), 'example!')
            manager.privacy.grant_timer.timeout.emit()
            self.assertFalse(field.revealed)
            self.assertEqual(field.edit.text(), '••••••••')
            self.assertEqual(manager.details['host'].edit.text(), '••••••••')
        manager.done(QDialog.DialogCode.Rejected)
        manager.deleteLater()

    def test_inline_copy_of_hidden_address_needs_no_auth_and_keeps_hidden(self):
        manager = CameraManager([self.camera])
        manager.show()
        QTest.qWait(35)
        with patch('privacy.secure_clipboard') as clipboard, patch('privacy.ConsentRequest') as consent:
            for key, expected in [('host', '127.0.0.1:8554'), ('username', 'viewer')]:
                field = manager.details[key]
                self.assertIs(field.copy_button.parentWidget(), field.edit)
                self.assertTrue(field.edit.rect().contains(field.copy_button.geometry()))
                self.assertTrue(field.edit.rect().contains(field.eye.geometry()))
                field.copy_button.click()
                clipboard.return_value.copy.assert_called_with(expected)
                self.assertFalse(field.revealed)
            consent.assert_not_called()
        manager.done(QDialog.DialogCode.Rejected)
        manager.deleteLater()

    def test_secret_copy_waits_for_auth_and_dialogs_use_compact_sizes(self):
        manager = CameraManager([self.camera])
        editor = CameraEditor(self.camera, manager, privacy=manager.privacy)
        self.assertLessEqual(manager.width(), 820)
        self.assertLessEqual(manager.height(), 540)
        self.assertLessEqual(editor.width(), 520)
        simple_height = editor.height()
        editor.mode.setCurrentIndex(1)
        self.assertLess(editor.height(), simple_height)
        editor.advanced.setChecked(True)
        self.assertGreater(editor.height(), simple_height)
        with patch('privacy.secure_clipboard') as clipboard, patch.object(manager.privacy, 'authorize') as authorize:
            for field in (manager.details['password'], manager.details['url'], editor.fields['password'], editor.fields['full_url']):
                field.copy_button.click()
                self.assertTrue(authorize.call_args.kwargs['required'])
                clipboard.return_value.copy.assert_not_called()
                authorize.call_args.args[0]()  # Simulate a successful verification callback.
                clipboard.return_value.copy.assert_called_with(field.value())
                clipboard.return_value.copy.reset_mock()
                self.assertFalse(field.revealed)
        editor.deleteLater()
        manager.deleteLater()


class PlayerManagementEntry(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_player_management_action_opens_modal(self):
        opened = []
        def close_manager():
            manager = self.app.activeModalWidget()
            opened.append(isinstance(manager, CameraManager) and manager.isVisible())
            if isinstance(manager, QDialog):
                manager.reject()
        QTimer.singleShot(120, close_manager)
        self.window.manage_cameras()
        self.assertEqual(opened, [True])
        self.assertEqual(self.window.modal_depth, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
