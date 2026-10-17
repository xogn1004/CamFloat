"""Regression coverage for app chrome, real deselection and fullscreen gestures."""
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main import app_icon
import test_app as fixtures


class ChromeGestures(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def click(self, index):
        overlay = self.window.tiles[index].overlay
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=overlay.rect().center())

    def test_selection_deselection_returning_click_and_target_shortcuts(self):
        with patch.object(self.window, 'app_is_foreground', return_value=True):
            self.assertIsNone(self.window.selected)
            self.click(0)
            self.assertEqual(self.window.selected, 0)
            overlay = self.window.tiles[0].overlay
            overlay.activation_press = True  # Native WM_MOUSEACTIVATE snapshot.
            self.click(0)
            QTest.qWait(QApplication.doubleClickInterval() + 40)
            self.assertEqual(self.window.selected, 0)
            self.click(0)
            QTest.qWait(QApplication.doubleClickInterval() + 40)
            self.assertIsNone(self.window.selected)
            camera = self.window.camera_for_slot(0)
            muted, revision = camera['muted'], self.window.tiles[0].worker.revision
            self.window.toggle_mute(self.window.selected)
            self.window.reconnect(self.window.selected)
            self.assertEqual(camera['muted'], muted)
            self.assertEqual(self.window.tiles[0].worker.revision, revision)

    def test_double_then_third_click_enters_fullscreen_without_reconnecting(self):
        self.window.set_layout(4)
        QTest.qWait(600)
        handles = [int(t.winId()) for t in self.window.tiles]
        revisions = [t.worker.revision for t in self.window.tiles]
        overlay = self.window.tiles[2].overlay
        with patch.object(self.window, 'app_is_foreground', return_value=True):
            self.click(2)
            point = overlay.rect().center()
            global_point = overlay.mapToGlobal(point)
            QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(self.window.focused_screen, 2)
            self.assertFalse(self.window.isFullScreen())
            point = overlay.mapFromGlobal(global_point)
            QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(80)
        self.assertTrue(self.window.isFullScreen())
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.selected, 2)
        self.assertEqual(revisions, [t.worker.revision for t in self.window.tiles])
        self.assertEqual(handles, [int(t.winId()) for t in self.window.tiles])
        self.window.handle_escape()
        self.assertIsNone(self.window.focused_screen)
        self.assertTrue(self.window.isFullScreen())
        self.window.handle_escape()
        self.assertFalse(self.window.isFullScreen())

    def test_triple_after_restoring_enlarged_screen_uses_original_screen(self):
        self.window.set_layout(4)
        self.window.single_view(3)
        point = self.window.mapToGlobal(QPoint(100, 100))
        self.window.record_double_click(3, point)
        self.window.toggle_focus(3)
        self.assertIsNone(self.window.focused_screen)
        # Third click can now land over another underlying SCREEN.
        self.assertTrue(self.window.consume_third_click(point))
        self.assertEqual(self.window.focused_screen, 3)
        self.assertTrue(self.window.isFullScreen())

    def test_third_click_timeout_distance_and_single_layout(self):
        point = self.window.mapToGlobal(QPoint(100, 100))
        self.window.last_double = (1, point, time.monotonic() - 5)
        self.assertFalse(self.window.consume_third_click(point))
        self.window.record_double_click(1, point)
        self.assertFalse(self.window.consume_third_click(point + QPoint(100, 0)))
        self.window.set_layout(1)
        self.window.record_double_click(0, point)
        self.window.toggle_focus(0)
        self.assertTrue(self.window.isFullScreen())
        self.assertTrue(self.window.consume_third_click(point))
        self.assertTrue(self.window.isFullScreen())
        self.window.handle_escape()
        self.assertFalse(self.window.isFullScreen())

    def test_f11_selected_vs_unselected_and_restore_previous_geometry(self):
        self.window.set_layout(4)
        geometry = QRect(self.window.geometry())
        self.window.select_slot(None)
        self.window.toggle_fullscreen(self.window.selected)
        self.assertIsNone(self.window.focused_screen)
        self.assertTrue(self.window.isFullScreen())
        self.window.toggle_fullscreen(self.window.selected)
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.geometry(), geometry)
        self.window.select_slot(1)
        self.window.toggle_fullscreen(self.window.selected)
        self.assertEqual(self.window.focused_screen, 1)
        self.window.toggle_fullscreen(self.window.selected)
        self.assertIsNone(self.window.focused_screen)
        self.window.single_view(2)
        self.window.toggle_fullscreen(2)
        self.window.toggle_fullscreen(2)
        self.assertEqual(self.window.focused_screen, 2)
        self.assertEqual(self.window.geometry(), geometry)
        self.window.toggle_layout_fullscreen()
        self.assertIsNone(self.window.focused_screen)

    def test_drag_does_not_deselect_and_double_cancels_pending_deselect(self):
        self.window.select_slot(0)
        overlay = self.window.tiles[0].overlay
        with patch.object(self.window, 'app_is_foreground', return_value=True):
            point = overlay.rect().center()
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(overlay, point + QPoint(30, 20))
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=point + QPoint(30, 20))
            self.assertFalse(self.window.click_timer.isActive())
            self.window.defer_deselect(0)
            QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, pos=overlay.rect().center())
            self.assertFalse(self.window.click_timer.isActive())
            self.assertEqual(self.window.selected, 0)

    def test_chrome_toast_and_screen_button_order(self):
        self.assertFalse(app_icon().isNull())
        self.assertFalse(self.window.windowIcon().isNull())
        self.window.chrome.reveal()
        self.assertTrue(self.window.chrome.isVisible())
        self.assertTrue(self.window.chrome.layout_buttons[2].isChecked())
        self.window.set_layout(4)
        self.assertTrue(self.window.toast.isVisible())
        self.assertIn('4분할', self.window.toast.label.text())
        self.window.toast.hide()
        self.window.set_layout(4)
        self.assertFalse(self.window.toast.isVisible())
        self.window.single_view(1)
        self.assertFalse(self.window.toast.isVisible())
        self.window.restore_focus()
        overlay = self.window.tiles[0].overlay
        overlay.reveal_controls()
        row = overlay.bar.layout()
        self.assertEqual([row.itemAt(i).widget() for i in range(row.count())],
            [overlay.reload, overlay.mute, overlay.volume, overlay.value, overlay.choose, overlay.fullscreen])
        self.window.set_opacity(55)
        self.assertAlmostEqual(self.window.chrome.windowOpacity(), .55, delta=.01)
        self.window.resize(300, 180)
        self.app.processEvents()
        self.window.chrome.reveal()
        self.assertGreaterEqual(self.window.chrome.x(), self.window.x())
        self.assertLessEqual(self.window.chrome.geometry().right(), self.window.geometry().right())
        with self.window.modal():
            self.assertFalse(self.window.chrome.isVisible())
            self.assertFalse(self.window.toast.isVisible())


if __name__ == '__main__':
    unittest.main(verbosity=2)
