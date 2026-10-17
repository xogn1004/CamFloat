import copy
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSlider

import test_app as fixtures
from camera_model import normalize
from native_window import taskbar_can_minimize, system_minimize


class ReleaseRC1(unittest.TestCase):
    setUpClass = classmethod(fixtures.WindowTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WindowTests.tearDownClass.__func__)
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown

    def test_fullscreen_locks_opacity_and_restores_all_surfaces(self):
        w = self.window
        w.set_opacity(45)
        handles = [int(t.winId()) for t in w.tiles]
        for _ in range(2):
            w.toggle_layout_fullscreen()
            self.app.processEvents()
            self.assertEqual(w.config['opacity'], 45)
            for surface in [w, w.chrome, w.toast] + [t.overlay for t in w.tiles]:
                self.assertEqual(surface.windowOpacity(), 1.0)
            w.set_opacity(80)
            self.assertEqual(w.config['opacity'], 45)
            menu = w.build_app_menu()
            opacity = next(a.menu() for a in menu.actions() if a.text() == '전체 투명도')
            slider = opacity.actions()[0].defaultWidget().findChild(QSlider)
            self.assertEqual(slider.value(), 0)
            self.assertFalse(slider.isEnabled())
            menu.deleteLater()
            w.handle_escape()
            self.assertFalse(w.isFullScreen())
            self.assertAlmostEqual(w.windowOpacity(), .45, delta=.01)
            self.assertEqual(handles, [int(t.winId()) for t in w.tiles])

    def test_master_mute_preserves_individual_flags_and_survives_layouts(self):
        w = self.window
        w.config['cameras'][0]['muted'] = False
        individual = [c['muted'] for c in w.config['cameras']]
        w.mute_all()
        self.assertTrue(w.config['master_muted'])
        self.assertEqual(individual, [c['muted'] for c in w.config['cameras']])
        for count in (1, 4, 2):
            w.set_layout(count)
            self.assertTrue(all(w.audio_muted(c) for c in w.config['cameras']))
        restored = normalize(copy.deepcopy(w.config))
        self.assertTrue(restored['master_muted'])
        w.mute_all()
        self.assertEqual(individual, [c['muted'] for c in w.config['cameras']])
        self.assertFalse(w.audio_muted(w.config['cameras'][0]))
        self.assertFalse(w.chrome.master_mute.isChecked())

    def test_toolbar_groups_deadline_and_shared_labels(self):
        chrome = self.window.chrome
        chrome.panel.layout().activate()
        buttons = [chrome.layout_buttons[n] for n in (1, 2, 4)] + [
            chrome.master_mute, chrome.manager, chrome.fullscreen, chrome.pin, chrome.more]
        self.assertEqual([b.x() for b in buttons], sorted(b.x() for b in buttons))
        self.assertTrue(all(b.geometry().right() < chrome.width() for b in buttons))
        with patch('chrome.time.monotonic', return_value=100):
            chrome.reveal()
        self.assertAlmostEqual(chrome.deadline, 101.6)
        with patch('chrome.QCursor.pos', return_value=QPoint(-90000, -90000)), \
                patch('chrome.time.monotonic', return_value=102):
            chrome.poll()
        self.assertFalse(chrome.isVisible())
        self.window.mute_all()
        self.assertIn('전체 음소거 해제', chrome.master_mute.toolTip())
        menu = self.window.build_app_menu()
        entries = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual([a.text().split('\t')[0] for a in entries[:7]], [
            '화면 구성', '전체 음소거 해제', '카메라 관리…', '전체화면',
            '항상 위에 해제', '하드웨어 가속 해제', '전체 투명도'])
        self.assertTrue(all(not a.isCheckable() for a in entries[:7]))
        menu.deleteLater()

    def test_compact_volume_popup_bounds_wheel_and_lifecycle(self):
        w = self.window
        w.resize(300, 180)
        self.app.processEvents()
        overlay = w.tiles[0].overlay
        overlay.reveal_controls()
        self.assertFalse(overlay.expanded_controls())
        popup = overlay.volume_popup
        popup.show_for_speaker()
        self.assertTrue(popup.isVisible())
        self.assertTrue(overlay.rect().contains(popup.geometry()))
        speaker = overlay.mute.mapTo(overlay, QPoint(0, 0))
        self.assertLessEqual(popup.geometry().bottom(), speaker.y())
        popup.slider.setValue(36)
        self.assertEqual(w.camera_for_slot(0)['volume'], 36)
        wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(overlay.mute, wheel)
        self.assertEqual(w.camera_for_slot(0)['volume'], 41)
        w.showMinimized()
        self.app.processEvents()
        self.assertFalse(popup.isVisible())

        w.showNormal()
        self.app.processEvents()
        self.assertFalse(popup.isVisible())

    def test_popup_hover_transfer_and_delayed_dismissal(self):
        w = self.window
        w.resize(300, 180)
        self.app.processEvents()
        overlay = w.tiles[0].overlay
        overlay.reveal_controls()
        self.app.sendEvent(overlay.mute, QEvent(QEvent.Type.Enter))
        popup = overlay.volume_popup
        self.assertTrue(popup.isVisible())
        self.app.sendEvent(overlay.mute, QEvent(QEvent.Type.Leave))
        self.assertTrue(popup.hide_timer.isActive())
        self.app.sendEvent(popup, QEvent(QEvent.Type.Enter))
        self.assertFalse(popup.hide_timer.isActive())
        with patch('volume_popup.QCursor.pos', return_value=QPoint(-90000, -90000)):
            popup.dismiss_if_outside()
        self.assertFalse(popup.isVisible())

    def test_native_minimize_style_preserves_stream_handles(self):
        w = self.window
        handles = [int(t.winId()) for t in w.tiles]
        revisions = [t.worker.revision for t in w.tiles]
        self.assertTrue(taskbar_can_minimize(w))
        system_minimize(w)
        self.app.processEvents()
        self.assertTrue(w.isMinimized())
        self.assertTrue(all(not t.overlay.isVisible() for t in w.tiles))
        w.activate()
        self.app.processEvents()
        self.assertFalse(w.isMinimized())
        self.assertTrue(taskbar_can_minimize(w))
        self.assertEqual(handles, [int(t.winId()) for t in w.tiles])
        self.assertEqual(revisions, [t.worker.revision for t in w.tiles])

    def test_screen_menu_volume_precedes_mute(self):
        menu = self.window.build_context_menu(0)
        names = [a.text().split('\t')[0] for a in menu.actions()]
        mute = next(i for i, name in enumerate(names) if name.startswith('이 영상 음소거'))
        self.assertLess(names.index('이 영상 음량'), mute)
        menu.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
