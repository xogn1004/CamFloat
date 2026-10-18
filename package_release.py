"""Prepare the user-facing distribution; keep development reports in the repo."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile


ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / 'release' / 'CamFloat'
DEVELOPMENT_FILES = (
    'README.md', 'CHANGELOG.md', 'CODE_REVIEW.md', 'THIRD_PARTY.md',
    'QA-summary.json', 'BUILD-INFO.json',
)


def prepare():
    if RELEASE.is_symlink() or RELEASE.is_junction():
        raise RuntimeError('Release directory must not be a linked directory.')
    allowed = [ROOT / 'release' / 'CamFloat',
               Path(os.environ['LOCALAPPDATA']) / 'CamFloatBuild/current/dist/CamFloat']
    if RELEASE.resolve() not in [path.resolve() for path in allowed]:
        raise RuntimeError('Release directory escaped the workspace.')
    if not (RELEASE / 'CamFloat.exe').is_file() or not (RELEASE / '_internal').is_dir():
        raise RuntimeError('Build release/CamFloat before packaging.')

    # Keep old provenance with the development evidence, rather than shipping it.
    for name in DEVELOPMENT_FILES:
        path = RELEASE / name
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f'Refusing linked release file: {name}')
        if path.is_file():
            if path.suffix == '.json':
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                evidence = ROOT / 'verification' / 'current' / 'distribution'
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / f'{path.stem}-{digest}.json').write_bytes(data)
            path.unlink()

    license_dir = RELEASE / 'licenses'
    if license_dir.is_symlink() or license_dir.is_junction():
        raise RuntimeError('License directory must not be a linked directory.')
    shutil.copytree(ROOT / 'licenses', license_dir, dirs_exist_ok=True)
    # Google Drive source folders can carry the Windows read-only directory
    # flag. Do not make the next isolated PyInstaller build undeletable.
    license_dir.chmod(license_dir.stat().st_mode | stat.S_IWRITE)
    shutil.copy2(ROOT / 'packaging' / '시작하기.txt', RELEASE / '시작하기.txt')
    print('Distribution: CamFloat.exe, _internal/, licenses/, 시작하기.txt')


def archive():
    metadata = (ROOT / 'version_info.txt').read_text(encoding='utf-8')
    match = re.search(r"StringStruct\('ProductVersion', '([\w.-]+)'\)", metadata)
    if not match:
        raise RuntimeError('Product version was not found.')
    output = ROOT / 'release' / f'CamFloat-{match[1]}-win-x64.zip'
    temporary = output.with_suffix('.zip.tmp')
    try:
        # Include only distribution entries, never local reports or user exports.
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in ('CamFloat.exe', '_internal', 'licenses', '시작하기.txt'):
                entry = RELEASE / name
                paths = sorted(entry.rglob('*')) if entry.is_dir() else [entry]
                for path in paths:
                    if path.is_symlink() or path.is_junction():
                        raise RuntimeError(f'Refusing linked archive entry: {path.name}')
                    if path.is_file():
                        bundle.write(path, path.relative_to(RELEASE.parent).as_posix())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output.with_suffix('.sha256').write_text(
        f'{digest}  {output.name}\n', encoding='ascii')
    print(f'Archive: {output.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', action='store_true', help='Also refresh ZIP and SHA-256.')
    parser.add_argument('--staged', action='store_true', help='Package the isolated build without replacing the running app.')
    args = parser.parse_args()
    if args.staged:
        RELEASE = Path(os.environ['LOCALAPPDATA']) / 'CamFloatBuild/current/dist/CamFloat'
    prepare()
    if args.archive:
        archive()
