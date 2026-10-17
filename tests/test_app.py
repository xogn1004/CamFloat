import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QRect, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from camera_model import (build_url, crypt, data_path, default_config, find_vlc_directory,
    load_config, make_vlc_instance, new_camera, normalize, save_config, stream_url_for_quality)
from dialogs import CameraEditor, CameraManager
from main import PlayerWindow
from native_window import is_topmost


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.old_env = os.environ.get('CAMFLOAT_DATA_DIR')
        os.environ['CAMFLOAT_DATA_DIR'] = self.temporary.name

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop('CAMFLOAT_DATA_DIR', None)
        else:
            os.environ['CAMFLOAT_DATA_DIR'] = self.old_env
        self.temporary.cleanup()

    def test_migrate_order_credentials_audio_and_backup(self):
        one = dict(name='거실', url=crypt('rtsp://admin:a%40b@127.0.0.1:554/onvif1'),
                   quality='HD', volume=42, muted=True)
        two = dict(name='현관', url=crypt('rtsp://admin:second@127.0.0.2:554/onvif1'),
                   quality='SD', volume=70, muted=False)
        old = dict(streams=[one, dict(url=''), two, dict(url='')], order=[2, 0, 1, 3], layout=2)
        data_path().write_text(json.dumps(old), encoding='utf-8')
        config = load_config()
        self.assertEqual([c['name'] for c in config['cameras']], ['현관', '거실'])
        self.assertEqual(config['cameras'][1]['volume'], 42)
        self.assertTrue(config['cameras'][1]['muted'])
        save_config(config)
        self.assertTrue(data_path().with_name('settings-v1.backup.json').exists())
        self.assertNotIn('second@', data_path().read_text(encoding='utf-8'))
        self.assertEqual(load_config(), config)

    def test_special_characters_and_custom_rtsp_path(self):
        password = 'pw@:/#한글'
        url = build_url('example.com', 15554, 'admin', password)
        self.assertEqual(unquote(urlsplit(url).password), password)
        self.assertEqual(urlsplit(url).port, 15554)
        self.assertTrue(stream_url_for_quality(url, 'SD').endswith('/onvif2'))
        custom = 'rtsp://admin:pw@example.com:554/custom/channel?video=1'
        self.assertEqual(stream_url_for_quality(custom, 'SD'), custom)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.instance = make_vlc_instance(find_vlc_directory())
        sample = Path(__file__).resolve().parents[1] / 'sample-test.mp4'
        cls.video = QUrl.fromLocalFile(str(sample)).toString()

    @classmethod
    def tearDownClass(cls):
        cls.instance.release()

    def setUp(self):
        config = default_config()
        config['cameras'] = [new_camera(f'테스트 {i + 1}', self.video) for i in range(6)]
        for camera in config['cameras']:
            camera['muted'] = True
        config['slots'] = [c['id'] for c in config['cameras'][:4]]
        config['layout'] = 2
        self.window = PlayerWindow(config, self.instance, persist=False)
        self.window.show()
        QTest.qWait(1000)

    def tearDown(self):
        self.window.close()
        for _ in range(100):
            self.app.processEvents()
            if all(tile.worker.done.is_set() for tile in self.window.tiles):
                break
            QTest.qWait(20)
        self.assertTrue(all(tile.worker.done.is_set() for tile in self.window.tiles))
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_video_survives_topmost_and_opacity_without_recreating_handles(self):
        self.assertTrue(self.window.tiles[0].player.is_playing())
        handles = [int(tile.winId()) for tile in self.window.tiles]
        for enabled in (False, True, False, True):
            self.window.set_always_on_top(enabled)
            self.app.processEvents()
            self.assertEqual(is_topmost(self.window), enabled)
            self.assertEqual(handles, [int(tile.winId()) for tile in self.window.tiles])
            self.assertTrue(self.window.tiles[0].player.is_playing())
        for opacity in (100, 60, 20, 100):
            self.window.set_opacity(opacity)
            self.app.processEvents()
            self.assertAlmostEqual(self.window.windowOpacity(), opacity / 100, delta=.01)
            for tile in self.window.tiles[:2]:
                self.assertAlmostEqual(tile.overlay.windowOpacity(), opacity / 100, delta=.01)
            self.assertEqual(handles, [int(tile.winId()) for tile in self.window.tiles])

    def test_layout_selection_menus_and_independent_audio(self):
        for count in (1, 2, 4):
            self.window.set_layout(count)
            self.app.processEvents()
            self.assertEqual(sum(t.overlay.isVisible() for t in self.window.tiles), count)
            for index, tile in enumerate(self.window.tiles[:count]):
                self.assertEqual(tile.overlay.geometry(), QRect(tile.mapToGlobal(QPoint(0, 0)), tile.size()))
                QTest.mouseClick(tile.overlay, Qt.MouseButton.LeftButton, pos=tile.overlay.rect().center())
                self.assertEqual(self.window.selected, index)
                menu = self.window.build_context_menu(index)
                self.assertIn(self.window.camera_for_slot(index)['name'], menu.actions()[0].text())
                self.assertTrue(any(a.text() == '이 영상 음량' for a in menu.actions()))
                self.assertEqual(any(a.text() == '이 화면만 크게 보기' for a in menu.actions()), count > 1)
                menu.deleteLater()
        second = copy.deepcopy(self.window.camera_for_slot(1))
        self.window.set_volume(0, 31)
        self.window.toggle_mute(0)
        self.assertEqual(self.window.camera_for_slot(0)['volume'], 31)
        self.assertEqual(self.window.camera_for_slot(1), second)

    def test_geometry_edges_and_registry_assignment(self):
        start = QRect(100, 100, 800, 450)
        self.window.drag_geometry(start, QPoint(120, 60), ())
        self.assertEqual(self.window.geometry(), QRect(220, 160, 800, 450))
        self.window.drag_geometry(start, QPoint(100, 50), ('right', 'bottom'))
        self.assertEqual(self.window.size().width(), 900)
        self.assertEqual(self.window.size().height(), 500)
        self.window.drag_geometry(start, QPoint(1000, 1000), ('left', 'top'))
        self.assertEqual(self.window.size(), self.window.minimumSize())
        cameras = list(reversed(self.window.config['cameras']))
        previous_slots = list(self.window.config['slots'])
        self.window.apply_camera_registry(cameras)
        self.assertEqual(self.window.config['slots'], previous_slots)
        self.window.assign_camera(0, cameras[5]['id'])
        self.assertEqual(self.window.camera_for_slot(0)['id'], cameras[5]['id'])
        self.assertEqual(len(self.window.config['cameras']), 6)

    def test_manager_reorder_cancel_isolation_and_editor_url_preserved(self):
        original = copy.deepcopy(self.window.config['cameras'])
        manager = CameraManager(original, self.window)
        manager.table.selectRow(5)
        manager.move_camera(-1)
        self.assertEqual(manager.cameras[4]['id'], original[5]['id'])
        self.assertEqual(self.window.config['cameras'], original)
        manager.close()
        manager.deleteLater()
        camera = new_camera('custom', 'rtsp://admin:a%40b@example.com:15554/custom?query=one')
        editor = CameraEditor(camera, self.window)
        self.assertEqual(editor.full_url.text(), camera['url'])
        editor.name.setText('별명 수정')
        editor.validate()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(editor.camera['url'], camera['url'])
        self.assertEqual(editor.camera['name'], '별명 수정')
        editor.close()
        editor.deleteLater()

    def test_registration_simple_mode_and_mode_switch(self):
        editor = CameraEditor(parent=self.window)
        editor.name.setText('새 카메라')
        editor.host.setText('example.com')
        editor.port.setValue(15554)
        editor.password.setText('test@pw:/#')
        editor.mode.setCurrentIndex(1)
        self.assertEqual(unquote(urlsplit(editor.full_url.text()).password), 'test@pw:/#')
        editor.mode.setCurrentIndex(0)
        editor.validate()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(editor.camera['name'], '새 카메라')
        self.assertEqual(urlsplit(editor.camera['url']).port, 15554)
        self.assertEqual(unquote(urlsplit(editor.camera['url']).password), 'test@pw:/#')
        editor.close()
        editor.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
