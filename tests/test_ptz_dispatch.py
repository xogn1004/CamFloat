"""Overlapping acknowledgements, cancellation, deadlines and bounded evidence."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from onvif_control import Client
from ptz_control import DirectionControl
from ptz_metadata import defaults
from ptz_timing import DirectionTiming
from ptz_transport import MotionAttempt
from test_direction_control import FakeClient


class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 10.
        self.camera = {'id': 'synthetic', 'url': 'rtsp://user:secret@127.0.0.1/onvif1'}
        self.camera['ptz'] = dict(defaults(self.camera), checked=True)
        self.patch = patch('ptz_control.Client', FakeClient)
        self.patch.start()
        self.eligible = patch('ptz_control.eligible', return_value=True)
        self.eligible.start()
        FakeClient.calls = []
        self.control = DirectionControl(clock=lambda: self.now, diagnostics_enabled=False)
        self.control.prepare(self.camera)
        self.gates = []

    def tearDown(self):
        self.control.shutdown()
        for gate in self.gates:
            gate.set()
        self.assertTrue(self.control.done.wait(3))
        self.assertTrue(self.control.lookup_done.wait(3))
        self.app.processEvents()
        self.patch.stop()
        self.eligible.stop()

    def pump(self, predicate):
        for _ in range(100):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Asynchronous condition was not reached')

    def test_click_limit_is_camera_wide_and_allows_exactly_500ms(self):
        self.assertTrue(self.control.move(self.camera, -1, 0))
        self.assertFalse(self.control.move(self.camera, 1, 0))
        self.now += .499
        self.assertFalse(self.control.move(self.camera, 0, 1))
        self.now += .0011
        self.assertTrue(self.control.move(self.camera, 0, -1))

    def test_repeats_bypass_click_limit_and_do_not_wait_for_replies(self):
        gate = threading.Event()
        self.gates.append(gate)
        entered = []
        def delayed(client, pan, tilt=0, *, attempt):
            entered.append(pan)
            gate.wait(2)
            return {'request_sent': True, 'response_verified': False}
        with patch.object(FakeClient, 'step', delayed):
            self.assertTrue(self.control.move(self.camera, 1, 0))
            self.pump(lambda: len(entered) == 1)
            self.now += .16
            self.assertTrue(self.control.move(self.camera, 1, 0, repeat=True))
            self.pump(lambda: len(entered) == 2)
            self.assertTrue(self.control.busy)
            gate.set()
            self.pump(lambda: not self.control.busy)

    def test_limit_four_stops_input_without_a_waiting_queue(self):
        gate = threading.Event()
        self.gates.append(gate)
        entered = []
        def delayed(client, pan, tilt=0, *, attempt):
            entered.append(1)
            gate.wait(2)
            return {'request_sent': True, 'response_verified': False}
        with patch.object(FakeClient, 'step', delayed):
            self.assertTrue(self.control.move(self.camera, 1, 0))
            for _ in range(3):
                self.now += .16
                self.assertTrue(self.control.move(self.camera, 1, 0, repeat=True))
            self.pump(lambda: len(entered) == 4)
            self.assertFalse(self.control.move(self.camera, 1, 0, repeat=True))
            self.assertEqual(self.control.state, 'send_limit')
            self.assertFalse(self.control.input_open)
            gate.set()
            self.pump(lambda: self.control.state == 'ready')
            self.assertEqual(len(entered), 4)

    def test_last_old_reply_clears_limit_without_overwriting_new_reply(self):
        self.control.begin_input()
        client = self.control.client
        token = self.control.input_cancelled
        response = {'request_sent': True, 'response_verified': False, 'new': True}
        self.control.state = 'send_limit'
        with self.control.jobs_lock:
            self.control.jobs[1] = object()
        self.control.finish(self.control.revision, (4, token, client, response, self.camera))
        self.assertEqual(self.control.state, 'send_limit')
        with self.control.jobs_lock:
            self.control.jobs.clear()
        self.control.finish(self.control.revision, (1, token, client,
            {'request_sent': True, 'http_status': 401}, self.camera))
        self.assertEqual(self.control.state, 'ready')
        self.assertIs(self.control.last_reply, response)

    def test_late_old_reply_cannot_overwrite_newer_result(self):
        gate = threading.Event()
        self.gates.append(gate)
        entered = threading.Event()
        def delayed(client, pan, tilt=0, *, attempt):
            if pan == -1:
                entered.set()
                gate.wait(2)
            return {'request_sent': True, 'response_verified': True, 'pan': pan}
        with patch.object(FakeClient, 'step', delayed):
            self.control.move(self.camera, -1, 0)
            self.assertTrue(entered.wait(1))
            self.control.move(self.camera, 1, 0, repeat=True)
            self.pump(lambda: self.control.last_reply and self.control.last_reply.get('pan') == 1)
            gate.set()
            self.pump(lambda: not self.control.busy)
            self.app.processEvents()
            self.assertEqual(self.control.last_reply['pan'], 1)
            self.assertEqual(self.control.state, 'ready')

    def test_release_cancels_unsent_and_new_camera_survives_old_reply(self):
        gate = threading.Event()
        self.gates.append(gate)
        entered = threading.Event()
        writes = []
        def waiting(client, pan, tilt=0, *, attempt):
            entered.set()
            gate.wait(2)
            if attempt.cancelled.is_set() or not attempt.before_send():
                return {'cancelled': True, 'request_sent': False}
            writes.append(pan)
            return {'request_sent': True, 'response_verified': True}
        with patch.object(FakeClient, 'step', waiting):
            self.control.move(self.camera, 1, 0)
            self.assertTrue(entered.wait(1))
            self.control.end_input()
            other = dict(self.camera, id='other')
            other['ptz'] = dict(defaults(other), checked=True)
            self.control.prepare(other)
            gate.set()
            self.pump(lambda: not self.control.busy)
            self.app.processEvents()
            self.assertEqual(writes, [])
            self.assertEqual(self.control.target[0], 'other')
            self.assertEqual(self.control.state, 'ready')

    def test_reply_from_old_press_does_not_interrupt_new_press(self):
        gate = threading.Event()
        self.gates.append(gate)
        entered = threading.Event()
        def waiting(client, pan, tilt=0, *, attempt):
            entered.set()
            gate.wait(2)
            return {'request_sent': True, 'http_status': 401}
        with patch.object(FakeClient, 'step', waiting):
            self.control.move(self.camera, -1, 0)
            self.assertTrue(entered.wait(1))
            self.control.end_input()
            self.control.begin_input()
            gate.set()
            self.pump(lambda: not self.control.busy)
            self.app.processEvents()
            self.assertTrue(self.control.input_open)
            self.assertNotEqual(self.control.state, 'move_error')


class TransportTests(unittest.TestCase):
    def test_only_body_writes_are_serialized_and_replies_can_overlap(self):
        write_lock = threading.Lock()
        count_lock = threading.Lock()
        writes = [0, 0, 0]
        both_sent = threading.Event()
        replies = []
        class Response:
            status = 200
            def read(self, size):
                return b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body/></s:Envelope>'
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def connect(self): pass
            def request(self, *args, **kwargs):
                with count_lock:
                    writes[0] += 1
                    writes[1] = max(writes[1], writes[0])
                time.sleep(.025)
                with count_lock:
                    writes[0] -= 1
                    writes[2] += 1
                    if writes[2] == 2:
                        both_sent.set()
            def getresponse(self):
                both_sent.wait(1)
                return Response()
            def close(self): pass
        client = Client({'url': 'rtsp://user:secret@127.0.0.1/onvif1'}, Connection)
        client.ptz_path, client.profile_token = '/ptz', 'profile'
        def run():
            attempt = MotionAttempt(threading.Event(), lambda: True, lambda event: None, write_lock=write_lock)
            replies.append(client.step(1, attempt=attempt))
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertTrue(both_sent.is_set())
        self.assertEqual(writes[1], 1)
        self.assertEqual(len(replies), 2)
        self.assertTrue(all(row['request_sent'] for row in replies))

    def test_cancel_during_connect_never_writes_request(self):
        calls = []
        cancelled = threading.Event()
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def connect(self): cancelled.set()
            def request(self, *args, **kwargs): calls.append('write')
            def close(self): calls.append('close')
        client = Client({'url': 'rtsp://user:secret@127.0.0.1/onvif1'}, Connection)
        client.ptz_path, client.profile_token = '/ptz', 'test-profile'
        attempt = MotionAttempt(cancelled, lambda: True, lambda event: None)
        result = client.step(1, attempt=attempt)
        self.assertTrue(result['cancelled'])
        self.assertFalse(result['request_sent'])
        self.assertEqual(calls, ['close'])

    def test_total_deadline_interrupts_a_trickling_reply(self):
        import socketserver
        stop = threading.Event()
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(1)
                try:
                    self.request.recv(32768)
                    self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n')
                    for _ in range(40):
                        if stop.wait(.035): break
                        self.request.sendall(b' ')
                except OSError:
                    pass
        with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
            serving = threading.Thread(target=server.handle_request, daemon=True)
            serving.start()
            client = Client({'url': 'rtsp://user:secret@127.0.0.1/onvif1'})
            client.ptz_path, client.ptz_port, client.profile_token = '/ptz', server.server_address[1], 'test-profile'
            attempt = MotionAttempt(threading.Event(), lambda: True, lambda event: None)
            started = time.monotonic()
            try:
                result = client.step(1, attempt=attempt)
                elapsed = time.monotonic() - started
                self.assertTrue(result['request_sent'])
                self.assertTrue(result['deadline_exceeded'])
                self.assertLess(elapsed, .9)
            finally:
                stop.set()
                serving.join(2)

    def test_timing_is_bounded_and_omits_connection_secrets(self):
        with tempfile.TemporaryDirectory() as folder, patch('ptz_timing.data_path', return_value=Path(folder) / 'settings.json'):
            timing = DirectionTiming('test-version')
            for i in range(2000):
                timing.record('sent', seq=i, address='rtsp://user:secret@127.0.0.1', password='secret')
            timing.flush()
            raw = timing.path.read_text(encoding='utf-8')
            self.assertNotIn('secret', raw)
            self.assertNotIn('127.0.0.1', raw)
            self.assertEqual(len(json.loads(raw)['events']), 1500)

    def test_summary_distinguishes_new_writes_and_completion_after_release(self):
        from tools.direction_timing import summarize
        result = summarize({'events': [
            {'event': 'dispatch', 'seq': 1, 'input': 1, 'ms': 0},
            {'event': 'write_started', 'seq': 1, 'ms': 1},
            {'event': 'sent', 'seq': 1, 'ms': 2},
            {'event': 'dispatch', 'seq': 2, 'input': 1, 'ms': 160},
            {'event': 'write_started', 'seq': 2, 'ms': 161},
            {'event': 'input_end', 'input': 1, 'ms': 162},
            {'event': 'sent', 'seq': 2, 'ms': 163},
            {'event': 'reply', 'seq': 2, 'ms': 300, 'duration_ms': 140},
        ]})
        self.assertEqual(result['write_started_after_release'], 0)
        self.assertEqual(result['transmission_completed_after_release'], 1)
        self.assertEqual(result['send_interval_ms']['median'], 161)


if __name__ == '__main__':
    unittest.main()
