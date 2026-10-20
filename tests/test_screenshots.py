"""Only synthetic local frames; never write real camera images or open Explorer."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from camfloat.playback import PlaybackWorker
from camfloat.screenshots import Screenshots
import test_app as fixtures


class FakePlayer:
    def __init__(self):
        self.released = False
        self.calls = []

    def is_playing(self):
        return True

    def has_vout(self):
        return 1

    def video_take_snapshot(self, output, path, width, height):
        self.calls.append((output, path, width, height))
        image = QImage(640, 360, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        return 0 if image.save(path) else -1

    def stop(self):
        self.calls.append('stop')

    def release(self):
        self.released = True


class SnapshotFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        for _ in range(300):
            self.app.processEvents()
            if condition():
                return
            QTest.qWait(10)
        self.fail('Capture did not finish')

    def worker(self, player):
        worker = PlaybackWorker(None, player)
        worker.phase = 'playing'
        # A real playback request establishes the active state. For file-only
        # checks, process the callback synchronously with this fake player.
        def request(capture):
            capture(player)
            return True
        worker.request_snapshot = request
        self.addCleanup(lambda: (worker.shutdown(), worker.done.wait(2)))
        return worker

    def test_png_uses_native_size_and_contains_no_camera_information(self):
        with tempfile.TemporaryDirectory(prefix='CamFloat-사진-') as folder:
            player = FakePlayer()
            manager = Screenshots(directory=folder)
            worker = self.worker(player)
            saved = []
            manager.saved.connect(lambda index, path: saved.append((index, path)))
            self.assertTrue(manager.capture(2, worker))
            self.wait(lambda: len(saved) == 1)
            path = saved[0][1]
            self.assertTrue(path.name.startswith('CamFloat_'))
            self.assertIn('_SCREEN3_', path.name)
            self.assertEqual(QImage(str(path)).size().width(), 640)
            self.assertEqual(QImage(str(path)).size().height(), 360)
            self.assertEqual(player.calls[0][2:], (0, 0))
            self.assertFalse(any(p.name.startswith('.camfloat-') for p in Path(folder).iterdir()))

    def test_failed_or_empty_snapshot_does_not_leave_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            manager = Screenshots(directory=folder)
            failed = []
            manager.failed.connect(failed.append)
            worker = self.worker(player)
            with patch.object(player, 'video_take_snapshot', return_value=-1):
                manager.capture(0, worker)
                self.wait(lambda: bool(failed))
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(failed, [0])

    def test_capture_failure_does_not_change_playback_state(self):
        with tempfile.TemporaryDirectory() as folder:
            player = FakePlayer()
            manager = Screenshots(directory=folder)
            worker = self.worker(player)
            with patch.object(player, 'video_take_snapshot', side_effect=OSError('private message')):
                manager.capture(0, worker)
                self.app.processEvents()
            self.assertEqual(worker.phase, 'playing')
            self.assertFalse(worker.error)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_same_screen_does_not_queue_captures_and_cancel_does_not_save(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Screenshots(directory=folder)
            requests = []
            from unittest.mock import Mock
            worker = Mock()
            worker.request_snapshot.side_effect = lambda capture: requests.append(capture) or True
            self.assertTrue(manager.capture(0, worker))
            self.assertFalse(manager.capture(0, worker))
            requests[0](None)
            self.app.processEvents()
            self.assertNotIn(0, manager.pending)
            self.assertEqual(list(Path(folder).iterdir()), [])
            manager.close()
            self.assertFalse(manager.capture(0, worker))

    def test_open_folder_creates_only_the_capture_folder_and_uses_local_url(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '사진' / 'CamFloat'
            manager = Screenshots(directory=target)
            with patch('camfloat.screenshots.QDesktopServices.openUrl', return_value=True) as open_url:
                self.assertTrue(manager.open_folder())
            self.assertTrue(target.is_dir())
            self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), target.resolve())
            self.assertTrue(open_url.call_args.args[0].isLocalFile())

    def test_read_only_or_invalid_directory_fails_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder) / 'file'
            blocked.write_text('keep', encoding='utf-8')
            manager = Screenshots(directory=blocked)
            failed = []
            manager.failed.connect(failed.append)
            manager.capture(0, self.worker(FakePlayer()))
            self.wait(lambda: bool(failed))
            self.assertFalse(manager.open_folder())
            self.assertEqual(blocked.read_text(encoding='utf-8'), 'keep')

    def test_repeated_captures_have_unique_names(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Screenshots(directory=folder)
            worker = self.worker(FakePlayer())
            saved = []
            manager.saved.connect(lambda index, path: saved.append(path))
            for count in range(3):
                self.assertTrue(manager.capture(0, worker))
                self.wait(lambda: len(saved) > count)
            self.assertEqual(len(set(saved)), 3)
            self.assertTrue(all(path.is_file() for path in saved))


class WorkerCaptureLifetime(unittest.TestCase):
    def setUp(self):
        class Player(FakePlayer):
            def media_new(self, url):
                from unittest.mock import Mock
                return Mock()

            def set_media(self, media):
                pass

            def play(self):
                return 0

            def audio_set_volume(self, value):
                pass

            def audio_set_mute(self, value):
                pass

        self.player = Player()
        self.worker = PlaybackWorker(self.player, self.player)
        self.worker.request(('rtsp://host/test', True, 100, True))
        deadline = time.monotonic() + 2
        while self.worker.busy and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertEqual(self.worker.phase, 'playing')

    def tearDown(self):
        self.worker.shutdown()
        self.assertTrue(self.worker.done.wait(3))

    def test_slow_capture_is_not_on_caller_and_release_waits_for_it(self):
        entered, release = threading.Event(), threading.Event()
        threads = []

        def capture(player):
            threads.append(threading.get_ident())
            self.assertIs(player, self.player)
            entered.set()
            release.wait(2)

        try:
            self.assertTrue(self.worker.request_snapshot(capture))
            self.assertTrue(entered.wait(1))
            self.assertFalse(self.worker.request_snapshot(capture))
            self.worker.shutdown()
            self.assertFalse(self.worker.done.wait(.03))
            self.assertFalse(self.player.released)
            self.assertNotIn(threading.get_ident(), threads)
        finally:
            release.set()
        self.assertTrue(self.worker.done.wait(2))
        self.assertTrue(self.player.released)

    def test_camera_change_before_capture_cancels_instead_of_capturing_new_camera(self):
        result = []
        finished = threading.Event()

        def capture(player):
            result.append(player)
            finished.set()

        with self.worker.condition:
            self.assertTrue(self.worker.request_snapshot(capture))
            self.worker.request(('rtsp://host/other', True, 100, True))
        self.assertTrue(finished.wait(2))
        self.assertEqual(result, [None])

    def test_shutdown_cancels_queued_capture_without_native_player_access(self):
        result = []
        with self.worker.condition:
            self.assertTrue(self.worker.request_snapshot(result.append))
            self.worker.shutdown()
        self.assertTrue(self.worker.done.wait(2))
        self.assertEqual(result, [None])
        self.assertFalse(self.worker.request_snapshot(result.append))


class CaptureUI(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_real_snapshot_is_video_only_and_leaves_playback_connected(self):
        with tempfile.TemporaryDirectory(prefix='CamFloat-사진-') as folder:
            self.window.screenshots.directory_override = Path(folder)
            window = self.window
            window.select_slot(0)
            window.tiles[0].overlay.reveal_controls()
            revisions = [t.worker.revision for t in window.tiles]
            players = [id(t.player) for t in window.tiles]
            width, height = window.tiles[0].player.video_get_size(0)
            self.assertTrue(window.take_screenshot(0))
            self.assertFalse(window.take_screenshot(0))
            for _ in range(400):
                self.app.processEvents()
                if not window.screenshots.pending:
                    break
                QTest.qWait(10)
            files = list(Path(folder).glob('CamFloat_*.png'))
            self.assertEqual(len(files), 1)
            image = QImage(str(files[0]))
            self.assertEqual((image.width(), image.height()), (width, height))
            self.assertFalse(image.isNull())
            self.assertEqual([t.worker.revision for t in window.tiles], revisions)
            self.assertEqual([id(t.player) for t in window.tiles], players)
            self.assertTrue(all(t.player.is_playing() for t in window.tiles[:2]))
            self.assertTrue(window.tiles[0].overlay.screenshot_notice.isVisible())
            with patch.object(window, 'open_screenshot_folder', return_value=True) as open_folder:
                window.tiles[0].overlay.screenshot_notice.click()
                open_folder.assert_called_once_with()

    def test_smallest_four_way_toolbar_fits_and_menus_match(self):
        window = self.window
        window.resize(300, 180)
        window.set_layout(4)
        self.app.processEvents()
        for tile in window.tiles:
            overlay = tile.overlay
            overlay.reveal_controls()
            self.app.processEvents()
            self.assertTrue(overlay.rect().contains(overlay.bar.geometry()), (overlay.size(), overlay.bar.geometry()))
            buttons = (overlay.reload, overlay.snapshot, overlay.mute, overlay.move_camera, overlay.choose, overlay.fullscreen)
            self.assertEqual(len({button.y() for button in buttons}), 1)
            for button in buttons:
                self.assertTrue(overlay.bar.rect().contains(button.geometry()), button.toolTip())
            self.assertFalse(overlay.snapshot.icon().isNull())
        menu = window.build_context_menu(0)
        self.assertIn('스크린샷 저장', [a.text() for a in menu.actions()])
        menu.deleteLater()
        app_menu = window.build_app_menu()
        self.assertIn('스크린샷 폴더 열기', [a.text() for a in app_menu.actions()])
        app_menu.deleteLater()

    def test_no_video_or_changing_camera_cannot_capture(self):
        window = self.window
        window.set_layout(2)
        window.assign_camera(0, None)
        self.assertFalse(window.take_screenshot(0))
        window.tiles[1].worker.busy = True
        try:
            self.assertFalse(window.take_screenshot(1))
        finally:
            window.tiles[1].worker.busy = False
