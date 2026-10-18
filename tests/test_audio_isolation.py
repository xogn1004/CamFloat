"""Verify engine output state, not just the camera configuration dictionaries."""
import time
import unittest
from PySide6.QtTest import QTest
import test_app as fixtures


class AudioIsolation(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def wait_audio(self, volumes, mutes, timeout=4):
        deadline = time.monotonic() + timeout
        actual = None
        while time.monotonic() < deadline:
            w = self.window
            w.update_status()
            QTest.qWait(60)
            if any(t.worker.busy for t in w.tiles[:len(volumes)]):
                continue
            actual = ([t.player.audio_get_volume() for t in w.tiles[:len(volumes)]],
                      [t.player.audio_get_mute() for t in w.tiles[:len(mutes)]])
            if actual == (volumes, mutes):
                return
        self.fail(f'Expected independent audio {(volumes, mutes)}, got {actual}')

    def test_zero_volume_and_mute_are_independent_across_enlargement(self):
        w = self.window
        w.set_volume(0, 100)
        w.set_volume(1, 0)
        self.wait_audio([100, 0], [0, 0])
        handles = [int(t.winId()) for t in w.tiles]
        revisions = [t.worker.revision for t in w.tiles]
        for focus in (0, 1):
            w.single_view(focus)
            self.wait_audio([100, 0], [0, 0])
        w.toggle_mute(1)
        self.wait_audio([100, 0], [0, 1])
        w.restore_focus()
        self.wait_audio([100, 0], [0, 1])
        self.assertEqual(handles, [int(t.winId()) for t in w.tiles])
        self.assertEqual(revisions, [t.worker.revision for t in w.tiles])

    def test_four_distinct_volumes_remain_stable_in_fullscreen_and_master_mute(self):
        w = self.window
        w.set_layout(4)
        for index, value in enumerate((100, 70, 25, 0)):
            w.set_volume(index, value)
        self.wait_audio([100, 70, 25, 0], [0, 0, 0, 0])
        w.toggle_mute(1)
        self.wait_audio([100, 70, 25, 0], [0, 1, 0, 0])
        w.toggle_fullscreen(2)
        self.wait_audio([100, 70, 25, 0], [0, 1, 0, 0])
        w.mute_all()
        self.wait_audio([100, 70, 25, 0], [1, 1, 1, 1])
        w.set_volume(2, 35)
        self.wait_audio([100, 70, 35, 0], [1, 1, 1, 1])
        w.mute_all()
        self.wait_audio([100, 70, 35, 0], [0, 1, 0, 0])
        w.handle_escape()
        w.handle_escape()
        self.wait_audio([100, 70, 35, 0], [0, 1, 0, 0])

    def test_reconnection_preserves_peer_audio(self):
        w = self.window
        w.set_volume(0, 100)
        w.set_volume(1, 20)
        w.toggle_mute(1)
        self.wait_audio([100, 20], [0, 1])
        w.reconnect(1)
        QTest.qWait(700)
        self.wait_audio([100, 20], [0, 1])
