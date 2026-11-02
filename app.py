import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
import tempfile
import zipfile
import math
from functools import wraps
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, session, redirect
import recovery
import cleanup

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('RENDER_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
if __name__ == '__main__' and os.name == 'nt':
    import msvcrt
    # Keep a lifetime lock so starting the launcher twice cannot create two workers.
    instance_lock = (DATA / 'server.lock').open('a+b')
    instance_lock.write(b'0')
    instance_lock.flush()
    instance_lock.seek(0)
    try:
        msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise SystemExit('Render desk is already running at http://127.0.0.1:7860')
CONFIG = DATA / 'config.json'
if not CONFIG.exists():
    CONFIG.write_text(json.dumps({'password': secrets.token_urlsafe(18), 'secret': secrets.token_hex(32)}))
config = json.loads(CONFIG.read_text())
app = Flask(__name__, static_folder='static')
app.secret_key = config['secret']
app.config.update(MAX_CONTENT_LENGTH=9 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
lock = threading.RLock()
preview_lock = threading.Lock()
process = None
active_id = None
attempts = {}
STATE = DATA / 'queue.json'
state = json.loads(STATE.read_text()) if STATE.exists() else {'paused': True, 'jobs': []}
state['paused'] = True
state.setdefault('global_settings', {})
state.setdefault('zip_threshold', 10)
state.setdefault('cleanup', dict(cleanup.DEFAULTS))
for job in state['jobs']:
    job.pop('preview_building', None)
    if job['status'] in ('rendering', 'stopping', 'encoding', 'finalizing'):
        job.update(status='stopped', error='Server stopped. Resume will validate saved frames.')

schema_lock = threading.Lock()
schema_cache = None

def encoding_schema():
    global schema_cache
    with schema_lock:
        if schema_cache is None:
            blender = blender_path()
            if not blender:
                raise RuntimeError('Install Blender before opening encoding settings.')
            target = DATA / 'encoding-schema.json'
            result = subprocess.run([blender, '--background', '--factory-startup', '--disable-autoexec',
                '--python-exit-code', '1', '--python', str(ROOT / 'encoding_schema.py'), '--', str(target)],
                capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError('Could not read encoding options from Blender.')
            schema_cache = json.loads(target.read_text())
        return schema_cache

def save():
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE)

def blender_path():
    if os.environ.get('BLENDER_PATH'):
        return os.environ['BLENDER_PATH']
    roots = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam', Path('C:/Program Files/Steam')]
    for root in list(roots):
        vdf = root / 'steamapps/libraryfolders.vdf'
        if vdf.exists():
            roots.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text()))
    for root in roots:
        path = root / 'steamapps/common/Blender/blender.exe'
        if path.exists():
            return str(path)
    return shutil.which('blender')

def auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('authenticated'):
            abort(401)
        if request.method != 'GET' and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', 'missing')):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

@app.get('/api/encoding-options')
@auth
def encoding_options():
    return jsonify(encoding_schema())

@app.post('/api/cleanup')
@auth
def clean_storage():
    with lock:
        count = cleanup.collect(DATA, state, active_id)
        save()
    return jsonify(deleted=count)

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/')
def index():
    return send_file(ROOT / 'static/index.html')

@app.post('/api/login')
def login():
    # Deliberately ignore forwarded addresses: the tunnel must not bypass throttling.
    now = time.time()
    recent = attempts.setdefault(request.remote_addr, [])
    recent[:] = [t for t in recent if now - t < 60]
    if len(recent) >= 10:
        abort(429)
    recent.append(now)
    if not hmac.compare_digest(str((request.get_json(silent=True) or {}).get('password', '')), config['password']):
        abort(401)
    session.clear()
    session.update(authenticated=True, csrf=secrets.token_hex(24))
    return jsonify(csrf=session['csrf'])

