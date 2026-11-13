"""Extract a portable Blender project, preserving paths relative to the scene."""
import ntpath
from pathlib import PureWindowsPath
import re
import shutil
import stat
import zipfile


def reserved(name):
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(name)
    return PureWindowsPath(name).is_reserved()


def unpack(archive, target):
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 200000:
            raise ValueError('ZIP contains too many entries.')
        limit = min(100 * 1024**3, shutil.disk_usage(target.parent).free)
        if sum(member.file_size for member in members) > limit:
            raise ValueError('Expanded ZIP exceeds available space or the 100 GiB limit.')
        scenes = []
        paths = set()
        entries = []
        for member in members:
            name = member.orig_filename
            parts = name.removesuffix('/').split('/')
            if (any(not part or part in ('.', '..') or part.endswith((' ', '.'))
                    or re.search(r'[<>:"|?*\\\x00-\x1f]', part) or reserved(part)
                    for part in parts) or member.flag_bits & 1
                    or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError('ZIP contains an unsafe path, link, or encrypted entry.')
            key = '/'.join(parts).casefold()
            if key in paths:
                raise ValueError('ZIP contains duplicate paths.')
            paths.add(key)
            if '__MACOSX' in parts or parts[-1].startswith('._'):
                continue
            path = target.joinpath(*parts)
            entries.append((member, path))
            if not member.is_dir() and path.suffix.lower() == '.blend':
                scenes.append(path)
        if len(scenes) != 1:
            raise ValueError('Include exactly one .blend file and its cache folders in the ZIP.')
        target.mkdir()
        try:
            for member, path in entries:
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, path.open('xb') as dest:
                        shutil.copyfileobj(source, dest, 1024*1024)
        except Exception:
            shutil.rmtree(target)
            raise
        return scenes[0]
