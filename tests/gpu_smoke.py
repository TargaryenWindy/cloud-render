"""Exercise installed Blender's real GPU and verify rendered override values."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery
root = Path(__file__).resolve().parents[1]
folder = root / 'data/gpu-smoke'
folder.mkdir(exist_ok=True)
blender = r'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe'
project = folder / 'project.blend'
expression = "import bpy; s=bpy.context.scene; s.render.engine='CYCLES'; s.frame_start=1; s.frame_end=2; bpy.ops.wm.save_as_mainfile(filepath=" + repr(str(project)) + ")"
subprocess.run([blender, '--background', '--factory-startup', '--python-exit-code', '1', '--python-expr', expression], check=True, stdout=subprocess.DEVNULL)
recovery.discard(folder)
(folder/'render-settings.json').write_text(json.dumps({'resolution_x':96,'resolution_y':64,'resolution_percentage':100,'samples':2,'fps':30}))
result = subprocess.run([blender, '--background', '--factory-startup', str(project), '--python-exit-code', '1', '--python', str(root/'render.py'), '--', str(folder)], capture_output=True)
(folder/'render.log').write_bytes(result.stdout + result.stderr)
assert result.returncode == 0, result.stdout[-3000:]
text = result.stdout.decode('utf-8', errors='replace')
assert 'CLOUD_DEVICE: OPTIX | NVIDIA GeForce RTX 3060' in text
assert '"samples": 2' in text
recovery.encode(folder, blender)
video = next(s for s in recovery.probe(folder/'output.mp4') if s['codec_type']=='video')
assert all(s['codec_type'] == 'video' for s in recovery.probe(folder/'output.mp4'))
assert (video['width'],video['height'],video['r_frame_rate'],int(video['nb_read_frames'])) == (96,64,'30/1',2), video
print('Real RTX 3060 OptiX render passed: 96 x 64, 2 samples, 30 fps, 2 frames.')
