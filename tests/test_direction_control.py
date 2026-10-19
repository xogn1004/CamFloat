"""Direction sessions use fake clients; no real camera access."""
import ipaddress
import threading
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from onvif_control import pulse
from ptz_control import DirectionControl, eligible


class FakeClient:
    calls = []
    gate = None

    def __init__(self, camera):
        self.url = camera['url']

    def discover(self):
        if self.gate:
            self.gate.wait(1)
        return {'profile_verified': True}

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
        self.control = DirectionControl()

    def tearDown(self):
        self.control.shutdown()
        if FakeClient.gate:
            FakeClient.gate.set()
        self.assertTrue(self.control.done.wait(2))
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
        self.assertEqual([x[0] for x in FakeClient.calls].count('Stop'), 2)

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

    def test_cancel_during_move_requests_stop_and_discards_ready_result(self):
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
            self.assertEqual([x[0] for x in FakeClient.calls].count('Stop'), 2)


if __name__ == '__main__':
    unittest.main()