@app.get('/api/state')
@auth
def status():
    with lock:
        jobs = [{**j, 'has_frames': (DATA / j['id'] / 'frames.zip').exists(), 'can_preview': j['status'] == 'completed' or (j['status'] in ('stopped', 'failed', 'cancelled') and j['id'] != active_id and (DATA / j['id'] / 'checkpoint.json').exists())} for j in state['jobs'] if not j.get('hidden')]
        return jsonify(paused=state['paused'], jobs=jobs, zip_threshold=state['zip_threshold'],
                       global_settings=state['global_settings'], cleanup=state['cleanup'],
                       completed_count=sum(j['status'] == 'completed' for j in state['jobs']), blender=blender_path(), csrf=session['csrf'])

@app.post('/api/logout')
@auth
def logout():
    session.clear()
    return jsonify(ok=True)

@app.post('/api/uploads')
@auth
def upload_begin():
    body = request.get_json()
    name = str(body.get('name', ''))
    size = int(body.get('size', 0))
    if not name.lower().endswith('.blend') or size < 12 or size > 100 * 1024**3:
        abort(400, 'Choose a .blend file, up to 100 GB.')
    ident = uuid.uuid4().hex
    folder = DATA / ident
    folder.mkdir()
    (folder / 'upload.json').write_text(json.dumps({'name': name[:240], 'size': size}))
    (folder / 'project.part').touch()
    return jsonify(id=ident)

def folder_for(ident):
    if not re.fullmatch('[a-f0-9]{32}', ident):
        abort(404)
    folder = DATA / ident
    if not folder.is_dir():
        abort(404)
    return folder

@app.put('/api/uploads/<ident>')
@auth
def upload_chunk(ident):
    folder = folder_for(ident)
    with lock:
        part = folder / 'project.part'
        if not part.exists():
            abort(409)
        meta = json.loads((folder / 'upload.json').read_text())
        offset = int(request.args.get('offset', '-1'))
        chunk = request.get_data()
        if offset != part.stat().st_size or not chunk or offset + len(chunk) > meta['size']:
            abort(409, 'Upload offset or size mismatch.')
        with part.open('ab') as file:
            file.write(chunk)
        return jsonify(offset=part.stat().st_size)

@app.post('/api/uploads/<ident>/finish')
@auth
def upload_finish(ident):
    folder = folder_for(ident)
    with lock:
        meta = json.loads((folder / 'upload.json').read_text())
        part = folder / 'project.part'
        if not part.exists() or part.stat().st_size != meta['size']:
            abort(400, 'Incomplete upload.')
        part.rename(folder / 'project.blend')
        state['jobs'].append(dict(id=ident, name=meta['name'], size=meta['size'], status='queued', created=time.time(), frame=None, error=''))
        save()
    return jsonify(ok=True)

@app.post('/api/queue')
@auth
def queue_control():
    with lock:
        state['paused'] = bool(request.get_json()['paused'])
        save()
    return jsonify(ok=True)

@app.post('/api/queue/clear')
@auth
def clear_queue():
    with lock:
        state['paused'] = True
        for job in state['jobs']:
            remove_job(job)
        save()
    return jsonify(ok=True)

def remove_job(job):
    job['hidden'] = True
    job['updated'] = time.time()
    if job['id'] == active_id and job['status'] != 'finalizing':
        job['status'] = 'stopping'
        (DATA / job['id'] / 'stop.request').touch()
    elif job['status'] == 'queued':
        job['status'] = 'removed'

def validate_settings(body):
    if not isinstance(body, dict):
        abort(400, 'Settings must be an object.')
    limits = {'resolution_x': (4, 16384), 'resolution_y': (4, 16384), 'resolution_percentage': (1, 100),
              'samples': (1, 1048576), 'fps': (1, 240)}
    clean = {}
    for key, value in body.items():
        if value is None or value == '':
            continue
        if key == 'keep_frames':
            if not isinstance(value, bool):
                abort(400, 'Keep frames must be yes or no.')
            clean[key] = value
            continue
        if key.startswith(('video_', 'frame_')):
            spec = encoding_schema().get(key)
            if not spec:
                abort(400, 'Unknown encoding setting.')
            kind = spec['type']
            if kind == 'ENUM':
                if value not in [c[0] for c in spec['choices']] or (key == 'video_codec' and value == 'NONE'):
                    abort(400, 'Unsupported encoding option.')
            elif kind == 'BOOLEAN':
                if not isinstance(value, bool):
                    abort(400, 'Expected yes or no.')
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not max(0, spec['min']) <= value <= spec['max'] or (kind == 'INT' and int(value) != value):
                    abort(400, 'Encoding setting outside supported range.')
            clean[key] = value
            continue
        if key not in limits:
            abort(400, 'Unknown render setting.')
        try:
            number = float(value)
        except (TypeError, ValueError):
            abort(400, 'Invalid render setting.')
        low, high = limits[key]
        if not math.isfinite(number) or not low <= number <= high or (key != 'fps' and not number.is_integer()):
            abort(400, 'Render setting outside supported range.')
        clean[key] = number if key == 'fps' else int(number)
    return clean

