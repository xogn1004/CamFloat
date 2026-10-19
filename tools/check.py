"""Run quick or selected regression checks using an isolated settings profile."""
import argparse
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'quick': ('test_smoke', 'test_check_runner'),
    'audio': ('test_audio_isolation',),
    'cameras': ('test_simple_registration', 'test_camera_management'),
    'files': ('test_camera_archive',),
    'window': ('test_layout_sessions', 'test_view_ui', 'test_chrome_gestures'),
    'shortcuts': ('test_startup_shortcuts',),
    'startup': ('test_startup_timing',),
    'ptz': ('test_camera_ptz_trial', 'test_camera_onvif_trial', 'test_camera_onvif_compat',
            'test_direction_control', 'test_direction_popup', 'test_ptz_dispatch'),
    'talkback': ('test_camera_talkback_trial',),
    'android': ('test_android_camera_app',),
    'full': (),
}
DESCRIPTIONS = {
    'quick': 'Basic settings, registration, archive, version and empty player lifecycle',
    'audio': 'Independent engine audio output',
    'cameras': 'Registration and camera management',
    'files': 'Camera import/export format',
    'window': 'Layouts, selection, fullscreen and toolbar gestures',
    'shortcuts': 'First-run shortcuts with simulated pin consent',
    'startup': 'Lazy imports and first-paint timings with an empty profile',
    'ptz': 'Direction panel, camera binding, cancellation and protocol with fake cameras',
    'talkback': 'Generated speaker tone and connection cleanup with fake cameras; no microphone',
    'android': 'USB APK collector with fake ADB; no real phone or app data access',
    'full': 'All unit/regression tests; network and packaged EXE QC are separate',
}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('groups', nargs='*', metavar='GROUP')
    parser.add_argument('--list', action='store_true', help='List groups without running checks')
    args = parser.parse_args(argv)
    args.groups = list(dict.fromkeys(args.groups or ['quick']))
    if any(group not in PROFILES for group in args.groups):
        parser.error('Choose groups from: ' + ', '.join(PROFILES))
    if 'full' in args.groups and len(args.groups) != 1:
        parser.error('Run full on its own')
    return args


def modules_for(groups):
    return tuple(dict.fromkeys(module for group in groups for module in PROFILES[group]))


def source_version():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    return next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets))


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.console.write(text)
        self.log.write(text)

    def flush(self):
        self.console.flush()
        self.log.flush()


def main(argv=None):
    args = arguments(argv)
    if args.list:
        for group, description in DESCRIPTIONS.items():
            print(f'{group:10} {description}')
        return 0
    sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
    output = ROOT / 'verification/current/checks' / '+'.join(args.groups)
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    previous = os.environ.get('CAMFLOAT_DATA_DIR')
    try:
        with tempfile.TemporaryDirectory(prefix='CamFloat-check-') as profile:
            os.environ['CAMFLOAT_DATA_DIR'] = profile
            loader = unittest.TestLoader()
            if args.groups == ['full']:
                suite = loader.discover(str(ROOT / 'tests'), pattern='test_*.py')
            else:
                suite = loader.loadTestsFromNames(modules_for(args.groups))
            with (output / 'latest.log').open('w', encoding='utf-8') as log:
                result = unittest.TextTestRunner(stream=Tee(sys.stderr, log), verbosity=2).run(suite)
            report = dict(version=source_version(), groups=args.groups,
                          modules=list(modules_for(args.groups)), tests=result.testsRun,
                          failures=len(result.failures), errors=len(result.errors),
                          skipped=len(result.skipped), seconds=round(time.perf_counter() - started, 3),
                          ok=result.wasSuccessful() and result.testsRun > 0, isolated_settings=True,
                          real_camera_access=False, network_qc_run=False, packaged_exe_qc_run=False)
    finally:
        if previous is None:
            os.environ.pop('CAMFLOAT_DATA_DIR', None)
        else:
            os.environ['CAMFLOAT_DATA_DIR'] = previous
    (output / 'latest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"\n{'PASS' if report['ok'] else 'FAIL'}: {report['tests']} checks, {report['seconds']:.3f}s")
    print('Report: ' + (output / 'latest.json').relative_to(ROOT).as_posix())
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
