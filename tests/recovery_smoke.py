"""Real Blender image pause/resume, partial preview, lossless encode and ZIP test."""
import hashlib, json, os, subprocess, sys, uuid, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery
import dependencies
root = Path(__file__).resolve().parents[1]
folder = root / 'data' / ('frames-smoke-' + uuid.uuid4().hex)
folder.mkdir(parents=True)
blender = dependencies.find('blender')
assert blender, 'Run the setup launcher first.'
project = folder / 'project.blend'
expr = "import bpy; s=bpy.context.scene; s.render.engine='CYCLES'; s.cycles.samples=1; s.render.resolution_x=64; s.render.resolution_y=64; s.render.resolution_percentage=100; s.frame_start=3; s.frame_end=13; s.frame_step=2; s.render.fps=30; setattr(s.render.image_settings,'media_type','VIDEO') if hasattr(s.render.image_settings,'media_type') else None; s.render.image_settings.file_format='FFMPEG'; s.render.ffmpeg.format='MKV'; s.render.ffmpeg.codec='FFV1'; bpy.ops.wm.save_as_mainfile(filepath=" + repr(str(project)) + ")"
subprocess.run([blender, '--background', '--factory-startup', '--python-exit-code', '1', '--python-expr', expr], check=True, stdout=subprocess.DEVNULL)
command = [blender, '--background', '--disable-autoexec', str(project), '--python-exit-code', '1', '--python', str(root/'render.py'), '--', str(folder)]
def render(stop=False):
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with (folder/'render.log').open('ab') as log:
        for line in proc.stdout:
            log.write(line)
            if stop and b'CLOUD_CHECKPOINT:' in line:
                (folder/'stop.request').touch()
    assert proc.wait() == 0, (folder/'render.log').read_text(errors='replace')[-4000:]
render(stop=True)
plan = recovery.validate(folder)
assert 0 < len(plan['frames']) < 6, plan
first = folder/'frames'/plan['frames'][0]['file']
digest = hashlib.sha256(first.read_bytes()).hexdigest()
saved = len(plan['frames'])
preview = recovery.encode(folder, blender, partial=True)
assert int(recovery.probe(preview)[0]['nb_read_frames']) == saved
print(f'Partial preview: {saved} frames.', flush=True)
(folder/'stop.request').unlink()
render()
assert hashlib.sha256(first.read_bytes()).hexdigest() == digest
plan = recovery.validate(folder)
assert [f['frame'] for f in plan['frames']] == [3,5,7,9,11,13]
output = recovery.encode(folder, blender)
video = next(s for s in recovery.probe(output) if s['codec_type']=='video')
assert output.suffix == '.mkv', output
assert (video['codec_name'], int(video['nb_read_frames']), video['r_frame_rate']) == ('ffv1',6,'30/1'), video
# Override only final codec/container after a full frame render: no image re-render.
(folder/'render-settings.json').write_text(json.dumps({'video_format':'MPEG4','video_codec':'H264','video_constant_rate_factor':'HIGH'}))
render()
assert hashlib.sha256(first.read_bytes()).hexdigest() == digest
output = recovery.encode(folder, blender)
assert output.suffix == '.mp4'
assert int(recovery.probe(output)[0]['nb_read_frames']) == 6
recovery.finish_frames(folder, keep=True)
assert not (folder/'frames').exists()
with zipfile.ZipFile(folder/'frames.zip') as archive:
    assert len([n for n in archive.namelist() if n.endswith('.png')]) == 6
    assert archive.testzip() is None
assert output.exists()
print('PASS: resume, step=2, file codec inheritance, override without re-render, verified video and frame ZIP. '+str(folder), flush=True)
