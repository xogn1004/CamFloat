"""Short checks using synthetic cameras and no live network connections."""
import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from camera_archive import decode, encode
from camera_draft import split_address_port
from camera_model import (data_path, default_config, find_vlc_directory, load_config,
                          make_vlc_instance, new_camera, normalize, save_config)
from main import PlayerWindow, VERSION

ROOT = Path(__file__).resolve().parents[1]


class QuickChecks(unittest.TestCase):
    def test_defaults_and_layout_assignments(self):
        config = normalize(dict(cameras=[new_camera('Synthetic', 'rtsp://127.0.0.1/onvif1')]))
        self.assertFalse(config['always_on_top'])
        self.assertEqual(config['opacity'], 80)
        self.assertEqual(config['layout'], 1)
        self.assertEqual(set(config['layout_slots']), {'1', '2', '4'})

    def test_settings_roundtrip_is_encrypted(self):
        config = default_config()
        config['cameras'] = [new_camera('Synthetic', 'rtsp://user:synthetic@127.0.0.1/onvif1')]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, CAMFLOAT_DATA_DIR=folder):
            save_config(config)
            self.assertNotIn('synthetic@', data_path().read_text(encoding='utf-8'))
            self.assertEqual(load_config()['cameras'][0]['url'], config['cameras'][0]['url'])

    def test_archive_does_not_transfer_audio(self):
        camera = new_camera('Synthetic', 'rtsp://user:synthetic@127.0.0.1/onvif1')
        camera.update(volume=0, muted=True)
        restored = decode(encode([camera]))[0]
        self.assertEqual(restored['volume'], 100)
        self.assertFalse(restored['muted'])

    def test_registration_host_port(self):
        self.assertEqual(split_address_port('example.com:15554', 554), ('example.com', 15554))

    def test_version_metadata_agrees(self):
        tree = ast.parse((ROOT / 'version_info.txt').read_text(encoding='utf-8'))
        strings = {node.args[0].value: node.args[1].value for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == 'StringStruct'}
        self.assertEqual(strings['FileVersion'], VERSION)
        self.assertEqual(strings['ProductVersion'], VERSION)
        fixed = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'FixedFileInfo')
        flags = next(ast.literal_eval(k.value) for k in fixed.keywords if k.arg == 'flags')
        self.assertEqual(bool(flags & 2), '-dev.' in VERSION or '-rc.' in VERSION)

    def test_player_start_close_without_camera(self):
        app = QApplication.instance() or QApplication([])
        instance = make_vlc_instance(find_vlc_directory())
        window = None
        try:
            window = PlayerWindow(default_config(), instance, persist=False)
            window.show()
            app.processEvents()
            self.assertTrue(window.isVisible())
            self.assertIsNone(window.camera_for_slot(0))
        finally:
            if window is not None:
                window.close()
                for _ in range(200):
                    app.processEvents()
                    if all(tile.worker.done.is_set() for tile in window.tiles):
                        break
                    QTest.qWait(10)
                self.assertTrue(all(tile.worker.done.is_set() for tile in window.tiles))
                window.close()
                window.deleteLater()
                app.processEvents()
            instance.release()
