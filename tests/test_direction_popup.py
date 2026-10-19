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

    def test_press_sends_before_release_and_hold_stops_on_release(self):
        panel = self.open_panel()
        button = panel.buttons['left']
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        QTest.qWait(40)
        self.assertTrue(any(x[0] == 'ContinuousMove' for x in FakeClient.calls))
        QTest.qWait(660)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        QTest.qWait(50)
        count = len(FakeClient.calls)
        self.assertGreaterEqual(count, 2)
        QTest.qWait(350)
        self.assertEqual(len(FakeClient.calls), count)
        self.assertFalse(panel.hold_timer.isActive())
        self.assertFalse(any(x[0] == 'Stop' for x in FakeClient.calls))

    def test_hold_is_cancelled_on_app_change(self):
        panel = self.open_panel()
        QTest.mousePress(panel.buttons['up'], Qt.MouseButton.LeftButton)
        QTest.qWait(190)
        self.window.application_state_changed(Qt.ApplicationState.ApplicationInactive)
        self.assertFalse(panel.hold_timer.isActive())
        QTest.qWait(30)
        count = len(FakeClient.calls)
        QTest.qWait(350)
        self.assertEqual(len(FakeClient.calls), count)

    def test_missing_reply_does_not_replace_buttons_or_interrupt_hold_and_clicks(self):
        with patch.object(FakeClient, 'step', return_value={
                'request_sent': True, 'response_verified': False, 'error': 'TimeoutError'}) as move:
            panel = self.open_panel()
            QTest.mousePress(panel.buttons['right'], Qt.MouseButton.LeftButton)
            QTest.qWait(650)
            self.assertTrue(panel.hold_timer.isActive())
            self.assertGreaterEqual(move.call_count, 2)
            self.assertFalse(panel.status.isVisible())
            self.assertTrue(all(b.isVisible() and b.isEnabled() for b in panel.buttons.values()))
            QTest.mouseRelease(panel.buttons['right'], Qt.MouseButton.LeftButton)
            QTest.qWait(50)
            count = move.call_count
            for _ in range(4):
                QTest.mouseClick(panel.buttons['left'], Qt.MouseButton.LeftButton)
                QTest.qWait(40)
            # Four manual clicks survive release and drain through the queue.
            QTest.qWait(2500)
            self.assertEqual(move.call_count, count + 4)
            self.assertFalse(panel.status.isVisible())

    def test_hold_repeats_while_previous_replies_are_still_pending(self):
        import threading
        gate = threading.Event()
        sent = []
        def delayed(client, pan, tilt=0, *, attempt=None):
            if attempt.cancelled.is_set() or not attempt.before_send():
                return {'cancelled': True, 'request_sent': False}
            attempt.on_event('write_started')
            attempt.request_sent()
            sent.append((pan, tilt))
            gate.wait(1)
            return {'request_sent': True, 'response_verified': True}
        with patch.object(FakeClient, 'step', delayed):
            panel = self.open_panel()
            try:
                QTest.mousePress(panel.buttons['right'], Qt.MouseButton.LeftButton)
                QTest.qWait(720)
                self.assertGreaterEqual(len(sent), 2)
                self.assertTrue(self.window.direction_control.busy)
                QTest.mouseRelease(panel.buttons['right'], Qt.MouseButton.LeftButton)
                count = len(sent)
                QTest.qWait(190)
                self.assertEqual(len(sent), count)
            finally:
                gate.set()
                self.assertTrue(self.window.direction_control.done.wait(2))
                self.app.processEvents()

    def test_registration_commit_queries_new_connection_only(self):
        with patch.object(self.window.direction_control, 'discover') as query:
            cameras = [dict(c) for c in self.window.config['cameras']]
            cameras[0]['url'] += '?updated'
            maps = self.window.config['layout_slots']
            self.assertTrue(self.window.commit_camera_draft(cameras, maps, True))
            self.assertEqual(query.call_count, 1)
            self.assertEqual(query.call_args.args[0]['id'], cameras[0]['id'])
            query.reset_mock()
            self.assertTrue(self.window.commit_camera_draft(cameras, maps, True))
            query.assert_not_called()

    def test_app_change_discards_queued_manual_clicks(self):
        panel = self.open_panel()
        for _ in range(4):
            QTest.mouseClick(panel.buttons['left'], Qt.MouseButton.LeftButton)
            QTest.qWait(20)
        control = self.window.direction_control
        self.assertTrue(control.pending)
        self.window.application_state_changed(Qt.ApplicationState.ApplicationInactive)
        self.assertFalse(control.pending)
        QTest.qWait(100)
        count = len(FakeClient.calls)
        QTest.qWait(650)
        self.assertEqual(len(FakeClient.calls), count)

    def test_control_port_only_change_requeries_and_ignores_old_metadata(self):
        from ptz_control import camera_key
        from ptz_metadata import defaults
        cameras = [dict(c) for c in self.window.config['cameras']]
        old = dict(cameras[0])
        cameras[0]['control_port'] = 25554
        with patch.object(self.window.direction_control, 'discover') as query:
            self.assertTrue(self.window.commit_camera_draft(cameras, self.window.config['layout_slots'], True))
            self.assertEqual(query.call_count, 1)
            query.assert_called_with(self.window.config['cameras'][0])
        before = self.window.config['cameras'][0].get('ptz')
        self.window.store_control_metadata(camera_key(old), dict(defaults(old), checked=True))
        self.assertEqual(self.window.config['cameras'][0].get('ptz'), before)


if __name__ == '__main__':
    unittest.main()
