"""Assemble the evidence for a release after the independent checks finish."""
import hashlib
import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import VERSION

root = Path(__file__).resolve().parents[1]
folder = root / 'verification' / 'current'
network = json.loads((folder / 'network-qa.json').read_text(encoding='utf-8'))
packaged = json.loads((folder / 'packaged-check/startup-check.json').read_text(encoding='utf-8'))
unit_log = (folder / 'unit-tests.log').read_text(encoding='utf-8')
match = re.search(r'Ran (\d+) tests in ([\d.]+)s', unit_log)
unit_ok = bool(match and unit_log.rstrip().endswith('OK'))
samples = [s['working_set_mb'] for s in network.get('timeline', [])
           if s['seconds'] >= network['soak_seconds'] - 60 and 'working_set_mb' in s]
manifest = dict(version=VERSION, recorded_at=datetime.now(timezone.utc).isoformat(),
    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    platform=platform.platform(), python=platform.python_version(),
    unit_tests=dict(ok=unit_ok, count=int(match[1]) if match else 0,
                    seconds=float(match[2]) if match else None),
    packaged_self_check=packaged, network=network,
    final_minute_working_set_mb=dict(min=min(samples), max=max(samples)) if samples else None,
    files={})
initial = folder / 'initial-failure-qa.json'
if initial.exists():
    manifest['initial_connection_check'] = json.loads(initial.read_text(encoding='utf-8'))
for relative in ('main.py', 'chrome.py', 'camera_model.py', 'dialogs.py', 'playback.py', 'native_window.py', 'icons.py',
                 'menu_labels.py', 'menu_widgets.py',
                 'single_instance.py', 'CamFloat.spec', 'version_info.txt',
                 'release/CamFloat/CamFloat.exe'):
    manifest['files'][relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
manifest['ok'] = unit_ok and network['ok'] and packaged['ok']
manifest['ok'] = manifest['ok'] and network['version'] == VERSION and packaged['version'] == VERSION
if initial.exists():
    manifest['ok'] = manifest['ok'] and manifest['initial_connection_check']['ok']
(folder / 'summary.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in manifest.items() if k not in ('network', 'files')}, ensure_ascii=False, indent=2))
raise SystemExit(0 if manifest['ok'] else 1)
