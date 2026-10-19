"""Manual compatibility experiments use fake devices only."""
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from onvif_control import Client, PTZ, SCHEMA
from tools import camera_onvif_compat as compat
from tools import camera_onvif_trial as trial


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.camera = dict(number=1, url='rtsp://user:secret@127.0.0.1/onvif1')
        self.client = compat.CompatibilityClient(self.camera)
        self.client.ptz_path = '/custom/ptz'
        self.client.profile_token = 'test-profile'

    def root(self, operation, pan=None, tilt=0):
        return ET.fromstring(self.client.build_envelope(PTZ, operation, pan, tilt, 250))

    def test_minimal_move_omits_timeout_and_zoom(self):
        root = self.root('ContinuousMove', -1)
        self.assertEqual(root.find('.//{' + SCHEMA + '}PanTilt').attrib, {'x': '-1.0', 'y': '0.0'})
        self.assertIsNone(root.find('.//{' + SCHEMA + '}Zoom'))
        self.assertIsNone(root.find('.//{' + PTZ + '}Timeout'))
        self.assertEqual(root.find('.//{' + PTZ + '}ProfileToken').text, 'test-profile')
        self.assertNotIn(b'secret', ET.tostring(root))

    def test_wire_request_uses_compatibility_envelope_and_bounded_socket(self):
        captured = []
        class Response:
            status = 200
            def read(self, size):
                return f'<s:Envelope xmlns:s="{compat.SOAP}"><s:Body><p:ContinuousMoveResponse xmlns:p="{PTZ}"/></s:Body></s:Envelope>'.encode()
        class Connection:
            def __init__(self, host, port, timeout):
                captured.append(('connection', port, timeout))
            def request(self, method, path, body, headers):
                captured.append(('body', body))
            def getresponse(self): return Response()
            def close(self): captured.append(('closed',))
        self.client.connection_factory = Connection
        self.client.stop_format = 'zero'
        result = self.client.request_stop()
        self.assertTrue(result['response_verified'])
        self.assertEqual(captured[0], ('connection', 5000, .3))
        root = ET.fromstring(captured[1][1])
        self.assertEqual(root.find('.//{' + SCHEMA + '}PanTilt').get('x'), '0.0')
        self.assertIsNone(root.find('.//{' + PTZ + '}Timeout'))
        self.assertEqual(captured[-1], ('closed',))

    def test_minimal_stop_keeps_profile_and_omits_optional_axes(self):
        stop = self.root('Stop').find('.//{' + PTZ + '}Stop')
        self.assertEqual([c.tag for c in stop], ['{' + PTZ + '}ProfileToken'])

    def test_zero_stop_is_explicit_and_does_not_weaken_app_validation(self):
        with self.assertRaises(ValueError):
            self.root('ContinuousMove', 0)
        self.client.stop_format = 'zero'
        axes = self.root('ContinuousMove', 0).find('.//{' + SCHEMA + '}PanTilt')
        self.assertEqual(axes.attrib, {'x': '0.0', 'y': '0.0'})
        regular = Client(self.camera)
        regular.profile_token = 'profile'
        with self.assertRaises(ValueError):
            regular.build_envelope(PTZ, 'ContinuousMove', 0, 0, 250)

    def test_explicit_space_uses_only_generic_velocity_space(self):
        self.client.move_format = 'space'
        axes = self.root('ContinuousMove', 0, 1).find('.//{' + SCHEMA + '}PanTilt')
        self.assertEqual(axes.get('x'), '0.0')
        self.assertEqual(axes.get('y'), '1.0')
        self.assertTrue(axes.get('space').endswith('/PanTiltSpaces/VelocityGenericSpace'))

    def test_invalid_variant_and_direction_never_send(self):
        client = Mock()
        for variant, pan, tilt in (('unknown', 1, 0), ('1', 1, 1), ('2', 0, 0)):
            with self.assertRaises(ValueError):
                compat.compare(client, variant, pan, tilt)
        client.call.assert_not_called()

    def test_stop_runs_while_move_reply_is_waiting_and_only_one_nonzero_move(self):
        stopped = threading.Event()
        calls = []
        class FakeClient:
            ptz_path = '/custom/ptz'
            def call(self, path, namespace, operation, **kwargs):
                calls.append((operation, kwargs.get('pan')))
                if operation == 'ContinuousMove':
                    kwargs['on_sent']()
                    if not stopped.wait(3):
                        raise AssertionError('Stop did not run independently')
                return {'request_sent': True, 'response_verified': False}, None
            def request_stop(self):
                calls.append(('zero_stop', 0))
                stopped.set()
                return {'request_sent': True, 'response_verified': False}
        result = compat.compare(FakeClient(), '2', -1, 0)
        self.assertEqual(calls, [('ContinuousMove', -1), ('zero_stop', 0),
                                 ('zero_stop', 0), ('Stop', None)])
        self.assertEqual(result['physical_result'], 'unconfirmed')
        self.assertEqual(result['move_requests'], 1)

    def test_interruption_runs_stop_and_fallback(self):
        client = Mock(ptz_path='/custom/ptz')
        def call(path, namespace, operation, **kwargs):
            if operation == 'ContinuousMove':
                kwargs['on_sent']()
                raise KeyboardInterrupt()
            return {'request_sent': True, 'response_verified': False}, None
        client.call.side_effect = call
        with self.assertRaises(KeyboardInterrupt):
            compat.compare(client, '1', 1, 0)
        self.assertEqual(client.request_stop.call_count, 2)
        self.assertEqual(client.call.call_args.args[2], 'Stop')

    def test_menu_selection_and_exit_never_send(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as folder, \
                patch('builtins.input', side_effect=['2', '3', 'q']), redirect_stdout(io.StringIO()):
            self.assertEqual(compat.menu(client, self.camera, 0, folder), 0)
            self.assertEqual(list(Path(folder).iterdir()), [])
        client.call.assert_not_called()
        client.request_stop.assert_not_called()

    def test_nonstop_observation_ends_session_and_preserves_report(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(compat, 'compare', return_value={}), \
                patch('builtins.input', side_effect=['l', 'x']), redirect_stdout(io.StringIO()):
            self.assertEqual(compat.menu(client, self.camera, 0, folder), 1)
            records = compat.load_history(Path(folder) / 'verification/current/camera-control/compat-manual-latest.json')
            self.assertEqual(records[0]['physical_result'], 'did_not_stop')

    def test_probe_and_comparison_cannot_be_combined(self):
        with patch.object(trial, 'load_cameras') as load, redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            trial.main(['--probe', '--compat'])
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
