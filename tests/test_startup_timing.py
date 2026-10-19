"""Startup checks with an empty profile; never contact a physical camera."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from startup_timing import StartupTiming
from camera_model import default_config
from startup_window import LoadingWindow, initialize_engine

ROOT = Path(__file__).resolve().parents[1]


class StartupChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_slow_engine_keeps_window_painted_and_event_loop_responsive(self):
        app = QApplication.instance() or QApplication([])
        gui_thread = threading.get_ident()
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        engine = object()
        worker_threads = []

        def initialize():
            worker_threads.append(threading.get_ident())
            time.sleep(.2)
            return engine

        timing = StartupTiming()
        try:
            actual, window = initialize_engine(default_config(), initialize, timing)
            try:
                self.assertIs(actual, engine)
                self.assertTrue(window.isVisible())
                self.assertGreaterEqual(len(ticks), 3)
                self.assertNotEqual(worker_threads, [gui_thread])
                self.assertIn('startup_window_painted', [r['stage'] for r in timing.stages])
                self.assertTrue(app.quitOnLastWindowClosed())
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()
        finally:
            timer.stop()

    def test_close_while_loading_releases_engine_and_does_not_reopen_window(self):
        app = QApplication.instance() or QApplication([])
        from unittest.mock import Mock
        engine = Mock()

        def close_loading():
            for window in app.topLevelWidgets():
                if isinstance(window, LoadingWindow) and not window.finished:
                    window.close()

        def initialize():
            time.sleep(.1)
            return engine

        QTimer.singleShot(20, close_loading)
        self.assertEqual(initialize_engine(default_config(), initialize, StartupTiming()), (None, None))
        engine.release.assert_called_once_with()
        self.assertFalse(any(w.isVisible() for w in app.topLevelWidgets() if isinstance(w, LoadingWindow)))
        app.processEvents()

    def test_initialization_error_closes_loading_window_and_restores_application_policy(self):
        app = QApplication.instance() or QApplication([])

        def initialize():
            raise RuntimeError('synthetic failure')

        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
            initialize_engine(default_config(), initialize, StartupTiming())
        self.assertTrue(app.quitOnLastWindowClosed())
        self.assertFalse(any(w.isVisible() for w in app.topLevelWidgets() if isinstance(w, LoadingWindow)))
        app.processEvents()

    def test_move_and_minimize_while_loading_are_preserved_for_handoff(self):
        app = QApplication.instance() or QApplication([])
        config = default_config()

        def minimize():
            for window in app.topLevelWidgets():
                if isinstance(window, LoadingWindow) and not window.finished:
                    window.move(140, 130)
                    window.showMinimized()

        def initialize():
            time.sleep(.1)
            return object()

        QTimer.singleShot(20, minimize)
        _, window = initialize_engine(config, initialize, StartupTiming())
        try:
            self.assertTrue(window.isMinimized())
            self.assertEqual(config['geometry'][:2], [140, 130])
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_missing_native_instance_is_an_initialization_error(self):
        with self.assertRaises(RuntimeError):
            initialize_engine(default_config(), lambda: None, StartupTiming())

    def test_main_does_not_load_management_or_network_protocol(self):
        code = '''
import main, sys
assert not any(name in sys.modules for name in
               ('dialogs', 'camera_manager', 'camera_editor', 'cryptography', 'onvif_control'))
from dialogs import UsageDialog
assert 'camera_manager' not in sys.modules and 'camera_editor' not in sys.modules
from dialogs import CameraManager, CameraEditor
assert CameraManager.__name__ == 'CameraManager' and CameraEditor.__name__ == 'CameraEditor'
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_protocol_factory_still_returns_real_client_when_requested(self):
        import ptz_control
        with patch('onvif_control.Client') as client:
            self.assertIs(ptz_control.Client({'url': 'synthetic'}), client.return_value)
            client.assert_called_once_with({'url': 'synthetic'})
        self.assertTrue(ptz_control.direction_valid(-1, 0))
        self.assertFalse(ptz_control.direction_valid(True, 0))

    def test_first_paint_records_only_durations_once(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, CAMFLOAT_DATA_DIR=folder):
            timing = StartupTiming()
            timing.mark('imports_ready')
            window = QWidget()
            timing.watch(window)
            try:
                window.show()
                path = Path(folder) / 'diagnostics/startup.json'
                for _ in range(100):
                    app.processEvents()
                    if path.exists():
                        break
                    QTest.qWait(5)
                report = json.loads(path.read_text(encoding='utf-8'))
                stages = report['stages']
                self.assertEqual([row['stage'] for row in stages],
                                 ['imports_ready', 'first_paint', 'event_loop_ready'])
                self.assertTrue(all(set(row) == {'stage', 'ms'} and row['ms'] >= 0 for row in stages))
                self.assertEqual([row['ms'] for row in stages], sorted(row['ms'] for row in stages))
                timing.finish()
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), report)
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()

    def test_read_only_diagnostics_does_not_block_startup(self):
        timing = StartupTiming()
        with patch('camera_model.data_path', side_effect=PermissionError):
            timing.finish()
        self.assertTrue(timing.finished)

    def test_diagnostic_is_disabled_in_test_and_demo_modes(self):
        app = QApplication.instance() or QApplication([])
        window = QWidget()
        timing = StartupTiming()
        timing.watch(window, enabled=False)
        self.assertFalse(hasattr(window, '_startup_observer'))
        window.deleteLater()
        app.processEvents()
