"""Find installed tools; install only missing tools in this project's tools directory."""
import argparse
from functools import lru_cache
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / 'tools'
MANIFEST = TOOLS / 'paths.json'
WINDOWS = os.name == 'nt'


def candidates(name):
    override = os.environ.get(name.upper() + '_PATH')
    if override:
        yield override
    if name == 'blender':
        roots = ([Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam', Path('C:/Program Files/Steam')]
                 if WINDOWS else [Path.home()/'.local/share/Steam', Path.home()/'.steam/steam'])
        for root in list(roots):
            vdf = root/'steamapps/libraryfolders.vdf'
            if vdf.exists():
                roots.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors='replace')))
        for root in roots:
            yield root/'steamapps/common/Blender'/('blender.exe' if WINDOWS else 'blender')
        if WINDOWS:
            yield from Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('Blender Foundation/Blender */blender.exe')
        else:
            yield '/opt/blender/blender'
    found = shutil.which(name)
    if found:
        yield found
    if WINDOWS and name in ('ffmpeg', 'ffprobe'):
        yield Path('C:/av1')/(name+'.exe')
    if MANIFEST.exists():
        value = json.loads(MANIFEST.read_text()).get(name)
        if value:
            yield ROOT/value
    yield TOOLS/(name + ('.exe' if WINDOWS else ''))


