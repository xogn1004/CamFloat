"""Camera speaker framing tests. Only generated PCM and fake sockets."""
import json
import argparse
import io
from contextlib import redirect_stdout
import struct
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import unittest
from unittest.mock import patch

from tools import camera_talkback_trial as trial


class TalkbackTrialTests(unittest.TestCase):
    def setUp(self):
        self.camera = dict(number=1, url='rtsp://user:secret@127.0.0.1:554/onvif1')

    def factory(self, *, open_status=200, description_status=200, frame_error=None):
        clients = []
        class Client:
            def __init__(self, url):
                self.parts = urlsplit(url)
                self.sock = self
                self.calls = []
                self.request_uris = []
                self.frames = []
                self.closed = False
                clients.append(self)
            def request(self, method, headers):
                self.calls.append((method, headers))
                self.request_uris.append(getattr(self, 'uri', ''))
                if method == 'DESCRIBE':
                    return description_status
                return open_status if 'AudioCtlCmd:OPEN' in ' '.join(headers) else 200
            def sendall(self, data):
                if frame_error:
                    raise frame_error
                self.frames.append(data)
            def close(self):
                self.closed = True
        return clients, Client

    def test_fixed_two_second_stream_has_small_generated_notes(self):
        frames = list(trial.tone_frames())
        self.assertEqual(len(frames), 100)
        audible = 0
        for index, frame in enumerate(frames):
            self.assertEqual(len(frame), 336)
            self.assertEqual(struct.unpack('<BBH', frame[:4]), (0x24, 2, 332))
            self.assertEqual(frame[4:16], bytes(12))
            values = struct.unpack('<160h', frame[16:])
            self.assertLessEqual(max(map(abs, values)), 1000)
            audible += any(values)
            if index < 20 or index >= 58:
                self.assertFalse(any(values))
        self.assertGreater(audible, 0)

    def test_success_closes_and_does_not_log_secrets_or_claim_audible_output(self):
        clients, factory = self.factory()
        result = trial.trial(self.camera, client_factory=factory, sleeper=lambda _: None, monotonic=lambda: 0)
        self.assertEqual(result['frames_sent'], 100)
        self.assertEqual(result['open_status'], 200)
        self.assertEqual(result['close_status'], 200)
        self.assertTrue(clients[0].closed)
        self.assertEqual(result['physical_result'], 'unconfirmed')
        self.assertFalse(result['microphone_used'])
        for secret in ('secret', '127.0.0.1', 'rtsp://'):
            self.assertNotIn(secret, json.dumps(result))

    def test_probe_sends_no_audio(self):
        clients, factory = self.factory()
        result = trial.trial(self.camera, send_tone=False, client_factory=factory)
        self.assertEqual(result['frames_sent'], 0)
        self.assertFalse(clients[0].frames)
        self.assertEqual(len(clients[0].calls), 3)
        self.assertEqual(result['close_status'], 200)

    def test_default_vendor_candidate_closes_on_documented_path(self):
        clients, factory = self.factory()
        result = trial.trial(self.camera, send_tone=False, client_factory=factory)
        self.assertEqual(urlsplit(clients[0].request_uris[1]).path, '/onvif0')
        self.assertEqual(urlsplit(clients[0].request_uris[2]).path, '/onvif1')
        self.assertEqual(result['close_path_variant'], '/onvif1')
        self.assertTrue(clients[0].closed)

    def test_rejected_open_sends_no_frames_but_attempts_close(self):
        clients, factory = self.factory(open_status=403)
        result = trial.trial(self.camera, client_factory=factory)
        self.assertEqual(result['frames_sent'], 0)
        self.assertTrue(clients[0].closed)
        self.assertIn('AudioCtlCmd:CLOSE', ' '.join(clients[0].calls[-1][1]))

    def test_rejected_description_does_not_open_audio(self):
        clients, factory = self.factory(description_status=400)
        result = trial.trial(self.camera, client_factory=factory)
        self.assertEqual(result['frames_sent'], 0)
        self.assertEqual(len(clients[0].calls), 1)
        self.assertTrue(clients[0].closed)

    def test_send_failure_always_closes(self):
        clients, factory = self.factory(frame_error=OSError('secret'))
        result = trial.trial(self.camera, client_factory=factory)
        self.assertEqual(result['error'], 'OSError')
        self.assertEqual(result['close_status'], 200)
        self.assertTrue(clients[0].closed)

    def test_interrupt_always_closes(self):
        clients, factory = self.factory(frame_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            trial.trial(self.camera, client_factory=factory)
        self.assertTrue(clients[0].closed)
        self.assertIn('AudioCtlCmd:CLOSE', ' '.join(clients[0].calls[-1][1]))

    def test_invalid_path_rejected_before_connection(self):
        clients, factory = self.factory()
        with self.assertRaises(ValueError):
            trial.trial(self.camera, path='/unrelated', client_factory=factory)
        self.assertFalse(clients)

    def test_custom_duration_controls_generated_frame_count(self):
        clients, factory = self.factory()
        result = trial.trial(self.camera, duration_seconds=5, client_factory=factory,
                             sleeper=lambda _: None, monotonic=lambda: 0)
        self.assertEqual(result['frames_sent'], 250)
        self.assertEqual(result['generated_audio_seconds'], 5)
        self.assertEqual(len(clients[0].frames), 250)

    def test_invalid_duration_rejected_before_connection(self):
        for seconds in (0, -1, 31, 1.5):
            clients, factory = self.factory()
            with self.assertRaises(ValueError):
                trial.trial(self.camera, duration_seconds=seconds, client_factory=factory)
            self.assertFalse(clients)

    def test_time_entry_validation_defaults_and_retry(self):
        for value in ('-1', '301', '1.5', 'abc'):
            with self.assertRaises(argparse.ArgumentTypeError):
                trial.seconds_argument(value, 0, 300)
        self.assertEqual(trial.seconds_argument('0', 0, 300), 0)
        self.assertEqual(trial.seconds_argument('300', 0, 300), 300)
        with patch('builtins.input', side_effect=['invalid', '20']), redirect_stdout(io.StringIO()):
            self.assertEqual(trial.prompt_seconds('Delay', 10, 0, 300), 20)
        with patch('builtins.input', return_value=''):
            self.assertEqual(trial.prompt_seconds('Duration', 3, 1, 30), 3)

    def test_countdown_waits_requested_seconds_and_zero_starts_immediately(self):
        waits = []
        with redirect_stdout(io.StringIO()):
            trial.countdown(12, sleeper=waits.append)
            trial.countdown(0, sleeper=waits.append)
        self.assertEqual(waits, [1] * 12)

    def test_probe_report_does_not_overwrite_manual_observations(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)):
            trial.save([{'physical_result': 'heard'}])
            trial.save([{'frames_sent': 0}], probe=True)
            base = Path(folder) / 'verification/current/camera-control'
            self.assertEqual(json.loads((base / 'talkback-manual-latest.json').read_text()), [{'physical_result': 'heard'}])
            self.assertEqual(json.loads((base / 'talkback-probe-latest.json').read_text()), [{'frames_sent': 0}])

    def test_new_manual_trial_keeps_previous_listening_results(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)):
            evidence = {'camera_number': 1, 'physical_result': 'heard'}
            trial.save([evidence])
            fake_result = {'camera_number': 1, 'frames_sent': 100, 'physical_result': 'unconfirmed'}
            with patch.object(trial, 'load_cameras', return_value=[self.camera]), \
                    patch.object(trial, 'trial', return_value=fake_result), \
                    patch.object(trial, 'countdown'), \
                    patch('builtins.input', side_effect=['1', '', 'n', 'q']), redirect_stdout(io.StringIO()):
                self.assertEqual(trial.main(['--delay', '0', '--duration', '2']), 0)
            saved = trial.previous_results()
            self.assertEqual(saved[0], evidence)
            self.assertEqual(saved[1]['physical_result'], 'not_heard')

    def test_invalid_history_is_not_used(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(trial, 'ROOT', Path(folder)):
            self.assertEqual(trial.previous_results(), [])
            base = Path(folder) / 'verification/current/camera-control'
            base.mkdir(parents=True)
            for raw in ('not-json', '{}', '[1]'):
                (base / 'talkback-manual-latest.json').write_text(raw, encoding='utf-8')
                self.assertEqual(trial.previous_results(), [])


if __name__ == '__main__':
    unittest.main()
