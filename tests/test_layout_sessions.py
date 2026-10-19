import copy
import json
import unittest
from unittest.mock import patch
from PySide6.QtTest import QTest
from camfloat.camera_model import (default_config, ensure_layout_slots, fill_empty_slots, new_camera,
                          normalize, save_config, load_config)
from camfloat.dialogs import CameraManager
import test_app as fixtures


class LayoutStorage(unittest.TestCase):
    setUp = fixtures.ModelTests.setUp
    tearDown = fixtures.ModelTests.tearDown

    def test_migration_and_independent_layout_roundtrip(self):
        cameras = [new_camera(str(i), f'rtsp://host{i}/onvif1') for i in range(4)]
        ids = [c['id'] for c in cameras]
        config = normalize(dict(cameras=cameras, layout=4, slots=ids))
        self.assertEqual(config['layout_slots']['1'], [ids[0], None, None, None])
        config['layout_slots']['1'][0] = ids[3]
        config['layout_slots']['2'][:2] = [ids[2], ids[1]]
        save_config(config)
        loaded = load_config()
        self.assertEqual(loaded['layout_slots'], config['layout_slots'])
        self.assertEqual(loaded['layout_slots']['4'], ids)

    def test_disabled_filter_and_reenable_only_empty_slots(self):
        config = default_config()
        config['cameras'] = [new_camera(str(i), f'rtsp://host{i}/onvif1') for i in range(4)]
        ids = [c['id'] for c in config['cameras']]
        config.update(slots=ids, layout=4)
        ensure_layout_slots(config)
        config['cameras'][0]['enabled'] = False
        ensure_layout_slots(config)
        for count, slots in config['layout_slots'].items():
            self.assertNotIn(ids[0], slots)
            if count != '1':
                self.assertIsNone(slots[0])
        self.assertEqual(config['layout_slots']['1'][0], ids[1])
        config['layout_slots']['4'][0] = ids[3]
        config['layout_slots']['4'][3] = None
        config['cameras'][0]['enabled'] = True
        fill_empty_slots(config, [ids[0]])
        self.assertEqual(config['layout_slots']['4'], [ids[3], ids[1], ids[2], ids[0]])
        self.assertEqual(config['layout_slots']['1'][0], ids[1])


class SessionRules(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_first_connection_failure_never_auto_retries_but_manual_does(self):
        tile = self.window.tiles[0]
        tile.ever_played = False
        tile.initial_failed = False
        tile.worker.busy = False
        tile.attempt_started = 0
        with patch.object(tile.player, 'get_state') as state, patch('camfloat.main.time.monotonic', return_value=30):
            state.return_value.value = 7
            self.window.update_status()
            self.assertTrue(tile.initial_failed)
            self.assertIsNone(tile.retry_at)
            revision = tile.worker.revision
            for _ in range(8):
                self.window.update_status()
            self.assertEqual(tile.worker.revision, revision)
            self.assertIn('다시 연결', tile.status_text)
            self.window.reconnect(0)
            self.assertFalse(tile.initial_failed)
            self.assertGreater(tile.worker.revision, revision)

    def test_enlarging_and_screen_cycle_never_reconnect_or_change_assignment(self):
        self.window.set_layout(4)
        QTest.qWait(600)
        slots = copy.deepcopy(self.window.config['layout_slots'])
        handles = [int(t.winId()) for t in self.window.tiles]
        revisions = [t.worker.revision for t in self.window.tiles]
        players = [id(t.player) for t in self.window.tiles]
        for index in (2, 0, 3, 1):
            self.window.single_view(index)
            QTest.qWait(50)
            self.assertEqual(self.window.config['layout'], 4)
            self.assertEqual(self.window.focused_screen, index)
            self.assertEqual(sum(t.overlay.isVisible() for t in self.window.tiles), 1)
            self.assertTrue(all(t.isVisible() for t in self.window.tiles))
            self.assertTrue(all(t.player.is_playing() for t in self.window.tiles))
            self.assertEqual(self.window.tiles[index].geometry(), self.window.rect())
        self.window.cycle_camera(1)
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.tiles[2].overlay.screen_badge.text(), 'SCREEN 3')
        self.assertIn('SCREEN', self.window.tiles[2].overlay.following.accessibleName())
        self.window.handle_escape()
        self.assertIsNone(self.window.focused_screen)
        self.assertEqual(self.window.config['layout_slots'], slots)
        self.assertEqual([t.worker.revision for t in self.window.tiles], revisions)
        self.assertEqual([int(t.winId()) for t in self.window.tiles], handles)
        self.assertEqual([id(t.player) for t in self.window.tiles], players)

    def test_layout_assignments_do_not_leak_to_other_layouts(self):
        ids = [c['id'] for c in self.window.config['cameras']]
        self.window.set_layout(1)
        self.window.assign_camera(0, ids[5])
        self.window.set_layout(2)
        self.assertEqual(self.window.config['slots'][:2], ids[:2])
        self.window.assign_camera(1, ids[4])
        self.window.set_layout(4)
        self.assertEqual(self.window.config['slots'], ids[:4])
        self.window.set_layout(1)
        self.assertEqual(self.window.config['slots'][0], ids[5])
        self.window.set_layout(2)
        self.assertEqual(self.window.config['slots'][1], ids[4])

    def test_manager_disabled_camera_removed_everywhere_then_refills_empty(self):
        dialog = CameraManager(self.window.config['cameras'], self.window,
            layout_slots=self.window.config['layout_slots'], layout=2)
        camera_id = dialog.cameras[0]['id']
        number = dialog.cameras[0]['number']
        dialog.table.selectRow(0)
        dialog.toggle_enabled()
        self.assertFalse(dialog.cameras[0]['enabled'])
        for slots in dialog.layout_slots.values():
            self.assertNotIn(camera_id, slots)
        for choice in dialog.screen_choices:
            self.assertEqual(choice.findData(camera_id), -1)
        dialog.layout_choice.setCurrentIndex(dialog.layout_choice.findData(4))
        dialog.table.selectRow(0)
        dialog.toggle_enabled()
        for count, slots in dialog.layout_slots.items():
            if count != '1':
                self.assertEqual(slots[0], camera_id)
        self.assertNotEqual(dialog.layout_slots['1'][0], camera_id)
        dialog.move_camera(1)
        self.assertEqual(dialog.cameras[1]['number'], number)
        self.assertEqual(dialog.layout_slots['4'][0], camera_id)
        self.window.apply_camera_registry(dialog.cameras, layout_slots=dialog.layout_slots)
        dialog.done(0)
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
