"""Protocol and stop scheduling checks using fake clients, never live devices."""
import hashlib
import json
import unittest
from unittest.mock import patch

from tools import camera_ptz_trial as trial


class PTZTrialTests(unittest.TestCase):
    def camera(self, url='rtsp://user:secret@192.168.1.2:554/onvif1', **extra):
        return dict(number=1, name='Example', url=url, enabled=True, **extra)

    def test_only_enabled_private_registered_cameras(self):
        good = self.camera()
        disabled = self.camera()
        disabled['enabled'] = False
        candidates = [good, disabled, self.camera(connection_locked=True)]
        for host in ('127.0.0.1', '169.254.1.2', '8.8.8.8', '224.0.0.1', '0.0.0.0', 'example.com'):
            candidates.append(self.camera('rtsp://' + host + '/onvif1'))
        candidates.append(self.camera('http://192.168.1.2/onvif1'))
        candidates.append(self.camera('rtsp://192.168.1.2:invalid/onvif1'))
        self.assertEqual(trial.eligible_cameras({'cameras': candidates}), [good])

    def test_digest_uses_control_method_and_keeps_password_out(self):
        uri = 'rtsp://192.168.1.2:554/onvif1'
        md5 = lambda text: hashlib.md5(text.encode()).hexdigest()
        expected = md5(md5('user:example:secret') + ':xyz:' + md5('SET_PARAMETER:' + uri))
        header = trial.digest_header('Digest realm="example", nonce="xyz"', uri, 'user', 'secret', 'SET_PARAMETER')
        self.assertIn('response="' + expected + '"', header)
        self.assertNotIn('secret', header)

    def test_digest_rejects_unsupported_algorithm_and_qop(self):
        for challenge in ('Basic realm="example"', 'Digest nonce="x", algorithm="SHA-512"',
                          'Digest nonce="x", qop="auth-int"', 'Digest realm="example"'):
            with self.assertRaises(ValueError):
                trial.digest_header(challenge, 'rtsp://example/stream', 'u', 'p', 'SET_PARAMETER')

    def test_digest_qop_increments_count_and_rejects_header_injection(self):
        with patch.object(trial.secrets, 'token_hex', return_value='client'):
            header = trial.digest_header('Digest realm="test", nonce="xyz", qop="auth"',
                                         'rtsp://example/stream', 'u', 'p', 'SET_PARAMETER', 3)
        self.assertIn('nc=00000003', header)
        with self.assertRaises(ValueError):
            trial.digest_header('Digest realm="test", nonce="xyz"',
                                'rtsp://example/stream', 'u\r\nInjected: x', 'p', 'SET_PARAMETER')

    def test_command_formats_and_reject_unbounded_commands(self):
        for variant in trial.FORMATS:
            method, headers, body = trial.command(variant, 'STOP')
            self.assertIn(method, ('SET_PARAMETER', 'USER_CMD_SET'))
            self.assertIn('STOP', ' '.join(headers) + body.decode())
        for direction in ('AUTO', 'REBOOT', 'UP', 'left\r\nInjected: x'):
            with self.assertRaises(ValueError):
                trial.command('content_type', direction)

    def fake_factory(self, *, backup_status=200, move_error=False):
        clients = []
        class FakeClient:
            def __init__(self, url):
                self.index = len(clients)
                self.calls = []
                self.closed = False
                clients.append(self)
            def ptz(self, variant, direction):
                self.calls.append(direction)
                if direction != 'STOP' and move_error:
                    raise TimeoutError('must not appear: user:secret@private-address')
                return backup_status if self.index == 1 else 200
            def close(self):
                self.closed = True
        return clients, FakeClient

    def test_pulse_schedules_stop_and_closes_connections(self):
        clients, factory = self.fake_factory()
        result = trial.pulse(self.camera(), 'content_type', 'LEFT', 100, factory)
        self.assertEqual(result['move_status'], 200)
        self.assertEqual(result['timed_stop_status'], 200)
        self.assertEqual(clients[0].calls, ['STOP', 'LEFT', 'STOP'])
        self.assertEqual(clients[1].calls, ['STOP', 'STOP'])
        self.assertTrue(all(c.closed for c in clients))
        self.assertEqual(result['physical_result'], 'unconfirmed')

    def test_failed_backup_prevents_movement(self):
        clients, factory = self.fake_factory(backup_status=400)
        result = trial.pulse(self.camera(), 'user_body', 'LEFT', 100, factory)
        self.assertNotIn('move_status', result)
        self.assertNotIn('LEFT', clients[0].calls)
        self.assertTrue(all(c.closed for c in clients))

    def test_move_error_still_stops_without_logging_credentials(self):
        clients, factory = self.fake_factory(move_error=True)
        result = trial.pulse(self.camera(), 'content_type', 'LEFT', 100, factory)
        self.assertEqual(result['timed_stop_status'], 200)
        self.assertEqual(result['final_stop_status'], 200)
        self.assertEqual(result['error'], 'TimeoutError')
        serialized = json.dumps(result)
        for secret in ('secret', '192.168.1.2', 'private-address', 'Example'):
            self.assertNotIn(secret, serialized)

    def test_invalid_duration_rejected_before_connecting(self):
        for duration in (0, 99, 251, 5000):
            with patch.object(trial.socket, 'create_connection') as connect:
                with self.assertRaises(ValueError):
                    trial.pulse(self.camera(), 'content_type', 'LEFT', duration)
                connect.assert_not_called()

    def test_wire_digest_retry_stays_on_same_socket_and_checks_sequence(self):
        replies = [
            b'RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\nWWW-Authenticate: Digest realm="test", nonce="n"\r\nContent-Length: 0\r\n\r\n',
            b'RTSP/1.0 200 OK\r\nCSeq: 2\r\nContent-Length: 0\r\n\r\n',
        ]
        sent = []
        class FakeSocket:
            def settimeout(self, seconds): pass
            def sendall(self, data): sent.append(data)
            def recv(self, size): return replies.pop(0)
            def close(self): pass
        with patch.object(trial.socket, 'create_connection', return_value=FakeSocket()) as connect:
            client = trial.Client(self.camera()['url'])
            self.assertEqual(client.ptz('user_body', 'STOP'), 200)
            client.close()
        self.assertEqual(connect.call_count, 1)
        self.assertNotIn(b'Authorization:', sent[0])
        self.assertIn(b'Authorization: Digest ', sent[1])
        self.assertIn(b'Content-Length: 12\r\n', sent[1])
        self.assertNotIn(b'secret', sent[1])


if __name__ == '__main__':
    unittest.main()
