"""Validate image checkpoints, encode videos, and validate legacy checkpoints."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import dependencies

def tool(name):
    return dependencies.find(name)


def probe(path):
    if not tool('ffprobe'):
        raise RuntimeError('FFprobe is required for video recovery.')
    result = subprocess.run([tool('ffprobe'), '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(path)], capture_output=True, check=True)
    return json.loads(result.stdout)['streams']

def signature(streams):
    fields = ('codec_type', 'codec_name', 'profile', 'width', 'height', 'pix_fmt', 'r_frame_rate', 'time_base', 'sample_rate', 'channels', 'channel_layout')
    return [tuple(s.get(k) for k in fields) for s in streams if s['codec_type'] == 'video']

def legacy_validate(folder):
    checkpoint = folder / 'checkpoint.json'
    if not checkpoint.exists():
        return None
    plan = json.loads(checkpoint.read_text())
    expected, previous = plan['start'], None
    for segment in plan['segments']:
        if segment['first'] != expected or Path(segment['file']).name != segment['file']:
            raise RuntimeError('Invalid checkpoint sequence.')
        streams = probe(folder / 'segments' / segment['file'])
        video = next(s for s in streams if s['codec_type'] == 'video')
        if int(video.get('nb_read_frames', 0)) != (segment['last']-segment['first']) // plan['step'] + 1:
            raise RuntimeError('Incomplete video checkpoint.')
        current = signature(streams)
        if previous is not None and current != previous:
            raise RuntimeError('Video checkpoint streams differ.')
        previous = current
        expected = segment['last'] + plan['step']
    return plan

def safe_remove(folder, name):
    """Delete only an explicitly named child without following redirected paths."""
    folder = Path(folder).resolve()
    path = folder / name
    if path.is_symlink() or path.resolve().parent != folder:
        raise RuntimeError('Refusing cleanup outside the job folder.')
    if path.is_dir():
        # Windows junctions inside a frame directory must not be traversed.
        for child in path.rglob('*'):
            if child.is_symlink() or not child.resolve().is_relative_to(path.resolve()):
                raise RuntimeError('Refusing cleanup through a redirected directory.')
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)

def discard(folder):
    for name in ('scene-audio.wav', 'encode-audio.wav', 'checkpoint.json', 'frames', 'segments', 'preview.mp4', 'frames.zip',
                 'preview-result.json', 'encode-result.json', 'full-render.request'):
        safe_remove(folder, name)

def validate(folder):
    checkpoint = folder / 'checkpoint.json'
    if not checkpoint.exists():
        return None
    plan = json.loads(checkpoint.read_text())
    if plan.get('version') != 2:
        return legacy_validate(folder)
    expected = plan['start']
    for frame in plan['frames']:
        if frame['frame'] != expected or Path(frame['file']).name != frame['file']:
            raise RuntimeError('Invalid image checkpoint sequence.')
        path = folder / 'frames' / frame['file']
        if not path.is_file() or path.stat().st_size != frame['size'] or frame['size'] == 0:
            raise RuntimeError('Missing or incomplete saved frame.')
        expected += plan['step']
    return plan

def encode(folder, blender):
    plan = validate(folder)
    if not plan or plan.get('version') != 2:
        raise RuntimeError('Old video checkpoints require Restart to render image frames.')
    if not plan['frames'] or plan['frames'][-1]['frame'] + plan['step'] <= plan['end']:
        raise RuntimeError('Animation is not fully rendered.')
    audio = folder / 'scene-audio.wav'
    if plan['step'] > 1:
        adjusted = folder / 'encode-audio.wav'
        adjusted.unlink(missing_ok=True)
        if audio.exists():
            # Each saved frame advances the source timeline by step frames.
            subprocess.run([tool('ffmpeg'), '-v', 'error', '-i', str(audio), '-af',
                            f"atempo={plan['step']}", str(adjusted)], check=True)
    result_file = folder / 'encode-result.json'
    result_file.unlink(missing_ok=True)
    with (folder / 'render.log').open('ab') as logfile:
        result = subprocess.run([blender, '--background', '--factory-startup', '--disable-autoexec',
            '--python-exit-code', '1', '--python', str(Path(__file__).with_name('encode.py')),
            '--', str(folder)], stdout=logfile, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not result_file.exists():
        raise RuntimeError('Video encoding failed. Frames are safe; check the log and adjust output settings, then Resume.')
    name = json.loads(result_file.read_text())['file']
    if Path(name).name != name:
        raise RuntimeError('Invalid encoded output path.')
    building = folder / name
    streams = probe(building)
    if audio.exists() and not any(s['codec_type'] == 'audio' for s in streams):
        raise RuntimeError('Encoded movie is missing the scene audio. Frames retained.')
    video = next(s for s in streams if s['codec_type'] == 'video')
    if int(video.get('nb_read_frames', 0)) != len(plan['frames']):
        raise RuntimeError('Encoded video frame count does not match saved images. Frames retained.')
    target = folder / ('output' + building.suffix)
    building.replace(target)
    (folder / 'output.json').write_text(json.dumps({'file': target.name}))
    return target

def output_path(folder):
    meta = folder / 'output.json'
    name = json.loads(meta.read_text())['file'] if meta.exists() else 'output.mp4'
    if Path(name).name != name or not name.startswith('output.'):
        raise RuntimeError('Invalid output filename.')
    return folder / name

def finish_frames(folder, keep=False):
    """Called only after the final movie has passed frame-count verification."""
    import zipfile
    if keep:
        plan = validate(folder)
        archive = folder / 'frames-building.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for frame in plan['frames']:
                bundle.write(folder / 'frames' / frame['file'], frame['file'])
            bundle.write(folder / 'checkpoint.json', 'manifest.json')
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise RuntimeError('Frame archive verification failed. Images retained.')
        archive.replace(folder / 'frames.zip')
    else:
        safe_remove(folder, 'frames.zip')
    for name in ('scene-audio.wav', 'encode-audio.wav', 'frames', 'segments', 'checkpoint.json', 'preview.mp4', 'preview-result.json', 'encode-result.json'):
        safe_remove(folder, name)
    final = output_path(folder)
    for path in folder.iterdir():
        if (path.name.startswith(('output-building', 'preview-building', 'checkpoint-')) or
            (path.name.startswith('output.') and path != final and path.name != 'output.json')):
            safe_remove(folder, path.name)
