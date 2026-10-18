"""Check publishable Git history, document links and prepared release assets.

This is a publication check, not a replacement for app playback/QC tests.
Reports only file/line/reason for findings, never the matched secret text.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def history_check():
    objects = dict(row.partition(' ')[::2] for row in
                   git('rev-list', '--objects', '--all').decode('utf-8').splitlines())
    reader = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    findings = []
    counts = Counter()
    try:
        for oid, path in objects.items():
            reader.stdin.write((oid + '\n').encode('ascii'))
            reader.stdin.flush()
            _, kind, size = reader.stdout.readline().split()
            data = reader.stdout.read(int(size))
            reader.stdout.read(1)
            counts[kind.decode()] += 1
            if kind not in (b'blob', b'commit', b'tag'):
                continue
            if kind == b'blob' and b'\0' in data:
                if not (path.endswith('.ico') or
                        (path.startswith('docs/images/') and path.endswith('.png'))):
                    findings.append(dict(object=oid[:12], path=path, reason='unreviewed-binary'))
                continue
            if kind == b'blob' and re.search(
                    r'(?i)(?:^|/)(?:settings(?:[.-].*)?\.json|\.env(?:\..*)?|'
                    r'.*\.(?:camfloat|pem|pfx|key|pyc)|id_rsa)$', path):
                findings.append(dict(object=oid[:12], path=path, reason='private-file-type'))
            for n, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
                reasons = []
                if re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|'
                             r'AKIA[A-Z0-9]{16})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', line):
                    reasons.append('credential-pattern')
                if re.search(r'(?i)C:[\\/]+(?:Users[\\/]+(?!Public\b|Default\b)[^\s\\/]+|Google\.Drive[\\/]+)', line):
                    reasons.append('personal-absolute-path')
                for match in re.finditer(r'(?i)rtsps?://[^\s\'"<>\)\]\}]+', line):
                    raw = match.group().rstrip(',;`')
                    if any(c in raw for c in '{['):
                        continue  # URL templates and the redaction marker.
                    try:
                        host = urlsplit(raw).hostname or ''
                    except ValueError:
                        host = ''
                    allowed = {'localhost', 'example.com', 'example.org', 'example.net',
                               'host', 'h', 'unfinished', '주소', '도메인', '카메라ip', '...'}
                    # Deliberately invalid URL in the parser rejection tests.
                    invalid_test = path in ('tests/test_regressions.py', 'tools/publication_check.py') and raw.startswith('rtsp://u:p#x@host/')
                    if host not in allowed and not host.startswith(('127.', 'host')) and not invalid_test:
                        reasons.append('non-example-rtsp-host')
                for address in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', line):
                    if address.startswith('127.'):
                        continue
                    if (path, address) in {('tests/test_regressions.py', '192.168.1.24'),
                                           ('dialogs.py', '192.168.0.10'),
                                           ('tools/publication_check.py', '192.168.1.24'),
                                           ('tools/publication_check.py', '192.168.0.10')}:
                        continue  # Reviewed synthetic form-entry examples.
                    reasons.append('non-example-ipv4')
                if reasons:
                    findings.append(dict(object=oid[:12], path=path or '<git-metadata>',
                                         line=n, reasons=sorted(set(reasons))))
    finally:
        reader.stdin.close()
        reader.stdout.close()
        reader.wait()
    return dict(objects=dict(counts), findings=findings)


def document_check():
    failures = []
    paths = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').decode('utf-8').split('\0')
    for name in set(paths):
        path = ROOT / name
        if path.suffix != '.md' or not path.is_file():
            continue
        body = path.read_text(encoding='utf-8')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in body):
            failures.append(dict(path=name, reason='control-character'))
        for target in re.findall(r'\]\(([^)]+)\)', body):
            target = target.split(' "', 1)[0].strip('<>')
            if '://' in target or target.startswith(('#', 'mailto:')):
                continue
            target = unquote(target.split('#', 1)[0])
            if target and not (path.parent / target).exists():
                failures.append(dict(path=name, reason='broken-relative-link', target=target))
    return failures


def asset_check():
    archive = ROOT / 'release/CamFloat-1.0.0-win-x64.zip'
    assert archive.with_suffix('.sha256').read_text().split()[0] == sha256(archive)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, 'ZIP CRC failure'
        names = bundle.namelist()
        assert sorted({n.split('/')[1] for n in names}) == [
            'CamFloat.exe', '_internal', 'licenses', '시작하기.txt']
        assert bundle.read('CamFloat/licenses/CamFloat-MIT.txt') == (ROOT / 'LICENSE').read_bytes()
        assert 'CamFloat/_internal/vlc/plugins/audio_output/libdirectsound_plugin.dll' in names
        from package_release import UNUSED_QT_FILES
        assert not any('CamFloat/_internal/PySide6/' + name in names for name in UNUSED_QT_FILES)
        assert not any(n.lower().endswith(('.camfloat', 'settings.json', '.mp4', '.wav', '.md', '.log')) for n in names)
        exe_hash = hashlib.sha256(bundle.read('CamFloat/CamFloat.exe')).hexdigest()
    source_manifest = json.loads((ROOT / 'docs/third-party-sources.json').read_text())
    for item in source_manifest:
        path = ROOT / 'vendor/source-assets' / item['file']
        assert path.stat().st_size == item['bytes'] and sha256(path) == item['sha256']
        assert item['upstream_checksum_verified']
    return dict(archive_sha256=sha256(archive), archive_bytes=archive.stat().st_size,
                exe_sha256=exe_hash, source_archives=len(source_manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', action='store_true', help='Also check locally prepared ZIP and source archives.')
    args = parser.parse_args()
    # Importing packaging helpers must not require installing CamFloat's GUI.
    import sys
    sys.path.insert(0, str(ROOT))
    report = dict(history=history_check(), document_failures=document_check())
    if args.assets:
        report['assets'] = asset_check()
    report['ok'] = not report['history']['findings'] and not report['document_failures']
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report['ok'] else 1)
