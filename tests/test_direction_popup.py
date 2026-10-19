"""Responsive direction controls with synthetic video and fake camera clients."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_direction_control import FakeClient
import test_app as fixtures


class DirectionPopupTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)

    def setUp(self):
        self.client_patch = patch('ptz_control.Client', FakeClient)
        self.eligible_patch = patch('ptz_control.eligible', return_value=True)
        self.client_patch.start()
        self.eligible_patch.start()
        FakeClient.calls = []
        FakeClient.gate = None
        fixtures.WindowTests.setUp(self)
        self.overlay = self.window.tiles[0].overlay

    def tearDown(self):
        fixtures.WindowTests.tearDown(self)
        self.client_patch.stop()
        self.eligible_patch.stop()

    def open_panel(self):
        self.overlay.reveal_controls()
        QTest.mouseClick(self.overlay.move_camera, Qt.MouseButton.LeftButton)
        for _ in range(100):
            self.app.processEvents()
            if self.window.direction_control.state == 'ready':
                break
            QTest.qWait(10)
        self.assertEqual(self.window.direction_control.state, 'ready')
        self.assertTrue(self.overlay.direction_popup.isVisible())
        return self.overlay.direction_popup

    def test_compact_panel_is_one_row_and_inside_smallest_pane(self):
        self.window.resize(300, 180)
        self.window.set_layout(4)
        self.app.processEvents()
        panel = self.open_panel()
        self.assertTrue(panel.compact)
        self.assertEqual(len({b.y() for b in panel.buttons.values()}), 1)
        self.assertTrue(self.overlay.rect().contains(panel.geometry()))
        self.assertTrue(self.overlay.rect().contains(self.overlay.bar.geometry()))
        self.assertEqual(list(panel.buttons), ['left', 'up', 'down', 'right'])
        self.assertTrue(all(not b.autoRepeat() and b.toolTip() for b in panel.buttons.values()))
        self.assertEqual(FakeClient.calls, [])

    def test_wide_panel_is_cross_and_escape_dismisses_before_fullscreen(self):
        self.window.set_layout(1)
        self.window.resize(800, 450)
        self.app.processEvents()
        panel = self.open_panel()
        self.assertFalse(panel.compact)
        self.assertLess(panel.buttons['up'].y(), panel.buttons['left'].y())
        self.assertGreater(panel.buttons['down'].y(), panel.buttons['left'].y())
        self.assertEqual(panel.buttons['left'].y(), panel.buttons['right'].y())
        self.window.handle_escape()
        self.assertFalse(panel.isVisible())
        self.assertFalse(self.overlay.move_camera.isChecked())

    def test_buttons_operate_panel_camera_even_if_selection_changes(self):
        panel = self.open_panel()
        self.window.select_slot(1)
        QTest.mouseClick(panel.buttons['up'], Qt.MouseButton.LeftButton)
        for _ in range(100):
            self.app.processEvents()
            if self.window.direction_control.state == 'ready':
                break
            QTest.qWait(10)
        self.assertEqual([x for x in FakeClient.calls if x[0] == 'ContinuousMove'], [('ContinuousMove', 0, 1)])

    def test_background_and_camera_change_close_panel(self):
        panel = self.open_panel()
        self.window.application_state_changed(Qt.ApplicationState.ApplicationInactive)
        self.assertFalse(panel.isVisible())
        panel = self.open_panel()
        self.window.assign_camera(0, self.window.config['cameras'][2]['id'])
        self.assertFalse(panel.isVisible())

    def test_outside_click_toggle_and_toolbar_suppression(self):
        panel = self.open_panel()
        self.window.chrome.reveal()
        self.assertFalse(self.window.chrome.isVisible())
        QTest.mouseClick(self.overlay.move_camera, Qt.MouseButton.LeftButton)
        self.assertFalse(panel.isVisible())
        panel = self.open_panel()
        QTest.mouseClick(self.overlay.reload, Qt.MouseButton.LeftButton)
        self.assertFalse(panel.isVisible())
        self.assertIsNone(self.window.direction_control.target)

    def test_right_menu_matches_icon_and_no_new_setting(self):
        menu = self.window.build_context_menu(0)
        action = next(a for a in menu.actions() if a.text() == '카메라 이동')
        self.assertFalse(action.icon().isNull())
        self.assertFalse(any('ptz' in k or 'direction' in k for k in self.window.config))
        menu.deleteLater()


if __name__ == '__main__':
    unittest.main()
