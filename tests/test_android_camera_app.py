"""Read-only APK collection scope checks with fake ADB and synthetic ZIPs."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import android_camera_app as tool


def apk(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('classes.dex', b'avSendIOCtrl preset privacy SHOULD_NOT_PRINT_SECRET')
        archive.writestr('lib/arm64-v8a/libAVAPIs.so', b'avClientStart')
        archive.writestr('../../never-extract.txt', b'Not extracted')


class AndroidCameraAppTests(unittest.TestCase):
    def test_paths_accept_only_expected_apks_and_reject_escapes(self):
        remote = '/data/app/~~example/com.cctv.iptime-example/base.apk'
        self.assertEqual(tool.apk_paths(('package:' + remote).encode()), [remote])
        for data in (b'package:/data/data/com.cctv.iptime/accounts.xml',
                     b'package:/data/app/../data/base.apk', b'package:/data/app/pkg/base.apk;reboot',
                     b'package:/data/app/pkg/base.apk\x00', b'',
                     b'package:/data/app/one/base.apk\npackage:/data/app/two/base.apk'):
            with self.subTest(data=data), self.assertRaises(tool.InvestigationError):
                tool.apk_paths(data)

    def test_apk_scanned_as_data_without_extraction_or_raw_strings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'base.apk'
            apk(path)
            report = tool.inspect_apk(path)
            self.assertTrue(report['sdk_markers']['ThroughTek_TUTK_candidate'])
            self.assertEqual(report['control_word_occurrences']['preset'], 1)
            self.assertEqual(report['native_libraries'], ['lib/arm64-v8a/libAVAPIs.so'])
            self.assertNotIn('SHOULD_NOT_PRINT_SECRET', json.dumps(report))
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ['base.apk'])

    def test_unauthorized_usb_does_not_collect_any_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(tool, 'adb_run',
                return_value=subprocess.CompletedProcess([], 1, b'', b'unauthorized')) as run:
            with self.assertRaises(tool.InvestigationError):
                tool.collect('adb.exe', Path(folder) / 'output')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[1], ['get-state'])
            self.assertFalse((Path(folder) / 'output').exists())

    def test_collection_only_queries_fixed_package_and_pulls_returned_apk(self):
        calls = []
        remote = '/data/app/example/com.cctv.iptime-example/base.apk'
        def adb(adb_path, args, timeout=20):
            calls.append(args)
            if args == ['get-state']:
                return subprocess.CompletedProcess([], 0, b'device\n', b'')
            if args == ['shell', 'pm', 'path', 'com.cctv.iptime']:
                return subprocess.CompletedProcess([], 0, ('package:' + remote + '\n').encode(), b'')
            if args[0] == 'pull':
                self.assertEqual(args[1], remote)
                apk(Path(args[2]))
                return subprocess.CompletedProcess([], 0, b'', b'')
            self.fail('Unexpected phone command')
        with tempfile.TemporaryDirectory() as folder, patch.object(tool, 'adb_run', side_effect=adb), redirect_stdout(io.StringIO()):
            report = tool.collect('adb.exe', Path(folder))
            self.assertEqual(len(calls), 3)
            self.assertTrue((Path(folder) / 'base.apk').is_file())
            self.assertFalse((Path(folder) / 'base.apk.part').exists())
            self.assertFalse(report['account_data_collected'])
            self.assertFalse(report['phone_modified'])
            self.assertEqual(report['package'], 'com.cctv.iptime')

    def test_adb_is_usb_only_without_shell_interpolation(self):
        completed = subprocess.CompletedProcess([], 0, b'device\n', b'')
        with patch.object(tool.subprocess, 'run', return_value=completed) as run:
            tool.adb_run('adb.exe', ['get-state'])
        self.assertEqual(run.call_args.args[0], ['adb.exe', '-d', 'get-state'])
        self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
