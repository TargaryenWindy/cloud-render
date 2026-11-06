"""Render atomic image checkpoints using the installed Blender."""
import bpy
import json
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_settings import apply, select_gpu

folder = Path(sys.argv[sys.argv.index('--') + 1])
scene = bpy.context.scene
options_file = folder / 'render-settings.json'
options = json.loads(options_file.read_text()) if options_file.exists() else {}
apply(scene, options)
select_gpu(bpy, scene)
first, last, step = scene.frame_start, scene.frame_end, scene.frame_step
video = {p.identifier: getattr(scene.render.ffmpeg, p.identifier)
         for p in scene.render.ffmpeg.bl_rna.properties
         if not p.is_readonly and p.type in ('ENUM', 'INT', 'FLOAT', 'BOOLEAN')}
if scene.render.image_settings.file_format != 'FFMPEG':
    video.update(format='MPEG4', codec='H264', constant_rate_factor='HIGH')
video_color = options.get('video_color_mode', scene.render.image_settings.color_mode
                          if scene.render.image_settings.file_format == 'FFMPEG' else 'RGB')
video.update({k[6:]: v for k, v in options.items() if k.startswith('video_') and k != 'video_color_mode'})
video.update(use_autosplit=False)
for key in ('format', 'codec'):
    setattr(scene.render.ffmpeg, key, video[key])
for key, value in video.items():
    if key not in ('format', 'codec'):
        setattr(scene.render.ffmpeg, key, value)
if hasattr(scene.render.image_settings, 'media_type'):
    scene.render.image_settings.media_type = 'IMAGE'
scene.render.image_settings.file_format = options.get('frame_format', 'PNG')
for key, value in options.items():
    if key.startswith('frame_') and key != 'frame_format':
        setattr(scene.render.image_settings, key[6:], value)
scene.render.use_file_extension = True
scene.render.use_multiview = False
if hasattr(scene.render, 'save_output'):
    scene.render.save_output = True
frames = folder / 'frames'
frames.mkdir(exist_ok=True)
checkpoint = folder / 'checkpoint.json'
plan = json.loads(checkpoint.read_text()) if checkpoint.exists() else {
    'version': 2, 'start': first, 'end': last, 'step': step, 'frames': []}
if plan.get('version') != 2:
    raise RuntimeError('Legacy video checkpoints require Restart for image rendering.')
plan.update(video=video, video_color=video_color, fps=scene.render.fps, fps_base=scene.render.fps_base,
            width=plan.get('width', max(1, scene.render.resolution_x * scene.render.resolution_percentage // 100)),
            height=plan.get('height', max(1, scene.render.resolution_y * scene.render.resolution_percentage // 100)),
            pixel_aspect_x=scene.render.pixel_aspect_x, pixel_aspect_y=scene.render.pixel_aspect_y,
            frame_format=scene.render.image_settings.file_format,
            view={k: getattr(scene.view_settings, k) for k in ('view_transform', 'look', 'exposure', 'gamma')})
if plan['frames']:
    tmp = checkpoint.with_suffix('.tmp')
    tmp.write_text(json.dumps(plan))
    tmp.replace(checkpoint)
print(f'CLOUD_RANGE:{first}:{last}', flush=True)
print('CLOUD_SETTINGS: ' + json.dumps(options), flush=True)
start = plan['frames'][-1]['frame'] + step if plan['frames'] else first
for frame in range(start, last + 1, step):
    if (folder / 'stop.request').exists():
        break
    began = time.monotonic()
    scene.frame_set(frame)
    scene.render.filepath = str(frames / 'writing')
    bpy.ops.render.render(write_still=True)
    saved = Path(scene.render.filepath + scene.render.file_extension)
    if not plan['frames']:
        image = bpy.data.images.load(str(saved), check_existing=False)
        plan['width'], plan['height'] = image.size
        bpy.data.images.remove(image)
    name = f'frame-{len(plan["frames"]):09d}' + scene.render.file_extension
    saved.replace(frames / name)
    plan['frames'].append(dict(file=name, frame=frame, size=(frames / name).stat().st_size))
    tmp = checkpoint.with_suffix('.tmp')
    tmp.write_text(json.dumps(plan))
    tmp.replace(checkpoint)
    finished = datetime.now().astimezone().isoformat(timespec='seconds')
    print(f'Frame {frame} saved at {finished} | Render time {time.monotonic() - began:.2f} s', flush=True)
    print(f'CLOUD_FRAME:{frame}:{first}:{last} seconds={time.monotonic() - began:.6f}', flush=True)
    print(f'CLOUD_CHECKPOINT:{frame}', flush=True)

# Mix the source scene so strip offsets, speakers, volume and mute settings apply.
if plan['frames'] and plan['frames'][-1]['frame'] + step > last and not (folder / 'stop.request').exists():
    audio = folder / 'scene-audio.wav'
    audio.unlink(missing_ok=True)
    if bpy.data.sounds:
        result = bpy.ops.sound.mixdown(filepath=str(audio), container='WAV', codec='PCM', format='S16')
        if 'FINISHED' not in result or not audio.exists():
            raise RuntimeError('Blender could not mix the scene audio.')
        with wave.open(str(audio), 'rb') as mix:
            audible = any(block.strip(b'\0') for block in iter(lambda: mix.readframes(65536), b''))
        if not audible:
            audio.unlink()
