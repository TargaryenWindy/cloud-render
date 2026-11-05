"""Encode image checkpoints once, using Blender's own FFmpeg settings."""
import bpy
import json
import sys
from pathlib import Path

args = sys.argv[sys.argv.index('--') + 1:]
folder = Path(args[0])
plan = json.loads((folder / 'checkpoint.json').read_text())
scene = bpy.context.scene
scene.sequence_editor_clear()
scene.use_nodes = False
scene.render.use_compositing = False
scene.render.use_sequencer = True
scene.render.use_multiview = False
scene.render.resolution_x, scene.render.resolution_y = plan['width'], plan['height']
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = plan['pixel_aspect_x']
scene.render.pixel_aspect_y = plan['pixel_aspect_y']
scene.render.fps, scene.render.fps_base = plan['fps'], plan['fps_base']
scene.frame_start, scene.frame_end, scene.frame_step = 1, len(plan['frames']), 1
if hasattr(scene.render.image_settings, 'media_type'):
    scene.render.image_settings.media_type = 'VIDEO'
scene.render.image_settings.file_format = 'FFMPEG'
settings = dict(plan['video'])
for key in ('format', 'codec'):
    setattr(scene.render.ffmpeg, key, settings.pop(key))
for key, value in settings.items():
    setattr(scene.render.ffmpeg, key, value)
audio = folder / ('encode-audio.wav' if plan['step'] > 1 else 'scene-audio.wav')
with_audio = audio.is_file()
if not with_audio:
    scene.render.ffmpeg.audio_codec = 'NONE'
elif scene.render.ffmpeg.audio_codec == 'NONE':
    scene.render.ffmpeg.audio_codec = {'WEBM': 'OPUS', 'OGG': 'VORBIS', 'AVI': 'PCM',
        'DV': 'PCM', 'MPEG1': 'MP2', 'MPEG2': 'MP2'}.get(scene.render.ffmpeg.format, 'AAC')
scene.render.ffmpeg.use_autosplit = False
scene.render.image_settings.color_mode = plan.get('video_color', 'RGB')
linear = plan['frame_format'] in ('OPEN_EXR', 'HDR')
if linear:
    for key, value in plan['view'].items():
        setattr(scene.view_settings, key, value)
else:
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
scene.sequencer_colorspace_settings.name = 'sRGB'
editor = scene.sequence_editor_create()
strips = editor.strips if hasattr(editor, 'strips') else editor.sequences
if with_audio:
    strips.new_sound('Scene audio', str(audio), channel=2, frame_start=1)
strip = strips.new_image('Rendered frames', str(folder / 'frames' / plan['frames'][0]['file']), channel=1, frame_start=1)
for frame in plan['frames'][1:]:
    strip.elements.append(frame['file'])
strip.frame_final_duration = len(plan['frames'])
scene.render.use_file_extension = True
if hasattr(scene.render, 'save_output'):
    scene.render.save_output = True
extensions = {'MPEG4': '.mp4', 'MKV': '.mkv', 'WEBM': '.webm', 'AVI': '.avi',
              'DV': '.dv', 'FLASH': '.flv', 'MPEG1': '.mpg', 'MPEG2': '.dvd',
              'OGG': '.ogv', 'QUICKTIME': '.mov'}
extension = extensions.get(scene.render.ffmpeg.format)
if not extension:
    raise RuntimeError('Unsupported container extension: ' + scene.render.ffmpeg.format)
scene.render.filepath = str(folder / 'output-building') + extension
print('CLOUD_ENCODING: ' + json.dumps(plan['video']), flush=True)
bpy.ops.render.render(animation=True)
path = Path(scene.render.filepath)
if not path.is_file():
    raise RuntimeError('Blender did not produce the expected movie: ' + str(path))
(folder / 'encode-result.json').write_text(json.dumps({'file': path.name}))
