import copy
import unittest
from unittest.mock import patch
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from dialogs import CameraManager
import test_app as fixtures


class ViewUI(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_badges_toolbar_and_right_click_icons(self):
        self.window.set_layout(4)
        for index, tile in enumerate(self.window.tiles):
            tile.overlay.reveal_controls()
            self.assertEqual(tile.overlay.screen_badge.text(), f'SCREEN {index + 1}')
            self.assertEqual(tile.overlay.quality_badge.text(), 'HD')
            self.assertEqual(tile.overlay.camera_name.accessibleName(), f'테스트 {index + 1}')
            for button in (tile.overlay.reload, tile.overlay.choose, tile.overlay.mute, tile.overlay.fullscreen):
                self.assertFalse(button.icon().isNull())
                self.assertTrue(button.toolTip())
            menu = self.window.build_context_menu(index)
            actions = {action.text(): action for action in menu.actions()}
            self.assertIn('이 화면의 카메라 지정', actions)
            self.assertFalse(actions['이 화면의 카메라 지정'].icon().isNull())
            self.assertNotIn('이 카메라 수정…', actions)
            for text in ('이 영상 다시 연결',):
                self.assertFalse(actions[text].icon().isNull())
            app_menu = self.window.build_app_menu()
            app_actions = {action.text(): action for action in app_menu.actions()}
            for text in ('항상 위에 표시', '등록된 카메라 관리…', '전체 화면 구성'):
                self.assertFalse(app_actions[text].icon().isNull())
                self.assertNotIn(text, actions)
            app_menu.deleteLater()
            menu.deleteLater()

    def test_real_single_doubleclick_fullscreen_roundtrip(self):
        self.window.set_layout(1)
        geometry = QRect(self.window.geometry())
        handles = [int(tile.winId()) for tile in self.window.tiles]
        self.window.toggle_focus(0)
        QTest.qWait(100)
        self.assertTrue(self.window.isFullScreen())
        self.assertIsNone(self.window.focused_screen)
        self.window.toggle_focus(0)
        QTest.qWait(100)
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.geometry(), geometry)
        self.assertEqual(handles, [int(tile.winId()) for tile in self.window.tiles])

    def test_split_fullscreen_escape_restores_split_then_window(self):
        self.window.set_layout(4)
        slots = list(self.window.config['slots'])
        geometry = QRect(self.window.geometry())
        self.window.toggle_fullscreen(2)
        QTest.qWait(100)
        self.assertTrue(self.window.isFullScreen())
        self.assertEqual(self.window.config['layout'], 4)
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.config['slots'], slots)
        self.window.handle_escape()
        QTest.qWait(100)
        self.assertTrue(self.window.isFullScreen())
        self.assertEqual(self.window.config['layout'], 4)
        self.assertEqual(self.window.config['slots'], slots)
        self.window.handle_escape()
        QTest.qWait(100)
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.geometry(), geometry)

    def test_single_fullscreen_escape_and_persistence(self):
        self.window.set_layout(1)
        geometry = QRect(self.window.geometry())
        self.window.toggle_fullscreen(0)
        self.window.persist_enabled = True
        with patch('main.save_config') as save:
            self.window.persist()
            self.assertEqual(save.call_args.args[0]['geometry'],
                             [geometry.x(), geometry.y(), geometry.width(), geometry.height()])
        self.window.persist_enabled = False
        self.window.handle_escape()
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.config['layout'], 1)

    def test_camera_cycle_wrap_and_focus_keeps_view(self):
        ids = [camera['id'] for camera in self.window.config['cameras']]
        self.window.set_layout(1)
        self.window.cycle_camera(-1)
        self.assertEqual(self.window.config['slots'][0], ids[-1])
        self.window.cycle_camera(1)
        self.assertEqual(self.window.config['slots'][0], ids[0])
        self.window.set_layout(4)
        self.window.single_view(2)
        self.window.cycle_camera(1)
        self.assertEqual(self.window.config['layout'], 4)
        self.assertEqual(self.window.focused_screen, 3)
        self.assertEqual(self.window.config['slots'][0], ids[0])
        self.window.restore_focus()
        self.assertEqual(self.window.config['slots'][2], ids[2])
        self.assertEqual(len(set(self.window.config['slots'])), 4)

    def test_manager_explicit_screen_assignment_and_cancel_isolation(self):
        original = list(self.window.config['slots'])
        dialog = CameraManager(self.window.config['cameras'], self.window, slots=original)
        target = self.window.config['cameras'][5]['id']
        choice = dialog.screen_choices[1]
        choice.setCurrentIndex(choice.findData(target))
        self.assertTrue(dialog.assignment_changed)
        self.assertEqual(dialog.slots[1], target)
        self.assertEqual(self.window.config['slots'], original)
        self.window.apply_camera_registry(copy.deepcopy(dialog.cameras), dialog.slots)
        self.assertEqual(self.window.config['slots'][1], target)
        dialog.close()
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
