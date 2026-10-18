import copy
import base64
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from camera_model import (LOAD_WARNINGS, build_url, camera_url, crypt, data_path, default_config,
    load_config, new_camera, normalize, redact, save_config, supports_quality, validate_rtsp_url)
from dialogs import CameraEditor, CameraManager
from playback import PlaybackWorker
import test_app as fixtures
from single_instance import InstanceGuard
from main import demo_video_url
import tempfile
import os


class StorageRegressions(unittest.TestCase):
    setUp = fixtures.ModelTests.setUp
    tearDown = fixtures.ModelTests.tearDown
    def test_malformed_fields_and_duplicate_slots(self):
        camera = new_camera('one', 'rtsp://127.0.0.1/onvif1')
        camera['volume'] = 'invalid'
        raw = dict(cameras=[None, 3, camera], opacity='bad', geometry=['?', 0, 1, 1],
                   slots=[camera['id'], camera['id'], {}, 'missing'])
        config = normalize(raw)
        self.assertEqual(config['opacity'], 100)
        self.assertEqual(config['cameras'][0]['volume'], 100)
        self.assertEqual(config['slots'], [camera['id'], None, None, None])
        self.assertIsNone(config['geometry'])
        self.assertEqual(normalize(dict(layout=2.0))['layout'], 1)

    def test_corrupted_json_recovers_previous_encrypted_save(self):
        config = default_config()
        config['cameras'] = [new_camera('first', 'rtsp://admin:secret@localhost/onvif1')]
        save_config(config)
        config['cameras'][0]['name'] = 'second'
        save_config(config)
        data_path().write_text('{ broken', encoding='utf-8')
        loaded = load_config()
        self.assertEqual(loaded['cameras'][0]['name'], 'first')
        self.assertTrue(LOAD_WARNINGS)
        self.assertTrue(list(data_path().parent.glob('settings-damaged-*.json')))
        self.assertNotIn('secret', data_path().with_suffix('.backup.json').read_text())

    def test_corrupt_without_backup_preserves_source(self):
        data_path().write_text('{ invalid', encoding='utf-8')
        self.assertEqual(load_config(), default_config())
        self.assertTrue(LOAD_WARNINGS)
        recovered = json.loads(next(data_path().parent.glob('settings-damaged-*.json')).read_text())
        self.assertEqual(base64.b64decode(crypt(recovered['data'], decrypt=True)), b'{ invalid')
        save_config(default_config())
        self.assertEqual(load_config(), normalize(default_config()))

    def test_failed_atomic_replace_preserves_original_and_cleans_temp(self):
        config = default_config()
        save_config(config)
        original = data_path().read_bytes()
        with patch('camera_model.os.replace', side_effect=PermissionError('test')):
            with self.assertRaises(PermissionError):
                save_config(dict(config, opacity=50))
        self.assertEqual(data_path().read_bytes(), original)
        self.assertFalse(list(data_path().parent.glob('settings-*.tmp')))

    def test_custom_sd_encrypted_and_quality_selection(self):
        camera = new_camera('custom', 'rtsp://admin:hdsecret@localhost/main')
        camera.update(sd_url='rtsp://admin:sdsecret@localhost/sub', quality='SD')
        config = default_config()
        config['cameras'] = [camera]
        config['slots'][0] = camera['id']
        save_config(config)
        stored = data_path().read_text()
        self.assertNotIn('hdsecret', stored)
        self.assertNotIn('sdsecret', stored)
        self.assertEqual(load_config(), config)
        self.assertEqual(camera_url(camera), camera['sd_url'])
        self.assertTrue(supports_quality(camera))
        camera['sd_url'] = ''
        self.assertFalse(supports_quality(camera))

    def test_invalid_addresses_and_ipv6(self):
        for url in ('http://localhost', 'rtsp://localhost:0/x', 'rtsp://localhost:/x',
                    'rtsp://host:65536/x', 'rtsp://host/has space', 'rtsp://u:p#x@host/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_rtsp_url(url)
        for host in ('host:554', 'http://host', 'host?x', 'a b'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                build_url(host, 554, 'a', 'b')
        url = build_url('::1', 15554, 'admin', 'a@b')
        self.assertEqual(validate_rtsp_url(url).hostname, '::1')
        with self.assertRaises(ValueError):
            build_url('host', 554, '', 'secret')

    def test_log_redaction_including_token_query(self):
        text = 'failed rtsp://user:secret@host/path?token=abcdef and RTSP://u:p@h/x\nend'
        safe = redact(text)
        self.assertNotIn('secret', safe)
        self.assertNotIn('abcdef', safe)
        self.assertNotIn('u:p', safe)

    def test_legacy_plaintext_backups_are_encrypted(self):
        data_path().write_text(json.dumps(dict(streams=[dict(url='rtsp://u:private@host/onvif1')])))
        save_config(load_config())
        for path in data_path().parent.glob('*.json'):
            self.assertNotIn('private@', path.read_text(encoding='utf-8'))

    def test_demo_video_relative_path_resolves_to_absolute_file_url(self):
        url = demo_video_url('sample-test.mp4')
        self.assertTrue(url.startswith('file:///'))
        self.assertIn('/camfloat/sample-test.mp4', url.replace('\\', '/'))
        with self.assertRaises(ValueError):
            demo_video_url('does-not-exist.mp4')


class UIRegressions(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown
    def test_registry_edits_preserve_custom_assignments_and_clear_tile(self):
        self.window.assign_camera(0, self.window.config['cameras'][5]['id'])
        original = list(self.window.config['slots'])
        edited = copy.deepcopy(self.window.config['cameras'])
        edited[5]['name'] = 'renamed'
        self.window.apply_camera_registry(edited)
        self.assertEqual(self.window.config['slots'], original)
        self.window.apply_camera_registry(copy.deepcopy(edited))
        self.assertEqual(self.window.config['slots'], original)
        self.window.assign_camera(1, None)
        self.assertIsNone(self.window.camera_for_slot(1))
        self.window.assign_camera(0, 'unknown')
        self.assertEqual(self.window.config['slots'][0], original[0])

    def test_focus_restore_order_and_assignment_to_original_tile(self):
        self.window.set_layout(4)
        original = list(self.window.config['slots'])
        self.window.select_slot(2)
        self.window.single_view(2)
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.config['slots'], original)
        self.window.restore_focus()
        self.assertEqual(self.window.config['layout'], 4)
        self.assertEqual(self.window.config['slots'], original)
        self.assertEqual(self.window.selected, 2)
        self.window.single_view(2)
        self.window.assign_camera(2, None)
        self.assertEqual(self.window.config['layout'], 4)
        self.assertIsNone(self.window.config['slots'][2])
        self.assertEqual(self.window.config['slots'][0], original[0])

    def test_opening_timeout_backoff_and_hover_status(self):
        tile = self.window.tiles[0]
        # Deterministic virtual clock; real libVLC playback is exercised elsewhere.
        with patch.object(tile.player, 'get_state') as state, patch('main.time.monotonic', return_value=100):
            state.return_value.value = 1
            tile.attempt_started = 80
            tile.ever_played = True
            tile.worker.busy = False
            self.window.update_status()
            self.assertEqual(tile.retry_at, 102)
            tile.overlay.refresh()
            self.assertIn('재연결', tile.overlay.empty.text())
            self.assertFalse(tile.overlay.empty.isHidden())
        with patch.object(tile.player, 'get_state') as state, patch('main.time.monotonic', return_value=103), patch.object(tile, 'start_attempt') as start:
            state.return_value.value = 7
            self.window.update_status()
            start.assert_called_once()
        tile.stop()
        self.assertIsNone(tile.retry_at)

    def test_stalled_media_clock_detects_freeze_without_rejecting_unsupported_clocks(self):
        tile = self.window.tiles[0]
        tile.last_clock = None
        with patch.object(tile.player, 'get_time', return_value=0):
            self.assertFalse(tile.clock_stalled(10))
            self.assertFalse(tile.clock_stalled(100))
        with patch.object(tile.player, 'get_time', return_value=1000):
            self.assertFalse(tile.clock_stalled(101))
            self.assertTrue(tile.clock_stalled(122))
        with patch.object(tile.player, 'get_time', return_value=2000):
            self.assertFalse(tile.clock_stalled(123))

    def test_volume_controls_sync_and_global_mute(self):
        self.window.set_volume(0, 67)
        self.assertEqual(self.window.tiles[0].overlay.volume.value(), 67)
        self.window.set_volume(0, 1000)
        self.assertEqual(self.window.camera_for_slot(0)['volume'], 100)
        self.window.mute_all()
        self.assertTrue(all(camera['muted'] for camera in self.window.config['cameras']))
        self.assertIn('해제', self.window.tiles[0].overlay.mute.toolTip())
        self.assertFalse(self.window.tiles[0].overlay.mute.icon().isNull())

    def test_real_vlc_audio_track_volume_and_muted_state(self):
        player = self.window.tiles[0].player
        deadline = time.monotonic() + 5
        while player.audio_get_track_count() < 2 and time.monotonic() < deadline:
            QTest.qWait(50)
        self.assertGreaterEqual(player.audio_get_track_count(), 2)
        self.window.set_volume(0, 37)
        deadline = time.monotonic() + 3
        while (player.audio_get_volume() != 37 or not player.audio_get_mute()) and time.monotonic() < deadline:
            QTest.qWait(50)
        self.assertEqual(player.audio_get_volume(), 37)
        self.assertTrue(player.audio_get_mute())

    def test_rapid_layout_quality_hardware_changes_then_recovery(self):
        handles = [int(tile.winId()) for tile in self.window.tiles]
        for i in range(12):
            self.window.set_layout((1, 2, 4)[i % 3])
            self.window.set_hardware(i % 2 == 0)
            self.window.reconnect(0)
        self.window.set_layout(4)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if all(tile.player.is_playing() and not tile.worker.busy for tile in self.window.tiles):
                break
            QTest.qWait(50)
        self.assertEqual(handles, [int(tile.winId()) for tile in self.window.tiles])
        self.assertTrue(all(tile.player.is_playing() for tile in self.window.tiles),
                        [(str(tile.player.get_state()), tile.worker.busy) for tile in self.window.tiles])

    def test_offscreen_geometry_is_recoverable(self):
        self.window.setGeometry(QRect(-30000, 30000, 8000, 8000))
        self.window.fit_to_screen()
        self.assertTrue(any(screen.availableGeometry().contains(self.window.geometry())
                            for screen in self.app.screens()))
        with self.assertRaises(ValueError):
            self.window.set_layout(3)

    def test_editor_invalid_mode_switch_does_not_replace_pasted_url(self):
        editor = CameraEditor(new_camera('x', 'rtsp://host/main'), self.window)
        editor.full_url.setText('rtsp://host:badport/main')
        editor.mode.setCurrentIndex(0)
        self.assertEqual(editor.mode.currentIndex(), 0)
        editor.mode.setCurrentIndex(1)
        self.assertEqual(editor.full_url.text(), 'rtsp://host:badport/main')
        editor.validate()
        self.assertNotEqual(editor.result(), QDialog.DialogCode.Accepted)
        editor.full_url.setText('rtsp://host/main')
        editor.sd_url.setText('rtsp://host/sub')
        editor.validate()
        self.assertEqual(editor.camera['sd_url'], 'rtsp://host/sub')
        editor.deleteLater()

    def test_registry_shows_all_cameras_and_order_is_always_available(self):
        manager = CameraManager(self.window.config['cameras'], self.window)
        self.assertFalse(hasattr(manager, 'search'))
        self.assertFalse(hasattr(manager, 'filter'))
        manager.table.selectRow(5)
        self.assertEqual(manager.table.currentRow(), 5)
        self.assertFalse(manager.table.isRowHidden(0))
        self.assertTrue(manager.buttons['up'].isEnabled())
        manager.move_camera(-1)
        self.assertEqual(manager.table.currentRow(), 4)
        manager.deleteLater()

    def test_modal_form_accepts_digits_without_layout_shortcut_interception(self):
        with self.window.modal():
            self.assertTrue(all(not shortcut.isEnabled() for shortcut in self.window.shortcuts))
            editor = CameraEditor(parent=self.window)
            editor.show()
            editor.host.setFocus()
            QTest.keyClicks(editor.host, '192.168.1.24')
            self.assertEqual(editor.host.text(), '192.168.1.24')
            self.assertEqual(self.window.config['layout'], 2)
            editor.close()
            editor.deleteLater()
        self.assertTrue(all(shortcut.isEnabled() for shortcut in self.window.shortcuts))

    def test_focus_persistence_keeps_previous_split_and_order(self):
        self.window.set_layout(4)
        original = list(self.window.config['slots'])
        self.window.single_view(3)
        self.window.persist_enabled = True
        with patch('main.save_config') as save:
            self.window.persist()
            stored = save.call_args.args[0]
            self.assertEqual(stored['layout'], 4)
            self.assertEqual(stored['slots'], original)
        self.window.persist_enabled = False

    def test_second_instance_activates_primary_and_does_not_get_lock(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, CAMFLOAT_DATA_DIR=folder):
            first, second = InstanceGuard(), InstanceGuard()
            activated = []
            first.activated.connect(lambda: activated.append(True))
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                QTest.qWait(100)
                self.assertEqual(activated, [True])
            finally:
                first.release()
                second.release()

    def test_idle_controls_hide_and_return_without_losing_selection(self):
        self.window.select_slot(0)
        overlay = self.window.tiles[0].overlay
        overlay.reveal_controls()
        self.assertFalse(overlay.label.isHidden())
        overlay.hide_idle_controls()
        self.assertTrue(overlay.label.isHidden())
        overlay.reveal_controls()
        self.assertFalse(overlay.label.isHidden())
        self.assertEqual(self.window.selected, 0)

    def test_minimum_four_pane_keeps_status_readable_and_hides_audio_bar(self):
        self.window.set_layout(4)
        self.window.resize(300, 180)
        self.app.processEvents()
        overlay = self.window.tiles[0].overlay
        overlay.reveal_controls()
        overlay.show_status('연결 끊김 · 2초 후 자동 재연결\n주소·비밀번호를 확인하세요')
        self.assertFalse(overlay.bar.isHidden())
        self.assertTrue(overlay.volume.isHidden())
        self.assertGreaterEqual(overlay.empty.height(), 40)
        self.assertNotIn('\n', overlay.empty.text())


class PlaybackRegressions(unittest.TestCase):
    def test_slow_stop_keeps_caller_responsive_and_coalesces_requests(self):
        entered, release = threading.Event(), threading.Event()

        class Media:
            def add_option(self, _): pass
            def release(self): pass

        class Fake:
            def __init__(self): self.starts = 0; self.released = False
            def media_new(self, _): return Media()
            def stop(self): entered.set(); release.wait(3)
            def set_media(self, _): pass
            def play(self): self.starts += 1; return 0
            def audio_set_volume(self, _): pass
            def audio_set_mute(self, _): pass
            def release(self): self.released = True

        fake = Fake()
        worker = PlaybackWorker(fake, fake)
        worker.request(('rtsp://host/a', True, 50, True))
        deadline = time.monotonic() + 2
        while fake.starts < 1 and time.monotonic() < deadline:
            time.sleep(.01)
        worker.request(None)
        self.assertTrue(entered.wait(2))
        start = time.monotonic()
        for i in range(30):
            worker.request((f'rtsp://host/{i}', True, 50, True))
        self.assertLess(time.monotonic() - start, .2)
        release.set()
        deadline = time.monotonic() + 2
        while worker.busy and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(fake.starts, 2)
        worker.shutdown()
        self.assertTrue(worker.done.wait(2))
        self.assertTrue(fake.released)


if __name__ == '__main__':
    unittest.main(verbosity=2)