@app.post('/api/settings')
@auth
def global_settings():
    body = request.get_json()
    if not isinstance(body, dict):
        abort(400)
    body = dict(body)
    retention = body.pop('cleanup', state['cleanup'])
    if not isinstance(retention, dict) or set(retention) != set(cleanup.DEFAULTS) or any(
        isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 3650 for v in retention.values()):
        abort(400, 'Cleanup days must be integers from 0 (disabled) to 3650.')
    threshold = body.pop('zip_threshold', state['zip_threshold'])
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or int(threshold) != threshold or not 1 <= threshold <= 1000:
        abort(400, 'ZIP threshold must be between 1 and 1000 files.')
    clean = validate_settings(body)
    with lock:
        state['global_settings'] = clean
        state['zip_threshold'] = int(threshold)
        state['cleanup'] = retention
        save()
    return jsonify(ok=True)

def effective_settings(job):
    return {**state['global_settings'], **job.get('settings', {})}

def frame_settings(options):
    return {k: v for k, v in options.items() if not k.startswith('video_') and k != 'keep_frames'}

def prepare_settings(job, folder):
    effective = effective_settings(job)
    snapshot = folder / 'render-settings.json'
    previous = json.loads(snapshot.read_text()) if snapshot.exists() else job.get('settings', {})
    if frame_settings(previous) != frame_settings(effective) and (folder / 'checkpoint.json').exists():
        recovery.discard(folder)
        (folder / 'full-render.request').unlink(missing_ok=True)
        job.update(frame=None, fallback=False, error='Effective settings changed. Starting from scratch.')
    snapshot.write_text(json.dumps(effective))
    return effective

@app.post('/api/jobs/<ident>/settings')
@auth
def job_settings(ident):
    clean = validate_settings(request.get_json())
    with lock:
        job = next((j for j in state['jobs'] if j['id'] == ident and not j.get('hidden')), None)
        if not job:
            abort(404)
        if job['status'] in ('rendering', 'stopping', 'encoding') or active_id == ident or job.get('preview_building'):
            abort(409, 'Stop the render before editing settings.')
        folder = DATA / ident
        if job.get('source_removed'):
            abort(409, 'The source file expired. Upload the project again to render it.')
        if clean != job.get('settings', {}):
            if frame_settings(clean) != frame_settings(job.get('settings', {})):
                recovery.discard(folder)
            (folder / 'full-render.request').unlink(missing_ok=True)
            (folder / 'settings.json').write_text(json.dumps(clean))
            job.update(settings=clean, updated=time.time())
            if job['status'] == 'completed':
                job['status'] = 'stopped'
            job['error'] = 'Settings saved. Image changes restart frames; video changes reuse saved frames.'
        save()
    return jsonify(ok=True)

@app.get('/api/download-all')
@auth
def download_all():
    with lock:
        jobs = [(j['id'], j['name']) for j in state['jobs'] if j['status'] == 'completed']
    if not jobs:
        abort(404, 'No completed videos yet.')
    if len(jobs) < state['zip_threshold']:
        return redirect('/static/downloads.html')
    archive = tempfile.TemporaryFile(dir=DATA)
    try:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for ident, name in jobs:
                path = recovery.output_path(DATA / ident)
                safe = re.sub(r'[^\w .()-]', '_', Path(name.replace('\\', '/')).stem)[:120]
                if path.exists():
                    bundle.write(path, f'{safe}-{ident[:8]}{path.suffix}')
        size = archive.tell()
        archive.seek(0)
        response = send_file(archive, mimetype='application/zip', as_attachment=True, download_name='render-desk-videos.zip')
        response.content_length = size
        response.call_on_close(archive.close)
        return response
    except Exception:
        archive.close()
        raise

