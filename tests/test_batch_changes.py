import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRect
from PySide6.QtTest import QTest

import test_app as fixtures
from menu_labels import CAMERAS, TOPMOST, LAYOUT, OPACITY


class BatchChanges(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            QTest.qWait(40)
        return bool(predicate())

    def test_menu_names_order_icons_shortcuts_and_hardware_action(self):
        menu = self.window.build_app_menu()
        actions = [a for a in menu.actions() if not a.isSeparator()]
        names = [a.text().split('\t')[0] for a in actions]
        self.assertEqual(names[:7], [LAYOUT, '전체 음소거', CAMERAS, '전체화면',
            '항상 위에', '하드웨어 가속 해제', OPACITY])
        self.assertEqual(sum('CamFloat' in name for name in names), 1)
        self.assertIn(OPACITY, names)
        self.assertEqual(actions[4].text().split('\t')[1], 'Ctrl+T')
        self.assertEqual(actions[2].text().split('\t')[1], 'Ctrl+M')
        for index in range(4):
            self.assertFalse(actions[index].icon().isNull())
        expected = ['1분할\t1', '2분할 · 좌우\t2', '2분할 · 상하\t2', '4분할\t4']
        for action, label in zip(actions[0].menu().actions(), expected, strict=True):
            self.assertEqual(action.text(), label)
            self.assertFalse(action.icon().isNull())
        hardware = next(a for a in actions if a.text() == '하드웨어 가속 해제')
        self.assertFalse(hardware.isCheckable())
        hardware.trigger()
        self.assertFalse(self.window.config['hardware_acceleration'])
        chrome = self.window.chrome
        self.assertTrue(all(button.text() == '' and not button.icon().isNull()
                            for button in chrome.layout_buttons.values()))
        self.assertIn('(1)', chrome.layout_buttons[1].toolTip())
        chrome.layout().activate() if chrome.layout() else None
        chrome.panel.layout().activate()
        self.assertLess(chrome.manager.x(), chrome.fullscreen.x())
        menu.deleteLater()

    def test_screen_menu_names_match_and_popup_animations_disabled(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        menu = self.window.build_context_menu(0)
        items = {a.text().split('\t')[0]: a for a in menu.actions()}
        cameras = items['이 화면의 카메라 지정'].menu()
        self.assertTrue(any(a.text() == CAMERAS + '\tCtrl+M' for a in cameras.actions()))
        self.assertIn('전체화면', items)
        self.assertEqual(items['전체화면'].text(), '전체화면\tF11')
        self.assertEqual(items['이 영상 다시 연결'].text(), '이 영상 다시 연결\tCtrl+R')
        self.assertFalse(QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu))
        self.assertFalse(QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateMenu))
        menu.deleteLater()

    def test_escape_then_f11_preserves_restored_split(self):
        self.window.set_layout(4)
        self.window.single_view(2)
        original = QRect(self.window.geometry())
        self.window.toggle_fullscreen(2)
        self.window.handle_escape()
        self.assertTrue(self.window.isFullScreen())
        self.assertIsNone(self.window.focused_screen)
        self.window.toggle_fullscreen(self.window.selected)
        self.assertFalse(self.window.isFullScreen())
        self.assertIsNone(self.window.focused_screen)
        self.assertEqual(self.window.geometry(), original)
        self.assertEqual(self.window.config['layout'], 4)

    def test_selection_border_only_where_requested(self):
        self.window.set_layout(1)
        self.window.select_slot(0)
        self.assertFalse(self.window.selection_border_visible(0))
        self.window.toggle_fullscreen(0)
        self.assertFalse(self.window.selection_border_visible(0))
        self.window.handle_escape()
        self.window.set_layout(4)
        self.window.select_slot(1)
        self.assertTrue(self.window.selection_border_visible(1))
        self.window.single_view(1)
        self.assertTrue(self.window.selection_border_visible(1))
        self.window.toggle_fullscreen(1)
        self.assertFalse(self.window.selection_border_visible(1))
        self.window.handle_escape()
        self.assertTrue(self.window.selection_border_visible(1))

    def test_manual_reload_replaces_paused_player_without_interrupting_other_stream(self):
        tile, other = self.window.tiles[:2]
        self.assertTrue(self.wait_for(lambda: all(not t.worker.busy and t.player.has_vout() for t in (tile, other))))
        second_player = id(other.player)
        second_revision = other.worker.revision
        second_time = other.player.get_time()
        hwnds = [int(t.winId()) for t in self.window.tiles]
        for _ in range(3):
            original_player = id(tile.player)
            tile.player.set_pause(1)
            self.assertTrue(self.wait_for(lambda: tile.player.get_state().value == 4, 2))
            self.window.reconnect(0)
            self.assertTrue(self.wait_for(lambda: not tile.worker.busy and id(tile.player) != original_player
                and tile.player.is_playing() and tile.player.has_vout() > 0 and tile.player.get_time() > 0))
            self.assertEqual(id(other.player), second_player)
            self.assertEqual(other.worker.revision, second_revision)
            self.assertTrue(other.player.is_playing())
        self.assertNotEqual(other.player.get_time(), second_time)
        self.assertEqual([int(t.winId()) for t in self.window.tiles], hwnds)

    def test_displayed_frame_watchdog_detects_frozen_output(self):
        tile = self.window.tiles[0]
        tile.last_frame_count = None
        with patch.object(tile, 'displayed_frames', return_value=50):
            self.assertFalse(tile.frames_stalled(10))
            self.assertTrue(tile.frames_stalled(31))
        with patch.object(tile, 'displayed_frames', return_value=51):
            self.assertFalse(tile.frames_stalled(32))
        with patch.object(tile, 'displayed_frames', return_value=None):
            self.assertFalse(tile.frames_stalled(100))
        self.assertTrue(self.wait_for(lambda: not tile.worker.busy and tile.player.is_playing()))
        self.assertIsInstance(tile.displayed_frames(), int)
        # Occluded outputs can legitimately stop presenting while their input
        # keeps playing; do not reconnect them on that basis.
        self.window.single_view(1)
        with patch.object(tile, 'frames_stalled', return_value=True) as frames, \
                patch.object(tile, 'clock_stalled', return_value=False):
            self.window.update_status()
            frames.assert_not_called()
            self.assertIsNone(tile.retry_at)


if __name__ == '__main__':
    unittest.main(verbosity=2)
