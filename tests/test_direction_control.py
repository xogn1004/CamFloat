"""Direction sessions use fake clients; no real camera access."""
import ipaddress
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from onvif_control import pulse
from ptz_metadata import defaults, validated, binding
from ptz_control import DirectionControl, eligible
from camera_model import default_config, new_camera, normalize, save_config, data_path
from camera_archive import encode, decode


class FakeClient:
    calls = []
    gate = None

    def __init__(self, camera):
        self.url = camera['url']
        self.ptz_path = '/onvif/deviceio_service'
        self.ptz_port = 5000
        self.profile_token = 'IPCProfilesToken0'

    def discover(self):
        if self.gate:
            self.gate.wait(1)
        return {'profile_verified': True}

    def step(self, pan, tilt=0, *, attempt=None):
        if attempt is not None:
            if attempt.cancelled.is_set() or not attempt.before_send():
                return {'cancelled': True, 'request_sent': False}
            attempt.on_event('write_started')
        self.calls.append(('ContinuousMove', pan, tilt))
        if attempt is not None:
            attempt.request_sent()
        return {'response_verified': True, 'request_sent': True}

    def control(self, operation, pan=None, on_sent=None, tilt=0):
        self.calls.append((operation, pan, tilt))
        if on_sent:
            on_sent()
        return {'response_verified': True}


class DirectionControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Synthetic RFC1918 address, never connected to by these tests.
        host = str(ipaddress.IPv4Address(0x0a000007))
        self.camera = {'id': 'synthetic', 'url': f'rtsp://user:synthetic@{host}/onvif1'}
        FakeClient.calls = []
        FakeClient.gate = None
        self.patch = patch('ptz_control.Client', FakeClient)
        self.patch.start()
        self.now = time.monotonic()
        self.control = DirectionControl(clock=lambda: self.now, diagnostics_enabled=False)

    def tearDown(self):
        self.control.shutdown()
        if FakeClient.gate:
            FakeClient.gate.set()
        self.assertTrue(self.control.done.wait(2))
        self.assertTrue(self.control.lookup_done.wait(2))
        self.app.processEvents()
        self.patch.stop()

    def wait_state(self, state):
        for _ in range(150):
            self.app.processEvents()
            if self.control.state == state:
                return
            QTest.qWait(10)
        self.fail(f'Expected {state}, got {self.control.state}')

    def test_eligibility_rejects_public_loopback_names_and_disabled(self):
        self.assertTrue(eligible(self.camera))
        for url in ('rtsp://127.0.0.1/onvif1', 'rtsp://example.com/onvif1',
                    'file:///sample.mp4', 'bad', 'rtsp://' + str(ipaddress.IPv4Address(0x08080808))):
            self.assertFalse(eligible(dict(self.camera, url=url)))
        self.assertFalse(eligible(dict(self.camera, enabled=False)))
        self.assertFalse(eligible(dict(self.camera, connection_locked=True)))

    def test_readiness_does_not_move_and_moves_do_not_queue(self):
        self.control.prepare(self.camera)
        self.wait_state('ready')
        self.assertEqual(FakeClient.calls, [])
        self.assertTrue(self.control.move(self.camera, 0, 1))
        self.assertFalse(self.control.move(self.camera, -1, 0))
        self.wait_state('ready')
        self.assertEqual([x for x in FakeClient.calls if x[0] == 'ContinuousMove'], [('ContinuousMove', 0, 1)])
        self.assertEqual([x[0] for x in FakeClient.calls].count('Stop'), 0)

    def test_cancelled_discovery_never_becomes_ready_or_moves(self):
        FakeClient.gate = threading.Event()
        self.control.prepare(self.camera)
        self.control.cancel()
        FakeClient.gate.set()
        self.wait_state('idle')
        self.assertIsNone(self.control.client)
        self.assertFalse(self.control.move(self.camera, 1, 0))
        self.assertEqual(FakeClient.calls, [])

    def test_wrong_camera_and_diagonal_never_send(self):
        self.control.prepare(self.camera)
        self.wait_state('ready')
        self.assertFalse(self.control.move(dict(self.camera, id='other'), 1, 0))
        self.assertFalse(self.control.move(self.camera, 1, 1))
        self.assertEqual(FakeClient.calls, [])

    def test_pre_cancelled_pulse_sends_nothing(self):
        cancelled = threading.Event()
        cancelled.set()
        result = pulse(FakeClient(self.camera), 1, cancelled=cancelled)
        self.assertTrue(result['cancelled'])
        self.assertEqual(FakeClient.calls, [])

    def test_cancel_during_move_discards_result_without_stop_or_extra_move(self):
        self.control.prepare(self.camera)
        self.wait_state('ready')
        self.control.move(self.camera, -1, 0)
        self.control.cancel()
        self.wait_state('idle')
        self.assertFalse(self.control.busy)
        self.assertIsNone(self.control.client)
        moves = [x for x in FakeClient.calls if x[0] == 'ContinuousMove']
        self.assertLessEqual(len(moves), 1)
        if moves:
            self.assertEqual([x[0] for x in FakeClient.calls].count('Stop'), 0)

    def test_open_uses_default_immediately_while_first_lookup_is_pending(self):
        FakeClient.gate = threading.Event()
        self.control.prepare(self.camera)
        self.assertEqual(self.control.state, 'ready')
        self.assertFalse(self.control.busy)
        self.assertEqual(self.control.client.ptz_path, '/onvif/deviceio_service')
        self.assertEqual(self.control.client.profile_token, 'IPCProfilesToken0')
        self.assertTrue(self.control.move(self.camera, 1, 0))
        self.wait_state('ready')

    def test_failed_initial_lookup_preserves_default_and_does_not_retry_on_reopen(self):
        with patch.object(FakeClient, 'discover', return_value={'profile_verified': False}) as query:
            self.control.prepare(self.camera)
            self.assertTrue(self.control.lookup_done.wait(1))
            self.app.processEvents()
            self.assertTrue(self.control.cache[(self.camera['id'], self.camera['url'])]['checked'])
            self.control.cancel()
            self.control.prepare(self.camera)
            self.assertEqual(query.call_count, 1)
            self.assertEqual(FakeClient.calls, [])

    def test_saved_route_is_used_and_stale_connection_binding_rejected(self):
        info = dict(defaults(self.camera), path='/custom/ptz', port=8080,
                    profile='other-profile', checked=True, source='device')
        camera = dict(self.camera, ptz=info)
        with patch.object(FakeClient, 'discover') as query:
            self.control.prepare(camera)
            self.assertEqual(self.control.client.ptz_path, '/custom/ptz')
            self.assertEqual(self.control.client.ptz_port, 8080)
            self.assertEqual(self.control.client.profile_token, 'other-profile')
            query.assert_not_called()
        self.assertIsNone(validated(info, dict(camera, url=camera['url'] + '?changed')))

    def test_reply_failure_refreshes_metadata_without_replaying_movement(self):
        camera = dict(self.camera, ptz=dict(defaults(self.camera), checked=True))
        with patch.object(FakeClient, 'step', return_value={'request_sent': True, 'response_verified': False, 'soap_fault': True}) as move:
            self.control.prepare(camera)
            self.control.move(camera, 1, 0)
            self.wait_state('move_error')
            self.assertTrue(self.control.lookup_done.wait(1))
            self.app.processEvents()
            self.assertEqual(move.call_count, 1)
            self.assertEqual(FakeClient.calls, [])

    def test_sent_without_reply_remains_ready_and_never_queries_or_replays(self):
        camera = dict(self.camera, ptz=dict(defaults(self.camera), checked=True))
        for response in ({'request_sent': True, 'response_verified': False, 'error': 'TimeoutError'},
                         {'request_sent': True, 'response_verified': False, 'error': 'RemoteDisconnected'},
                         {'request_sent': True, 'response_verified': False, 'http_status': 200}):
            with self.subTest(response=response), patch.object(FakeClient, 'step', return_value=response) as move, \
                    patch.object(FakeClient, 'discover') as query:
                self.now += 1
                self.control.prepare(camera)
                self.assertTrue(self.control.move(camera, 1, 0))
                self.wait_state('ready')
                self.assertEqual(self.control.last_reply, response)
                self.assertEqual(move.call_count, 1)
                query.assert_not_called()
                # An uncertain response must not be stored as verified support.
                self.assertNotEqual(self.control.hints(camera)['source'], 'confirmed')

    def test_unsent_or_explicitly_rejected_requests_are_still_failures(self):
        from ptz_control import delivery_failed
        for result in ({'request_sent': False, 'error': 'TimeoutError'},
                       {'request_sent': True, 'http_status': 401},
                       {'request_sent': True, 'http_status': 200, 'soap_fault': True}):
            self.assertTrue(delivery_failed(result))

    def test_metadata_is_encrypted_in_settings_and_not_exported(self):
        camera = new_camera('Synthetic', self.camera['url'])
        camera['ptz'] = dict(defaults(camera), profile='private-profile', checked=True)
        config = default_config()
        config['cameras'] = [camera]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, CAMFLOAT_DATA_DIR=folder):
            save_config(config)
            raw = data_path().read_text(encoding='utf-8')
            self.assertNotIn('private-profile', raw)
            self.assertNotIn('/onvif/deviceio_service', raw)
            self.assertEqual(normalize(json.loads(raw), encrypted=True)['cameras'][0]['ptz'], camera['ptz'])
        self.assertIsNone(decode(encode([camera]))[0]['ptz'])

    def test_malformed_or_damaged_metadata_does_not_break_camera(self):
        camera = new_camera('Synthetic', self.camera['url'])
        for bad in ({}, dict(defaults(camera), path='//example.com'),
                    dict(defaults(camera), port=0), dict(defaults(camera), profile='bad\n'), 'dpapi:broken'):
            camera['ptz'] = bad
            loaded = normalize(dict(cameras=[camera]), encrypted=isinstance(bad, str))
            self.assertEqual(loaded['cameras'][0]['url'], camera['url'])
            self.assertIsNone(loaded['cameras'][0]['ptz'])


if __name__ == '__main__':
    unittest.main()