@app.get('/api/downloads')
@auth
def downloads():
    with lock:
        return jsonify(files=[{'name': Path(j['name']).stem + recovery.output_path(DATA / j['id']).suffix, 'url': f"/api/jobs/{j['id']}/video?download=1"} for j in state['jobs'] if j['status'] == 'completed'])

@app.post('/api/queue/order')
@auth
def reorder_queue():
    with lock:
        ids = request.get_json().get('ids', [])
        queued = {j['id']: j for j in state['jobs'] if j['status'] == 'queued'}
        if len(ids) != len(queued) or set(ids) != set(queued):
            abort(409, 'Queue changed. Refresh and try again.')
        state['jobs'] = [j for j in state['jobs'] if j['status'] != 'queued'] + [queued[i] for i in ids]
        save()
    return jsonify(ok=True)

@app.post('/api/jobs/<ident>/<action>')
@auth
def control(ident, action):
    global process
    with lock:
        job = next((j for j in state['jobs'] if j['id'] == ident), None)
        if not job:
            abort(404)
        if job.get('preview_building'):
            abort(409, 'Wait for the partial preview to finish preparing.')
        if action == 'remove':
            remove_job(job)
        elif action in ('stop', 'cancel') and job['status'] in ('queued', 'rendering', 'encoding'):
            job['status'] = 'stopping' if active_id == ident else ('removed' if action == 'stop' else 'stopped')
            state['paused'] = True
            if active_id == ident:
                (DATA / ident / 'stop.request').touch()
        elif action in ('retry', 'resume', 'restart') and job['status'] in ('failed', 'cancelled', 'stopped', 'removed') and active_id != ident:
            if action == 'restart':
                recovery.discard(DATA / ident)
                job['frame'] = None
            job.update(status='queued', error='')
        else:
            abort(409)
        job['updated'] = time.time()
        save()
    return jsonify(ok=True)

@app.get('/api/jobs/<ident>/log')
@auth
def log(ident):
    path = folder_for(ident) / 'render.log'
    if not path.exists():
        return jsonify(text='Waiting to render…')
    with path.open('rb') as file:
        file.seek(max(0, path.stat().st_size - 24000))
        return jsonify(text=file.read().decode('utf-8', errors='replace'))

@app.get('/api/jobs/<ident>/video')
@auth
def video(ident):
    with lock:
        job = next((j for j in state['jobs'] if j['id'] == ident and j['status'] in ('completed', 'stopped', 'failed', 'cancelled') and j['id'] != active_id), None)
        if not job:
            abort(404)
        complete = job['status'] == 'completed'
    folder = folder_for(ident)
    path = recovery.output_path(folder) if complete else folder / 'preview.mp4'
    if not complete:
        with preview_lock:
            with lock:
                if job['status'] not in ('stopped', 'failed', 'cancelled') or active_id == ident:
                    abort(409)
                checkpoint = folder / 'checkpoint.json'
                if not checkpoint.exists():
                    abort(404, 'No finalized video checkpoints available.')
                job['preview_building'] = True
            try:
                if not path.exists() or path.stat().st_mtime_ns < checkpoint.stat().st_mtime_ns:
                    try:
                        recovery.encode(folder, blender_path(), partial=True)
                    except Exception as exc:
                        abort(409, 'Unable to assemble saved preview: ' + str(exc))
            finally:
                with lock:
                    job.pop('preview_building', None)
    return send_file(path, conditional=True,
                     as_attachment=request.args.get('download') == '1', download_name=Path(job['name']).stem + ('' if complete else '-partial') + path.suffix)

