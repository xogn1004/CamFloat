"""The default stays quick; full regression must be explicitly selected."""
from contextlib import redirect_stderr
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import package_release

spec = importlib.util.spec_from_file_location('camfloat_check', Path(__file__).resolve().parents[1] / 'tools/check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CheckSelection(unittest.TestCase):
    def test_default_is_quick_and_excludes_network(self):
        args = check.arguments([])
        self.assertEqual(args.groups, ['quick'])
        self.assertEqual(check.modules_for(args.groups), ('test_smoke', 'test_check_runner'))

    def test_multiple_groups_deduplicate(self):
        self.assertEqual(check.arguments(['audio', 'files', 'audio']).groups, ['audio', 'files'])
        self.assertEqual(check.modules_for(['audio', 'audio']), ('test_audio_isolation',))

    def test_full_and_unknown_groups_require_explicit_valid_selection(self):
        self.assertEqual(check.arguments(['full']).groups, ['full'])
        for argv in (['quick', 'full'], ['unknown']):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                check.arguments(argv)
            self.assertEqual(error.exception.code, 2)

    def test_list_does_not_run_tests(self):
        self.assertTrue(check.arguments(['--list']).list)

    def test_prerelease_packaging_rejects_published_folder_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'version_info.txt').write_text("StringStruct('ProductVersion', '1.0.1-dev.1')", encoding='utf-8')
            with patch.object(package_release, 'ROOT', root), patch.object(package_release, 'RELEASE', root / 'release/CamFloat'):
                with self.assertRaisesRegex(RuntimeError, '--staged'):
                    package_release.prepare()
            self.assertFalse((root / 'release').exists())
