"""Fetch the pinned official LGPL libVLC package and stage its x64 runtime."""
import hashlib
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
URL = 'https://api.nuget.org/v3-flatcontainer/videolan.libvlc.windows/3.0.23/videolan.libvlc.windows.3.0.23.nupkg'
SHA256 = '39d3035ccc9dcf58206f9888959b78f47f52eb2ee79af7f50b01c3342c279e7f'


def prepare():
    cache = Path(os.environ['LOCALAPPDATA']) / 'CamFloatBuild' / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    package = cache / URL.rsplit('/', 1)[-1]
    if not package.exists():
        temporary = package.with_suffix('.download')
        urllib.request.urlretrieve(URL, temporary)
        temporary.replace(package)
    with package.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SHA256:
            raise RuntimeError('libVLC package checksum mismatch; do not build.')
    destination = ROOT / 'vendor' / 'vlc'
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.is_junction():
        raise RuntimeError('Runtime destination must not be linked.')
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if not name.startswith('build/x64/') or name.endswith('/'):
                continue
            relative = name.removeprefix('build/x64/')
            if relative not in ('libvlc.dll', 'libvlccore.dll') and not relative.startswith(('plugins/', 'hrtfs/', 'lua/')):
                continue
            path = (destination / relative).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe runtime entry.')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
    print('Staged official libVLC 3.0.23 x64 (LGPL package).')


if __name__ == '__main__':
    prepare()