@app.get('/api/jobs/<ident>/frames')
@auth
def frame_archive(ident):
    path = folder_for(ident) / 'frames.zip'
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=True, download_name=f'frames-{ident[:8]}.zip', conditional=True)

def worker():
    global process, active_id
    next_cleanup = time.time() + 3600
    while True:
        with lock:
            if time.time() >= next_cleanup:
                try:
                    cleanup.collect(DATA, state, active_id)
                    save()
                except Exception as exc:
                    print('Cleanup deferred: ' + str(exc), flush=True)
                next_cleanup = time.time() + 3600
            job = next((j for j in state['jobs'] if j['status'] == 'queued'), None) if not state['paused'] else None
            if job:
                job.update(status='rendering', started=time.time(), error='')
                active_id = job['id']
                save()
        if not job:
            time.sleep(1)
            continue
        folder = DATA / job['id']
        try:
            with lock:
                effective_settings_snapshot = prepare_settings(job, folder)
            blender = blender_path()
            if not blender:
                raise RuntimeError('Blender not found. Set BLENDER_PATH in start.ps1.')
            if not recovery.tool('ffmpeg') or not recovery.tool('ffprobe'):
                raise RuntimeError('Install FFmpeg and FFprobe or set FFMPEG_PATH and FFPROBE_PATH.')
            (folder / 'stop.request').unlink(missing_ok=True)
            try:
                plan = recovery.validate(folder)
                if plan and plan.get('version') != 2:
                    raise RuntimeError('Switching legacy video checkpoints to image frames.')
            except Exception as exc:
                recovery.discard(folder)
                job['error'] = 'Checkpoint unusable; restarting from scratch: ' + str(exc)
            cache = DATA / 'optix-cache'
            cache.mkdir(exist_ok=True)
            env = dict(os.environ, OPTIX_CACHE_PATH=str(cache.resolve()))
            with lock:
                if job['status'] in ('stopped', 'stopping'):
                    job['status'] = 'stopped'
                    continue
                process = subprocess.Popen([blender, '--background', '--disable-autoexec', str(folder / 'project.blend'),
                    '--python-exit-code', '1', '--python', str(ROOT / 'render.py'), '--', str(folder)],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            with (folder / 'render.log').open('ab') as logfile:
                for line in process.stdout:
                    logfile.write(line)
                    logfile.flush()
                    text = line.decode('utf-8', errors='replace')
                    match = re.search(r'CLOUD_FRAME:(-?\d+):(-?\d+):(-?\d+)', text)
                    if match:
                        with lock:
                            job['frame'], job['start'], job['end'] = map(int, match.groups())
                            save()
            code = process.wait()
            with lock:
                should_encode = code == 0 and job['status'] != 'stopping'
                if should_encode:
                    job['status'] = 'encoding'
                    save()
            if should_encode:
                output = recovery.encode(folder, blender)
                with lock:
                    finalize = job['status'] != 'stopping'
                    if finalize:
                        job['status'] = 'finalizing'
                        save()
                if finalize:
                    recovery.finish_frames(folder, effective_settings_snapshot.get('keep_frames', False))
            with lock:
                if job['status'] == 'stopping':
                    job['status'] = 'stopped'
                else:
                    if code != 0:
                        raise RuntimeError(f'Blender exited with code {code}. Check the render log.')
                    job.update(status='completed', finished=time.time(), updated=time.time())
        except Exception as exc:
            with lock:
                if job['status'] == 'stopping':
                    job['status'] = 'stopped'
                elif job['status'] != 'stopped':
                    job.update(status='failed', error=str(exc))
        finally:
            with lock:
                job['updated'] = time.time()
                process = None
                active_id = None
                if not any(j['status'] == 'queued' for j in state['jobs']):
                    state['paused'] = True
                save()

if __name__ == '__main__':
    from waitress import serve
    threading.Thread(target=worker, daemon=True).start()
    print(f'Render desk: http://127.0.0.1:{os.environ.get("PORT", 7860)}', flush=True)
    print('Login password: ' + config['password'], flush=True)
    serve(app, host='127.0.0.1', port=int(os.environ.get('PORT', 7860)), threads=8, max_request_body_size=9 * 1024**2)
