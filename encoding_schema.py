"""Discover encoding options from the installed Blender."""
import bpy, json, sys
from pathlib import Path

def describe(p):
    item = dict(label=p.name, description=p.description, type=p.type)
    if p.type == 'ENUM':
        item['choices'] = [[e.identifier, e.name] for e in p.enum_items if e.identifier]
    elif p.type in ('INT', 'FLOAT'):
        item.update(min=p.hard_min, max=p.hard_max)
    return item

schema = {}
for p in bpy.context.scene.render.ffmpeg.bl_rna.properties:
    if not p.is_readonly and not p.identifier.startswith('audio_') and p.identifier != 'use_autosplit':
        schema['video_' + p.identifier] = describe(p)
images = bpy.context.scene.render.image_settings.bl_rna.properties['file_format']
schema['frame_format'] = dict(label='Saved frame format', type='ENUM', choices=[
    [e.identifier, e.name] for e in images.enum_items if e.identifier not in ('FFMPEG', 'OPEN_EXR_MULTILAYER')])
schema['video_color_mode'] = describe(bpy.context.scene.render.image_settings.bl_rna.properties['color_mode'])
schema['video_color_mode']['label'] = 'Video color / alpha channels'
for name in ('color_depth', 'color_mode', 'compression', 'quality', 'exr_codec', 'tiff_codec', 'jpeg2k_codec'):
    prop = bpy.context.scene.render.image_settings.bl_rna.properties.get(name)
    if prop:
        schema['frame_' + name] = describe(prop)
Path(sys.argv[sys.argv.index('--') + 1]).write_text(json.dumps(schema))
