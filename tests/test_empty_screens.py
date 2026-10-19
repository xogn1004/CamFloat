"""Single-view fallback and navigation skip only screens without assignments."""
import copy
import unittest
from camfloat.camera_model import default_config, ensure_layout_slots, new_camera
from camfloat.dialogs import CameraManager
import test_app as fixtures


class SingleAssignment(unittest.TestCase):
    def make_config(self):
        cameras = [new_camera(str(i), f'rtsp://host{i}/onvif1') for i in range(4)]
        config = default_config()
        config.update(cameras=cameras, slots=[c['id'] for c in cameras], layout=4)
        ensure_layout_slots(config)
        return config

    def test_empty_single_uses_first_available_without_filling_split_slots(self):
        config = self.make_config()
        config['layout_slots'] = {str(n): [None] * 4 for n in (1, 2, 4)}
        config['cameras'][0]['enabled'] = False
        ensure_layout_slots(config)
        self.assertEqual(config['layout_slots']['1'][0], config['cameras'][1]['id'])
        self.assertEqual(config['layout_slots']['2'], [None] * 4)
        self.assertEqual(config['layout_slots']['4'], [None] * 4)

    def test_removed_current_uses_successor_and_wraps(self):
        for position, expected in ((1, 2), (3, 0)):
            config = self.make_config()
            old = list(config['cameras'])
            config['layout_slots']['1'][0] = old[position]['id']
            config['cameras'].pop(position)
            ensure_layout_slots(config, previous_cameras=old)
            self.assertEqual(config['layout_slots']['1'][0], old[expected]['id'])

    def test_disabled_or_locked_single_is_skipped_and_all_unavailable_is_none(self):
        config = self.make_config()
        config['cameras'][0]['enabled'] = False
        config['cameras'][1]['connection_locked'] = True
        ensure_layout_slots(config)
        self.assertEqual(config['layout_slots']['1'][0], config['cameras'][2]['id'])
        for camera in config['cameras']:
            camera['enabled'] = False
        ensure_layout_slots(config)
        self.assertIsNone(config['layout_slots']['1'][0])


class EmptyScreenUI(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_single_cannot_be_cleared_in_player_or_manager(self):
        self.window.set_layout(1)
        current = self.window.config['slots'][0]
        self.window.assign_camera(0, None)
        self.assertEqual(self.window.config['slots'][0], current)
        menu = self.window.new_menu()
        self.window.populate_camera_menu(menu, 0)
        self.assertNotIn('이 화면 비우기', [a.text() for a in menu.actions()])
        menu.deleteLater()
        dialog = CameraManager(self.window.config['cameras'], self.window,
                               layout_slots=self.window.config['layout_slots'], layout=1)
        try:
            self.assertEqual(dialog.screen_choices[0].findData(None), -1)
            dialog.clear_screen(0)
            self.assertEqual(dialog.slots[0], current)
            self.assertTrue(dialog.screen_clear_buttons[0].isHidden())
        finally:
            dialog.done(0)
            dialog.deleteLater()

    def test_blank_split_does_not_enlarge_or_enter_fullscreen_by_third_click(self):
        self.window.set_layout(4)
        self.window.assign_camera(1, None)
        self.window.single_view(1)
        self.assertIsNone(self.window.focused_screen)
        self.window.toggle_focus(1)
        self.assertIsNone(self.window.focused_screen)
        from PySide6.QtCore import QPoint
        point = self.window.mapToGlobal(QPoint(50, 50))
        self.window.record_double_click(1, point)
        self.assertFalse(self.window.consume_third_click(point))
        self.assertFalse(self.window.isFullScreen())

    def test_enlarged_navigation_skips_blank_but_keeps_assigned_failed_stream(self):
        self.window.set_layout(4)
        self.window.assign_camera(1, None)
        self.window.assign_camera(3, None)
        self.window.tiles[2].initial_failed = True
        slots = list(self.window.config['slots'])
        self.window.single_view(0)
        self.window.cycle_camera(1)
        self.assertEqual(self.window.focused_screen, 2)
        self.window.cycle_camera(1)
        self.assertEqual(self.window.focused_screen, 0)
        self.window.cycle_camera(-1)
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.config['slots'], slots)

    def test_clearing_enlarged_screen_advances_then_restores_when_all_empty(self):
        self.window.set_layout(2)
        self.window.single_view(0)
        self.window.assign_camera(0, None)
        self.assertEqual(self.window.focused_screen, 1)
        overlay = self.window.tiles[1].overlay
        self.assertFalse(overlay.previous.isEnabled())
        self.assertFalse(overlay.following.isEnabled())
        self.window.assign_camera(1, None)
        self.assertIsNone(self.window.focused_screen)
        self.assertEqual(self.window.config['layout'], 2)

    def test_no_camera_single_has_specific_messages(self):
        self.window.set_layout(1)
        cameras = copy.deepcopy(self.window.config['cameras'])
        for camera in cameras:
            camera['enabled'] = False
        self.window.apply_camera_registry(cameras)
        self.assertEqual(self.window.tiles[0].overlay.empty.text(), '사용 중인 카메라가 없습니다')
        self.window.apply_camera_registry([])
        self.assertEqual(self.window.tiles[0].overlay.empty.text(), '등록된 카메라가 없습니다')
