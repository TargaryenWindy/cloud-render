import bpy
from pathlib import Path
bpy.ops.wm.read_factory_settings(use_empty=False)
s = bpy.context.scene
s.render.engine = 'BLENDER_EEVEE'
s.render.resolution_x = 64
s.render.resolution_y = 64
s.render.resolution_percentage = 100
s.frame_start = 1
s.frame_end = 2
folder = Path(__file__).resolve().parents[1] / 'data'
folder.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'smoke.blend'))
