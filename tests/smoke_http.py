"""Submit a tiny real project through the live upload API and verify its video."""
import http.cookiejar
import json
import time
import urllib.request
import sys
sys.stdout.reconfigure(errors='replace')
from pathlib import Path
root = Path(__file__).resolve().parents[1]
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
base = 'http://127.0.0.1:7860'
csrf = ''
def call(path, method='GET', data=None, raw=False):
    headers = {'X-CSRF-Token': csrf}
    if data is not None:
        headers['Content-Type'] = 'application/octet-stream' if raw else 'application/json'
        data = data if raw else json.dumps(data).encode()
    with client.open(urllib.request.Request(base+path, data=data, method=method, headers=headers)) as response:
        return json.load(response)
csrf = call('/api/login', 'POST', {'password': json.loads((root/'data/config.json').read_text())['password']})['csrf']
project = (root/'data/smoke.blend').read_bytes()
ident = call('/api/uploads', 'POST', {'name':'Smoke test.blend','size':len(project)})['id']
call('/api/uploads/'+ident+'?offset=0','PUT',project,True)
call('/api/uploads/'+ident+'/finish','POST',{})
call('/api/queue','POST',{'paused':False})
for _ in range(120):
    job = next(j for j in call('/api/state')['jobs'] if j['id'] == ident)
    if job['status'] in ('failed','completed'):
        break
    time.sleep(1)
print(json.dumps(job))
if job['status'] != 'completed':
    print(call('/api/jobs/'+ident+'/log')['text'][-6000:])
    raise SystemExit(1)
with client.open(base+'/api/jobs/'+ident+'/video') as response:
    video = response.read()
    assert b'ftyp' in video[:32]
    print('MP4 download verified:', len(video), 'bytes')