@lru_cache(maxsize=64)
def executable_check(path, name, modified):
    try:
        result = subprocess.run([path, '-version' if name in ('ffmpeg','ffprobe') else '--version'],
            capture_output=True, timeout=30)
        return result.returncode == 0, (result.stderr or result.stdout).decode(errors='replace')[-2000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def find(name, check=True):
    for candidate in candidates(name):
        path = Path(candidate)
        if not path.is_file():
            continue
        if check and not executable_check(str(path),name,path.stat().st_mtime_ns)[0]:
            continue
        return str(path.resolve())
    return None


def read_url(url):
    req = urllib.request.Request(url, headers={'User-Agent':'RenderDesk-setup'})
    return urllib.request.urlopen(req, timeout=120)


def download(url, target, checksum=None):
    print('Downloading ' + url.rsplit('/',1)[-1] + ' ...', flush=True)
    partial = target.with_name(target.name+'.part')
    try:
        digest = hashlib.sha256()
        received = 0
        last_report = time.monotonic()
        with read_url(url) as source, partial.open('wb') as out:
            while chunk := source.read(1024*1024):
                digest.update(chunk); out.write(chunk)
                received += len(chunk)
                if time.monotonic() - last_report >= 10:
                    print(f"  {received // (1024*1024)} MiB downloaded", flush=True)
                    last_report = time.monotonic()
        if checksum and digest.hexdigest().lower() != checksum.lower():
            raise RuntimeError('Download checksum mismatch; rerun setup.')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    def check(name):
        if not (root/name).resolve().is_relative_to(root):
            raise RuntimeError('Unsafe archive path: '+name)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                check(member.filename)
                bundle.extract(member, root)
    else:
        with tarfile.open(archive) as bundle:
            for member in bundle:
                check(member.name)
                if member.issym():
                    check(str(Path(member.name).parent/member.linkname))
                elif member.islnk():
                    check(member.linkname)
                elif not (member.isfile() or member.isdir()):
                    raise RuntimeError('Unsupported archive member: '+member.name)
                if hasattr(tarfile, 'data_filter'):
                    bundle.extract(member, root, filter='data')
                else:
                    bundle.extract(member, root)


def release(repo):
    with read_url('https://api.github.com/repos/'+repo+'/releases/latest') as response:
        return json.load(response)


def install_archive(url, group, names, checksum=None):
    TOOLS.mkdir(exist_ok=True)
    # Temporary downloads disappear on success or failure. Runtime binaries stay local.
    with tempfile.TemporaryDirectory(prefix='setup-', dir=TOOLS) as temp:
        temp = Path(temp)
        archive = temp/'download'
        download(url, archive, checksum)
        print('Extracting '+group+' into the app folder...', flush=True)
        extract(archive, temp/'unpacked')
        result = {}
        for name in names:
            executable = name + ('.exe' if WINDOWS else '')
            matches = list((temp/'unpacked').rglob(executable))
            if not matches:
                raise RuntimeError('Download does not contain '+executable)
            result[name] = matches[0].relative_to(temp/'unpacked')
        target = TOOLS/group
        if target.exists():
            # A previous failed install may exist; never overwrite it in place.
            import uuid
            target = TOOLS/(group+'-'+uuid.uuid4().hex[:8])
        (temp/'unpacked').rename(target)
        return {name: str((target/path).relative_to(ROOT)) for name,path in result.items()}


def blender_download():
    series = os.environ.get('BLENDER_SERIES')
    if series and not re.fullmatch(r'\d+\.\d+',series):
        raise RuntimeError('BLENDER_SERIES must look like 4.5 or 5.2.')
    if series:
        series_options = [series]
    else:
        with read_url('https://download.blender.org/release/') as response:
            index = response.read().decode()
        series_options = sorted(set(re.findall(r'href="Blender(\d+\.\d+)/"', index)), key=lambda v:tuple(map(int,v.split('.'))), reverse=True)
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('arm64','aarch64') else 'x64'
    suffix = ('windows-'+arch+'.zip') if WINDOWS else ('linux-'+arch+'.tar.xz')
    files = set()
    for series in series_options:
        base = 'https://download.blender.org/release/Blender'+series+'/'
        with read_url(base) as response:
            listing = response.read().decode()
        files = set(re.findall(r'blender-(\d+\.\d+\.\d+)-'+re.escape(suffix), listing))
        if files:
            break
    if not files:
        raise RuntimeError('No official Blender archive for this platform/series. Set BLENDER_PATH to an installed build.')
    version = max(files, key=lambda v:tuple(map(int,v.split('.'))))
    name = 'blender-'+version+'-'+suffix
    with read_url(base+'blender-'+version+'.sha256') as response:
        checks = response.read().decode()
    checksum = next((line.split()[0] for line in checks.splitlines() if line.split()[-1].lstrip('*') == name), None)
    if not checksum:
        raise RuntimeError('Missing official Blender checksum.')
    return install_archive(base+name, 'blender', ['blender'], checksum)


def ffmpeg_download():
    machine = platform.machine().lower()
    if machine not in ('amd64','x86_64'):
        raise RuntimeError('Automatic FFmpeg setup currently supports x86-64. Install FFmpeg/FFprobe and put them on PATH on ARM.')
    info = release('BtbN/FFmpeg-Builds')
    suffix = '-win64-gpl.zip' if WINDOWS else '-linux64-gpl.tar.xz'
    asset = next(a for a in info['assets'] if a['name'].startswith('ffmpeg-master-') and a['name'].endswith(suffix))
    checks_asset = next(a for a in info['assets'] if a['name']=='checksums.sha256')
    with read_url(checks_asset['browser_download_url']) as response:
        checks = response.read().decode()
    checksum = next(line.split()[0] for line in checks.splitlines() if line.split()[-1].lstrip('*') == asset['name'])
    return install_archive(asset['browser_download_url'], 'ffmpeg', ['ffmpeg','ffprobe'], checksum)


def cloudflared_download():
    arch = 'arm64' if platform.machine().lower() in ('arm64','aarch64') else 'amd64'
    name = 'cloudflared-'+('windows-' if WINDOWS else 'linux-')+arch+('.exe' if WINDOWS else '')
    info = release('cloudflare/cloudflared')
    asset = next(a for a in info['assets'] if a['name']==name)
    target = TOOLS/('cloudflared.exe' if WINDOWS else 'cloudflared')
    digest = asset.get('digest') or ''
    download(asset['browser_download_url'], target, digest.removeprefix('sha256:') or None)
    if not WINDOWS:
        target.chmod(0o755)
    return {'cloudflared':str(target.relative_to(ROOT))}


def ensure(remote=False):
    if platform.system() not in ('Windows','Linux'):
        raise RuntimeError('Automatic setup supports Windows and Linux.')
    TOOLS.mkdir(exist_ok=True)
    paths = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for names, install in [(['blender'], blender_download), (['ffmpeg','ffprobe'], ffmpeg_download),
                           *([(['cloudflared'],cloudflared_download)] if remote else [])]:
        missing = [name for name in names if not find(name, check=True)]
        if missing:
            for name in missing:
                existing = find(name, check=False)
                if existing:
                    detail = executable_check(existing,name,Path(existing).stat().st_mtime_ns)[1]
                    raise RuntimeError(name+' is present but cannot run; it will not be downloaded again. '+detail)
                if os.environ.get(name.upper()+'_PATH'):
                    raise RuntimeError(name.upper()+'_PATH is not runnable; correct or unset it before setup.')
            paths.update(install())
            tmp = MANIFEST.with_suffix('.tmp');tmp.write_text(json.dumps(paths,indent=2));tmp.replace(MANIFEST)
        for name in names:
            path = find(name,check=True)
            if not path:
                raise RuntimeError(name+' could not run. On Linux check GPU drivers and shared system libraries (see README).')
            print(name+': '+path,flush=True)
    return paths

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--remote',action='store_true')
    try: ensure(parser.parse_args().remote)
    except Exception as exc: raise SystemExit('Setup failed: '+str(exc))
