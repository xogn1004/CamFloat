"""Shortcut tests use temporary folders and mock pin approval; no desktop edits."""
from contextlib import nullcontext
import ctypes
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog
from camera_model import default_config, load_config, normalize, reset_settings, save_config
from startup_shortcuts import ShortcutDialog, maybe_offer_shortcuts, offer_shortcuts
from windows_shortcuts import create_shortcut, shortcut_target, PropertyKey, PropVariant, TaskbarPinning


class ShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.executable = self.folder / '한글 폴더' / 'CamFloat.exe'
        self.executable.parent.mkdir()
        self.executable.write_bytes(b'MZ-synthetic-test-only')
        self.desktop = self.folder / 'Desktop' / 'CamFloat.lnk'
        self.taskbar = SimpleNamespace(available=True, request=Mock())

    def tearDown(self):
        self.app.processEvents()
        self.temporary.cleanup()

    def test_real_shell_link_target_unicode_and_existing_file_preserved(self):
        self.assertEqual(ctypes.sizeof(PropertyKey), 20)
        self.assertEqual(ctypes.sizeof(PropVariant), 24)
        self.assertTrue(create_shortcut(self.desktop, self.executable))
        self.assertEqual(shortcut_target(self.desktop).resolve(), self.executable.resolve())
        original = self.desktop.read_bytes()
        self.assertFalse(create_shortcut(self.desktop, self.executable))
        self.assertEqual(original, self.desktop.read_bytes())

    def test_missing_settings_and_reset_offer_once_legacy_settings_do_not(self):
        with patch.dict(os.environ, CAMFLOAT_DATA_DIR=str(self.folder / 'profile')):
            config = load_config()
            self.assertFalse(config['shortcuts_prompted'])
            owner = SimpleNamespace(config=config, modal=nullcontext, persist=Mock())
            with patch('startup_shortcuts.offer_shortcuts') as offer:
                self.assertTrue(maybe_offer_shortcuts(owner))
                self.assertFalse(maybe_offer_shortcuts(owner))
                offer.assert_called_once_with(owner)
                owner.persist.assert_called_once()
                owner.config = reset_settings([])
                self.assertTrue(maybe_offer_shortcuts(owner))
                self.assertEqual(offer.call_count, 2)
            save_config(owner.config)
            self.assertTrue(load_config()['shortcuts_prompted'])
            self.assertTrue(normalize({})['shortcuts_prompted'])
            self.assertFalse(normalize(dict(shortcuts_prompted=False))['shortcuts_prompted'])

    def test_skip_does_not_create_files_or_request_pinning(self):
        dialog = ShortcutDialog(None, self.executable, self.desktop, self.taskbar)
        QTimer.singleShot(0, dialog.skip.click)
        self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
        self.assertFalse(self.desktop.exists())
        self.taskbar.request.assert_not_called()
        dialog.deleteLater()

    def test_desktop_selection_creates_shortcut_without_pinning(self):
        dialog = ShortcutDialog(None, self.executable, self.desktop, self.taskbar)
        dialog.create()
        self.assertTrue(self.desktop.exists())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.taskbar.request.assert_not_called()
        dialog.deleteLater()

    def test_taskbar_checkbox_requests_native_confirmation_only_when_selected(self):
        dialog = ShortcutDialog(None, self.executable, self.desktop, self.taskbar)
        dialog.desktop.setChecked(False)
        dialog.taskbar_box.setChecked(True)
        dialog.create()
        self.taskbar.request.assert_called_once()
        self.assertEqual(self.taskbar.request.call_args.args[0], self.executable)
        self.assertFalse(self.desktop.exists())
        self.taskbar.request.call_args.args[1](True)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.deleteLater()

    def test_permission_error_is_nonfatal_and_never_retries_with_elevation(self):
        dialog = ShortcutDialog(None, self.executable, self.desktop, self.taskbar)
        with patch('startup_shortcuts.create_shortcut', side_effect=PermissionError) as create:
            dialog.create()
            create.assert_called_once()
        self.assertFalse(dialog.apply.isEnabled())
        self.assertEqual(dialog.skip.text(), '닫기')
        self.assertFalse(self.desktop.exists())
        dialog.deleteLater()
        owner = SimpleNamespace(config=default_config(), modal=nullcontext, persist=Mock())
        with patch('startup_shortcuts.offer_shortcuts', side_effect=PermissionError):
            maybe_offer_shortcuts(owner)
        self.assertTrue(owner.config['shortcuts_prompted'])

    def test_unavailable_taskbar_is_disabled_and_existing_desktop_is_preserved(self):
        pinning = SimpleNamespace(available=True, begin=Mock())
        with patch('windows_shortcuts.QEventLoop'):
            self.assertIsNone(TaskbarPinning.is_pinned(pinning))
        self.desktop.parent.mkdir()
        self.desktop.write_bytes(b'existing user file')
        unavailable = SimpleNamespace(available=False)
        dialog = ShortcutDialog(None, self.executable, self.desktop, unavailable)
        self.assertFalse(dialog.desktop.isEnabled())
        self.assertFalse(dialog.taskbar_box.isEnabled())
        self.assertFalse(dialog.apply.isEnabled())
        dialog.deleteLater()
        fake = Mock(available=False)
        fake.is_pinned.return_value = None
        with patch('startup_shortcuts.TaskbarPinning', return_value=fake), \
                patch('startup_shortcuts.desktop_shortcut', return_value=self.desktop), \
                patch('startup_shortcuts.ShortcutDialog') as dialog_class:
            offer_shortcuts(None, self.executable)
            dialog_class.assert_not_called()
        self.assertEqual(self.desktop.read_bytes(), b'existing user file')

    def test_both_choices_off_disable_add_and_pin_failure_stays_dismissible(self):
        dialog = ShortcutDialog(None, self.executable, self.desktop, self.taskbar)
        dialog.desktop.setChecked(False)
        self.assertFalse(dialog.apply.isEnabled())
        dialog.taskbar_box.setChecked(True)
        dialog.create()
        self.taskbar.request.call_args.args[1](None)
        self.assertIn('오른쪽 클릭', dialog.status.text())
        self.assertTrue(dialog.skip.isEnabled())
        dialog.deleteLater()
