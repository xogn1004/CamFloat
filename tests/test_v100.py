import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QToolButton

import test_app as fixtures
from camera_model import default_config, normalize, new_camera, reset_settings
from camera_manager import CameraManager
from camera_editor import CameraEditor


class Defaults(unittest.TestCase):
    def test_new_defaults_and_existing_settings(self):
        for config in (default_config(), normalize({})):
            self.assertFalse(config['always_on_top'])
            self.assertEqual(config['opacity'], 80)
        existing = normalize(dict(always_on_top=True, opacity=45))
        self.assertTrue(existing['always_on_top'])
        self.assertEqual(existing['opacity'], 45)

    def test_reset_keeps_registry_and_resets_audio_assignments(self):
        cameras = [new_camera('거실', 'rtsp://user:test@127.0.0.1/onvif1'),
                   new_camera('현관', 'rtsp://user:test@127.0.0.2/onvif1')]
        cameras[0].update(volume=0, muted=True, quality='SD')
        cameras[1]['enabled'] = False
        original = copy.deepcopy(cameras)
        result = reset_settings(cameras)
        self.assertEqual(cameras, original)
        self.assertEqual(result['cameras'][0]['id'], cameras[0]['id'])
        self.assertEqual(result['cameras'][0]['url'], cameras[0]['url'])
        self.assertEqual(result['cameras'][0]['volume'], 100)
        self.assertFalse(result['cameras'][0]['muted'])
        self.assertFalse(result['cameras'][1]['enabled'])
        for slots in result['layout_slots'].values():
            self.assertEqual(slots[0], cameras[0]['id'])
            self.assertNotIn(cameras[1]['id'], slots)


class Dialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.camera = new_camera('테스트', 'rtsp://user:test@127.0.0.1/onvif1')
        self.camera['number'] = 1
        self.manager = CameraManager([self.camera])
        self.manager.show()
        QTest.qWait(25)

    def tearDown(self):
        self.manager.done(QDialog.DialogCode.Rejected)
        self.manager.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_info_click_repeatedly_displays_final_geometry(self):
        editor = CameraEditor(parent=self.manager)
        editor.show()
        self.manager.tabs.setCurrentIndex(1)
        for owner, label in ((self.manager, '화면별 카메라 도움말'), (editor, '카메라 입력 도움말')):
            button = next(b for b in owner.findChildren(QToolButton) if b.accessibleName() == label)
            for _ in range(2):
                button.click()
                self.app.processEvents()
                self.assertTrue(owner.tips.bubble.isVisible())
                geometry = owner.tips.bubble.geometry()
                QTest.qWait(50)
                self.assertEqual(owner.tips.bubble.geometry(), geometry)
                self.assertEqual(owner.tips.bubble.text(), button.toolTip())
            owner.tips.clear()
        editor.done(QDialog.DialogCode.Rejected)
        editor.deleteLater()

    def test_compact_manager_fields_fit(self):
        self.assertEqual(self.manager.width(), 760)
        self.assertEqual(self.manager.height(), 500)
        for group in self.manager.detail_groups:
            self.assertTrue(group.isVisible())
            self.assertGreaterEqual(group.width(), 240)

    def test_reset_is_draft_cancelable_and_callback_only_on_save(self):
        before = self.manager.snapshot()
        with patch('camera_manager.confirm_action', return_value=False):
            self.manager.reset_preferences()
        self.assertEqual(before, self.manager.snapshot())
        with patch('camera_manager.confirm_action', return_value=True):
            self.manager.reset_preferences()
        self.assertTrue(self.manager.settings_reset)
        self.assertEqual(len(self.manager.cameras), 1)
        self.assertEqual(self.manager.edit_layout, 1)
        calls = []
        self.manager.commit_callback = lambda *a, **k: calls.append((a, k)) or False
        self.manager.accept()
        self.assertTrue(calls[0][1]['reset'])
        self.assertTrue(self.manager.isVisible())

    def test_delete_confirmation_export_stays_open_and_cancel_preserves(self):
        before = self.manager.snapshot()
        results = []
        def operate():
            box = self.app.activeModalWidget()
            buttons = box.findChildren(QPushButton)
            backup = next(b for b in buttons if b.text() == '내보내기…')
            cancel = next(b for b in buttons if b.text() == '취소')
            results.append(cancel.isDefault())
            backup.click()
            results.append(box.isVisible())
            cancel.click()
        with patch.object(self.manager, 'export_file') as export:
            QTimer.singleShot(25, operate)
            self.manager.delete_all()
            export.assert_called_once()
        self.assertEqual(results, [True, True])
        self.assertEqual(before, self.manager.snapshot())
        def delete():
            box = self.app.activeModalWidget()
            next(b for b in box.findChildren(QPushButton) if b.text() == '전체 삭제').click()
        QTimer.singleShot(25, delete)
        self.manager.delete_all()
        self.assertEqual(self.manager.cameras, [])
        self.assertTrue(all(all(cid is None for cid in slots) for slots in self.manager.layout_slots.values()))
        self.assertEqual(self.camera['url'], 'rtsp://user:test@127.0.0.1/onvif1')


class Player(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_zero_volume_icon_changes_without_modifying_mute(self):
        w = self.window
        camera = w.camera_for_slot(0)
        camera['muted'] = False
        with patch('main.icon', wraps=__import__('icons').icon) as icons:
            w.set_volume(0, 0)
            self.assertIn('muted', [c.args[0] for c in icons.call_args_list])
            icons.reset_mock()
            w.set_volume(0, 1)
            self.assertIn('volume', [c.args[0] for c in icons.call_args_list])
            self.assertFalse(camera['muted'])
            camera['muted'] = True
            icons.reset_mock()
            w.set_volume(0, 50)
            self.assertIn('muted', [c.args[0] for c in icons.call_args_list])

    def test_reset_applies_window_settings_and_preserves_native_handles(self):
        w = self.window
        w.set_always_on_top(True)
        w.set_opacity(35)
        w.toggle_fullscreen(0)
        handles = [int(tile.winId()) for tile in w.tiles]
        config = reset_settings(w.config['cameras'])
        self.assertTrue(w.commit_camera_draft(config['cameras'], config['layout_slots'], True, reset=True))
        self.assertFalse(w.isFullScreen())
        self.assertFalse(w.config['always_on_top'])
        self.assertEqual(w.config['layout'], 1)
        self.assertEqual(w.config['opacity'], 80)
        self.assertIsNone(w.focused_screen)
        self.assertEqual(handles, [int(tile.winId()) for tile in w.tiles])

    def test_reset_save_failure_keeps_running_settings(self):
        w = self.window
        before = copy.deepcopy(w.config)
        config = reset_settings(w.config['cameras'])
        w.persist_enabled = True
        try:
            with patch('main.save_config', side_effect=OSError('synthetic failure')):
                self.assertFalse(w.commit_camera_draft(config['cameras'], config['layout_slots'], True, reset=True))
            self.assertEqual(w.config, before)
        finally:
            w.persist_enabled = False
