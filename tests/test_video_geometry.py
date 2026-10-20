"""Release checks using synthetic video and isolated settings only."""
import unittest

from PySide6.QtCore import QRect, QSize
from PySide6.QtTest import QTest

from camfloat.camera_model import default_config, normalize
from camfloat.video_geometry import cover_rect, smaller_size
import test_app as fixtures


class GeometryChecks(unittest.TestCase):
    def test_cover_centers_and_fills_without_stretching(self):
        self.assertEqual(cover_rect(800, 600, 16 / 9), QRect(-134, 0, 1067, 600))
        self.assertEqual(cover_rect(800, 450, 16 / 9), QRect(0, 0, 800, 450))
        self.assertEqual(cover_rect(800, 300, 4 / 3), QRect(0, -150, 800, 600))

    def test_invalid_or_extreme_video_size_keeps_the_viewport(self):
        for ratio in (None, 0, -1, float('nan'), float('inf'), 100000):
            self.assertEqual(cover_rect(800, 600, ratio), QRect(0, 0, 800, 600))

    def test_window_only_shrinks_and_respects_minimum(self):
        self.assertEqual(smaller_size(800, 600, 16 / 9, QSize(300, 180)), QSize(800, 450))
        self.assertEqual(smaller_size(800, 600, 4 / 3, QSize(300, 180)), QSize(800, 600))
        self.assertIsNone(smaller_size(300, 180, 16 / 9, QSize(300, 180)))

    def test_modes_default_and_normalize_separately_per_layout(self):
        config = default_config()
        config['view_modes']['4'][2] = 'fill'
        restored = normalize(config)
        self.assertEqual(restored['view_modes']['4'], ['fit', 'fit', 'fill', 'fit'])
        self.assertEqual(restored['view_modes']['1'], ['fit'] * 4)
        restored['view_modes']['4'] = ['bad', 'fill', 1, None]
        self.assertEqual(normalize(restored)['view_modes']['4'], ['fit', 'fill', 'fit', 'fit'])


class VideoPresentation(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def source_ready(self, index=0):
        tile = self.window.tiles[index]
        for _ in range(100):
            tile.update_video_geometry(read_size=True)
            if tile.source_ratio:
                return tile
            QTest.qWait(20)
        self.fail('Synthetic video did not become ready')

    def test_fill_keeps_sessions_and_original_frame_size(self):
        window = self.window
        window.set_layout(1)
        window.resize(800, 600)
        self.app.processEvents()
        tile = self.source_ready()
        player = tile.player
        revision = tile.worker.revision
        hwnd = tile.worker.hwnd
        window.set_view_mode(0, 'fill')
        self.app.processEvents()
        self.assertGreater(tile.video_surface.width(), tile.width())
        self.assertEqual(player.video_get_size(0), (640, 360))
        self.assertIs(tile.player, player)
        self.assertEqual((tile.worker.revision, tile.worker.hwnd), (revision, hwnd))
        window.set_view_mode(0, 'fit')
        self.assertEqual(tile.video_surface.geometry(), tile.rect())

    def test_modes_follow_screens_and_layouts(self):
        window = self.window
        window.set_view_mode(0, 'fill')
        self.assertEqual(window.view_mode(1), 'fit')
        window.set_layout(1)
        self.assertEqual(window.view_mode(0), 'fit')
        window.set_layout(2)
        self.assertEqual(window.view_mode(0), 'fill')
        window.single_view(0)
        self.assertEqual(window.view_mode(0), 'fill')
        window.restore_focus()
        self.assertEqual(window.view_mode(0), 'fill')

    def test_fit_window_and_fullscreen_guard(self):
        window = self.window
        window.set_layout(1)
        window.resize(800, 600)
        self.app.processEvents()
        self.source_ready()
        window.fit_window_to_video()
        self.assertEqual(window.size(), QSize(800, 450))
        window.toggle_layout_fullscreen()
        self.app.processEvents()
        self.assertIsNone(window.fitted_window_size())
        window.handle_escape()


if __name__ == '__main__':
    unittest.main()
