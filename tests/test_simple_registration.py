"""Focused simple-registration checks; synthetic addresses, no camera access."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QDialog
from camera_draft import split_address_port
from camera_editor import CameraEditor
from camera_model import new_camera


class AddressTests(unittest.TestCase):
    def test_host_only_keeps_port_field(self):
        self.assertEqual(split_address_port('  example.com  ', 15554), ('example.com', 15554))

    def test_pasted_host_port_and_ipv6(self):
        for value, expected in [
            ('127.0.0.1:18554', ('127.0.0.1', 18554)),
            ('example.com:15555', ('example.com', 15555)),
            ('[::1]:18554', ('::1', 18554)),
            ('[::1]', ('::1', 554)),
            ('::1', ('::1', 554)),
            ('2001:db8::554', ('2001:db8::554', 554)),
        ]:
            with self.subTest(value=value):
                self.assertEqual(split_address_port(value, 554), expected)

    def test_invalid_ports_and_full_urls_stay_rejected(self):
        for value in ('example.com:', 'example.com:0', 'example.com:65536',
                      'example.com:abc', 'example.com:-1', '[::1]:', '[::1]:0',
                      '[::1]junk', '[::1', 'rtsp://example.com:554/onvif1',
                      'example.com/onvif1', 'user@example.com:554', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                split_address_port(value, 554)


class SimpleRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = CameraEditor()

    def tearDown(self):
        self.editor.done(QDialog.DialogCode.Rejected)
        self.editor.deleteLater()
        self.app.processEvents()

    def test_check_button_splits_pasted_port_and_passes_encoded_url_to_probe(self):
        e = self.editor
        e.host.setText('127.0.0.1:18554')
        e.password.setText('test@:/!')
        with patch('camera_editor.find_vlc_directory', return_value=Path('synthetic-engine')), \
                patch.object(e.probe, 'start') as start:
            e.check.click()
        start.assert_called_once()
        url, folder = start.call_args.args
        self.assertEqual(e.host.text(), '127.0.0.1')
        self.assertEqual(e.port.value(), 18554)
        self.assertEqual(urlsplit(url).port, 18554)
        self.assertEqual(unquote(urlsplit(url).password), 'test@:/!')
        self.assertEqual(folder, Path('synthetic-engine'))

    def test_separate_port_field_and_default_port_both_check(self):
        for port in (554, 15554):
            e = self.editor
            e.host.setText('127.0.0.1')
            e.port.setValue(port)
            with patch('camera_editor.find_vlc_directory', return_value=Path('synthetic-engine')), \
                    patch.object(e.probe, 'start') as start:
                e.check_connection()
            self.assertEqual(urlsplit(start.call_args.args[0]).port, port)

    def test_control_port_is_independent_and_survives_input_mode_changes(self):
        e = self.editor
        e.host.setText('example.com')
        e.port.setValue(15554)
        self.assertEqual(e.control_port.value(), 5000)
        e.control_port.setValue(25554)
        e.advanced.setChecked(True)
        e.mode.setCurrentIndex(1)
        result = e.collect()
        self.assertEqual(result['control_port'], 25554)
        self.assertEqual(urlsplit(result['url']).port, 15554)
        e.mode.setCurrentIndex(0)
        self.assertEqual(e.collect()['control_port'], 25554)
        from ptz_metadata import defaults
        e.camera = dict(result, ptz=dict(defaults(result), checked=True))
        e.control_port.setValue(25555)
        self.assertIsNone(e.collect()['ptz'])

    def test_add_and_mode_switch_use_the_same_normalized_address(self):
        e = self.editor
        e.host.setText('example.com:15555')
        e.mode.setCurrentIndex(1)
        self.assertEqual(urlsplit(e.full_url.text()).port, 15555)
        e.mode.setCurrentIndex(0)
        e.validate()
        self.assertEqual(e.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(urlsplit(e.camera['url']).port, 15555)

    def test_invalid_port_reports_error_without_launching_probe(self):
        e = self.editor
        for address in ('example.com:0', 'example.com:', 'example.com:65536'):
            e.host.setText(address)
            with patch.object(e, 'show_error') as error, patch.object(e.probe, 'start') as start:
                e.check_connection()
            error.assert_called_once()
            start.assert_not_called()

    def test_sd_probe_keeps_pasted_port(self):
        e = self.editor
        e.host.setText('127.0.0.1:18554')
        e.quality.setCurrentText('SD')
        with patch('camera_editor.find_vlc_directory', return_value=Path('synthetic-engine')), \
                patch.object(e.probe, 'start') as start:
            e.check_connection()
        self.assertEqual(urlsplit(start.call_args.args[0]).port, 18554)
        self.assertEqual(urlsplit(start.call_args.args[0]).path, '/onvif2')

    def test_existing_url_keeps_original_credential_encoding(self):
        original = 'rtsp://viewer:synthetic%21@127.0.0.1:8554/onvif1'
        e = CameraEditor(new_camera('테스트', original))
        try:
            e.host.setText('127.0.0.1:8554')
            self.assertEqual(e.collect()['url'], original)
        finally:
            e.done(QDialog.DialogCode.Rejected)
            e.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
