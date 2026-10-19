"""ONVIF metadata, digest and bounded-move tool checks without live devices."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools import camera_onvif_trial as trial


class ONVIFTrialTests(unittest.TestCase):
    def setUp(self):
        self.camera = dict(number=1, url='rtsp://user:secret@127.0.0.1:554/onvif1')

    def test_wsse_digest_and_xml_escape(self):
        parts = urlsplit('rtsp://a%26b:secret@127.0.0.1/onvif1')
        with patch.object(trial.secrets, 'token_bytes', return_value=b'n' * 16):
            raw = trial.envelope(parts, trial.MEDIA, 'GetProfiles')
        self.assertNotIn(b'secret', raw)
        root = ET.fromstring(raw)
        created = root.find('.//{' + trial.WSU + '}Created').text
        digest = root.find('.//{' + trial.WSSE + '}Password').text
        expected = base64.b64encode(hashlib.sha1(b'n' * 16 + created.encode() + b'secret').digest()).decode()
        self.assertEqual(digest, expected)
        self.assertEqual(root.find('.//{' + trial.WSSE + '}Username').text, 'a&b')

    def test_continuous_move_has_device_timeout_and_no_tilt_or_zoom(self):
        root = ET.fromstring(trial.envelope(urlsplit(self.camera['url']), trial.PTZ, 'ContinuousMove', 'token', -1))
        self.assertEqual(root.find('.//{' + trial.PTZ + '}Timeout').text, 'PT0.25S')
        self.assertEqual(root.find('.//{' + trial.SCHEMA + '}PanTilt').attrib, {'x': '-1', 'y': '0'})
        self.assertEqual(root.find('.//{' + trial.SCHEMA + '}Zoom').get('x'), '0')
        for op in ('SystemReboot', 'SetPreset', 'SetConfiguration'):
            with self.assertRaises(ValueError):
                trial.envelope(urlsplit(self.camera['url']), trial.DEVICE, op)

    def test_vertical_motion_moves_only_tilt_with_same_device_timeout(self):
        for sign in (-1, 1):
            root = ET.fromstring(trial.envelope(urlsplit(self.camera['url']), trial.PTZ,
                                                'ContinuousMove', 'token', 0, sign))
            self.assertEqual(root.find('.//{' + trial.SCHEMA + '}PanTilt').attrib, {'x': '0', 'y': str(sign)})
            self.assertEqual(root.find('.//{' + trial.SCHEMA + '}Zoom').get('x'), '0')
            self.assertEqual(root.find('.//{' + trial.PTZ + '}Timeout').text, 'PT0.25S')

    def test_diagonal_zero_and_out_of_range_movement_rejected(self):
        for pan, tilt in ((1, 1), (0, 0), (0, 2), (2, 0), (None, 1), (True, 0), (1.0, 0)):
            with self.subTest(pan=pan, tilt=tilt), self.assertRaises(ValueError):
                trial.envelope(urlsplit(self.camera['url']), trial.PTZ, 'ContinuousMove', 'token', pan, tilt)

    def test_preset_query_requires_profile_but_does_not_change_it(self):
        with self.assertRaises(ValueError):
            trial.envelope(urlsplit(self.camera['url']), trial.PTZ, 'GetPresets')
        raw = trial.envelope(urlsplit(self.camera['url']), trial.PTZ, 'GetPresets', 'profile-token')
        root = ET.fromstring(raw)
        self.assertEqual(root.find('.//{' + trial.PTZ + '}ProfileToken').text, 'profile-token')
        self.assertIsNone(root.find('.//{' + trial.PTZ + '}SetPreset'))

    def test_service_address_must_stay_on_same_device(self):
        self.assertEqual(trial.service_path('http://127.0.0.1:5000/onvif/deviceio_service', '127.0.0.1'), '/onvif/deviceio_service')
        self.assertEqual(trial.service_path('http://127.0.0.1:8080/custom/ptz', '127.0.0.1'), '/custom/ptz')
        for url in ('http://example.com:5000/onvif/ptz', 'http://127.0.0.1:5000//other',
                    'http://u:p@127.0.0.1:5000/onvif/ptz', 'http://127.0.0.1:5000',
                    'http://127.0.0.1:5000/onvif/ptz?data=secret'):
            with self.assertRaises(ValueError):
                trial.service_path(url, '127.0.0.1')

    def test_200_without_expected_soap_response_is_not_success(self):
        class Response:
            status = 200
            def read(self, size):
                return f'<s:Envelope xmlns:s="{trial.SOAP}"><s:Body/></s:Envelope>'.encode()
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        result, _ = trial.Client(self.camera, Connection).call('/onvif/device_service', trial.DEVICE, 'GetCapabilities')
        self.assertTrue(result['request_sent'])
        self.assertFalse(result['response_verified'])

    def test_app_step_has_timeout_and_never_sends_stop_or_discovery(self):
        calls = []
        class Response:
            status = 200
            def read(self, size):
                return f'<s:Envelope xmlns:s="{trial.SOAP}"><s:Body><p:ContinuousMoveResponse xmlns:p="{trial.PTZ}"/></s:Body></s:Envelope>'.encode()
        class Connection:
            def __init__(self, host, port, timeout): calls.append(('connection', port, timeout))
            def request(self, method, path, body, headers): calls.append(('request', path, body))
            def getresponse(self): return Response()
            def close(self): pass
        client = trial.Client(self.camera, Connection)
        client.ptz_path, client.ptz_port, client.profile_token = '/custom/ptz', 8080, 'profile'
        result = client.step(0, 1)
        self.assertTrue(result['response_verified'])
        self.assertEqual(calls[0], ('connection', 8080, .15))
        requests = [c for c in calls if c[0] == 'request']
        self.assertEqual(len(requests), 1)
        root = ET.fromstring(requests[0][2])
        self.assertEqual(root.find('.//{' + trial.PTZ + '}Timeout').text, 'PT0.25S')
        self.assertIsNone(root.find('.//{' + trial.PTZ + '}Stop'))

    def test_manual_duration_is_bounded_and_step_default_stays_unchanged(self):
        for duration, expected in ((250, 'PT0.25S'), (1000, 'PT1S'), (2000, 'PT2S')):
            root = ET.fromstring(trial.envelope(urlsplit(self.camera['url']), trial.PTZ,
                'ContinuousMove', 'token', -1, device_timeout_ms=duration))
            self.assertEqual(root.find('.//{' + trial.PTZ + '}Timeout').text, expected)
        for duration in (0, 249, 2001, True, 1000.0, '1000'):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                trial.envelope(urlsplit(self.camera['url']), trial.PTZ,
                    'ContinuousMove', 'token', -1, device_timeout_ms=duration)

    def test_continuous_comparison_sends_only_one_move_and_stops_independently(self):
        calls = []
        stopped = threading.Event()
        class Client:
            ptz_path = '/custom/ptz'
            def call(self, path, namespace, operation, **kwargs):
                calls.append((operation, kwargs))
                if operation == 'ContinuousMove':
                    kwargs['on_sent']()
                    # The independent Stop must run while the move reply waits.
                    if not stopped.wait(2):
                        raise AssertionError('Stop waited for movement response')
                else:
                    stopped.set()
                return {'request_sent': True, 'response_verified': False}, None
        result = trial.continuous_trial(Client(), 0, 1, 250)
        self.assertEqual([c[0] for c in calls], ['ContinuousMove', 'Stop', 'Stop'])
        self.assertEqual(calls[0][1]['device_timeout_ms'], 250)
        self.assertEqual(calls[0][1]['tilt'], 1)
        self.assertEqual(result['move_requests'], 1)
        self.assertEqual(result['physical_result'], 'unconfirmed')

    def test_continuous_comparison_interrupt_still_stops(self):
        calls = []
        class Client:
            ptz_path = '/custom/ptz'
            def call(self, path, namespace, operation, **kwargs):
                calls.append(operation)
                if operation == 'ContinuousMove':
                    kwargs['on_sent']()
                    raise KeyboardInterrupt()
                return {'request_sent': True, 'response_verified': False}, None
        with self.assertRaises(KeyboardInterrupt):
            trial.continuous_trial(Client(), -1, 0, 2000)
        self.assertEqual(calls, ['ContinuousMove', 'Stop', 'Stop'])

    def test_continuous_comparison_invalid_input_sends_nothing(self):
        from unittest.mock import Mock
        client = Mock()
        for pan, tilt, duration in ((0, 0, 250), (1, 1, 250), (1, 0, 300),
                                    (1, 0, 3000), (1, 0, 250.0)):
            with self.subTest(pan=pan, tilt=tilt, duration=duration), self.assertRaises(ValueError):
                trial.continuous_trial(client, pan, tilt, duration)
        client.call.assert_not_called()

    def test_continuous_menu_exit_never_moves_or_touches_settings(self):
        from unittest.mock import Mock
        client = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)), \
                patch('builtins.input', side_effect=['2', 'q']), redirect_stdout(io.StringIO()):
            self.assertEqual(trial.continuous_menu(client, self.camera, 0), 0)
            self.assertEqual(list(Path(folder).iterdir()), [])
        client.call.assert_not_called()

    def test_disconnect_is_unconfirmed_and_does_not_expose_credentials(self):
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): raise trial.http.client.RemoteDisconnected('secret')
            def close(self): pass
        result, _ = trial.Client(self.camera, Connection).call('/onvif/device_service', trial.DEVICE, 'GetCapabilities')
        self.assertFalse(result['response_verified'])
        self.assertTrue(result['request_sent'])
        self.assertEqual(result['error'], 'RemoteDisconnected')
        self.assertNotIn('secret', json.dumps(result))

    def test_discovery_uses_profile_from_device_and_restricts_targets(self):
        class Client(trial.Client):
            def call(self, path, namespace, operation, *args, **kwargs):
                if operation == 'GetCapabilities':
                    raw = f'<Capabilities xmlns="{trial.SCHEMA}"><Media><XAddr>http://127.0.0.1:5000/onvif/media_service</XAddr></Media><PTZ><XAddr>http://127.0.0.1:5000/onvif/deviceio_service</XAddr></PTZ></Capabilities>'
                else:
                    raw = f'<trt:GetProfilesResponse xmlns:trt="{trial.MEDIA}" xmlns:tt="{trial.SCHEMA}"><trt:Profiles token="actual-token"><tt:PTZConfiguration token="config"/></trt:Profiles></trt:GetProfilesResponse>'
                return {'response_verified': True}, ET.fromstring(raw)
        client = Client(self.camera)
        result = client.discover()
        self.assertTrue(result['profile_verified'])
        self.assertEqual(client.profile_token, 'actual-token')
        self.assertEqual(client.ptz_path, '/onvif/deviceio_service')
        self.assertNotIn('actual-token', json.dumps(result))

    def test_stop_runs_after_disconnect_during_movement(self):
        calls = []
        class Client:
            def control(self, operation, pan=None, on_sent=None, tilt=0):
                calls.append(operation)
                if on_sent:
                    on_sent()
                return {'request_sent': True, 'response_verified': False, 'error': 'RemoteDisconnected'}
        result = trial.pulse(Client(), -1)
        self.assertEqual(calls.count('Stop'), 2)
        self.assertFalse(result['move']['response_verified'])
        self.assertEqual(result['physical_result'], 'unconfirmed')

    def test_final_stop_on_interrupted_move(self):
        calls = []
        class Client:
            def control(self, operation, pan=None, on_sent=None, tilt=0):
                calls.append(operation)
                if operation == 'ContinuousMove':
                    on_sent()
                    raise KeyboardInterrupt()
                return {'response_verified': False}
        with self.assertRaises(KeyboardInterrupt):
            trial.pulse(Client(), 1)
        self.assertEqual(calls.count('Stop'), 2)

    def test_vertical_pulse_preserves_stop_requests_and_axis_evidence(self):
        calls = []
        class Client:
            def control(self, operation, pan=None, on_sent=None, tilt=0):
                calls.append((operation, pan, tilt))
                if on_sent:
                    on_sent()
                return {'request_sent': True, 'response_verified': False}
        result = trial.pulse(Client(), 0, -1)
        self.assertEqual(calls[0], ('ContinuousMove', 0, -1))
        self.assertEqual([op for op, _, _ in calls].count('Stop'), 2)
        self.assertEqual((result['pan_sign'], result['tilt_sign']), (0, -1))
        self.assertEqual(result['physical_result'], 'unconfirmed')

    def test_new_session_keeps_previous_physical_observations(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)):
            evidence = {'camera_number': 1, 'physical_result': 'moved_and_stopped'}
            trial.save([evidence])
            class Client:
                def __init__(self, camera): pass
                def discover(self): return {'profile_verified': False}
            with patch.object(trial, 'load_cameras', return_value=[self.camera]), \
                    patch.object(trial, 'Client', Client), patch('builtins.input', return_value='1'), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(trial.main([]), 1)
            self.assertEqual(trial.previous_results()[0], evidence)
            self.assertEqual(len(trial.previous_results()), 2)

    def test_invalid_delay_rejected_before_camera_access(self):
        for value in ('-1', '301', 'abc'):
            with self.subTest(value=value), patch.object(trial, 'load_cameras') as load, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                trial.main(['--delay', value])
            self.assertEqual(error.exception.code, 2)
            load.assert_not_called()

    def test_probe_report_preserves_manual_motion_observations(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)):
            trial.save([{'physical_result': 'moved_and_stopped'}])
            trial.save([{'capabilities_verified': True}], probe=True)
            base = Path(folder) / 'verification/current/camera-control'
            self.assertEqual(json.loads((base / 'onvif-manual-latest.json').read_text()), [{'physical_result': 'moved_and_stopped'}])
            self.assertEqual(json.loads((base / 'onvif-probe-latest.json').read_text()), [{'capabilities_verified': True}])


if __name__ == '__main__':
    unittest.main()
