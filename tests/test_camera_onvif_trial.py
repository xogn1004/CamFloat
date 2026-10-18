"""ONVIF metadata, digest and bounded-move tool checks without live devices."""
import base64
import hashlib
import json
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

    def test_service_address_must_stay_on_same_device_and_known_port(self):
        self.assertEqual(trial.service_path('http://127.0.0.1:5000/onvif/deviceio_service', '127.0.0.1'), '/onvif/deviceio_service')
        for url in ('http://example.com:5000/onvif/ptz', 'http://127.0.0.1:80/onvif/ptz',
                    'http://u:p@127.0.0.1:5000/onvif/ptz', 'http://127.0.0.1:5000/other',
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
            def control(self, operation, pan=None, on_sent=None):
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
            def control(self, operation, pan=None, on_sent=None):
                calls.append(operation)
                if operation == 'ContinuousMove':
                    on_sent()
                    raise KeyboardInterrupt()
                return {'response_verified': False}
        with self.assertRaises(KeyboardInterrupt):
            trial.pulse(Client(), 1)
        self.assertEqual(calls.count('Stop'), 2)


if __name__ == '__main__':
    unittest.main()
