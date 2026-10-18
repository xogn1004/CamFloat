"""Management entry and native message regression; no live camera connections."""
import ctypes
import sys
import unittest
from ctypes import wintypes

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

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
        field = manager.details['host']
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
