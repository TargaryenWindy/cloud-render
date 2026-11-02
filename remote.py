"""Linux tunnel launcher; starts the server if needed, leaving URL last."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import dependencies

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('RENDER_DATA', ROOT/'data'))
DATA.mkdir(parents=True,exist_ok=True)
port=int(os.environ.get('PORT',7860))
url=f'http://127.0.0.1:{port}'
def ready():
    try:
        with urllib.request.urlopen(url,timeout=2) as response:return response.status==200
    except Exception:return False

def main():
    if not ready():
        with (DATA/'remote-server.log').open('ab') as out:
            server=subprocess.Popen([sys.executable,str(ROOT/'app.py')],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
        (DATA/'server.pid').write_text(str(server.pid))
        for _ in range(120):
            if ready():break
            if server.poll() is not None:raise RuntimeError('App startup failed. See data/remote-server.log.')
            time.sleep(.5)
        else:raise RuntimeError('App did not become ready. See data/remote-server.log.')
    tunnel=dependencies.find('cloudflared')
    if not tunnel:raise RuntimeError('Run bash remote.sh to install Cloudflared first.')
    logpath=DATA/'tunnel.log'
    with logpath.open('w') as log:
        process=subprocess.Popen([tunnel,'tunnel','--url',url,'--no-autoupdate'],stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+90
            while time.monotonic()<deadline and process.poll() is None:
                content=logpath.read_text(errors='replace')
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',content)
                if match and 'Registered tunnel connection' in content:
                    print('Keep this process running for remote access. Ctrl+C stops the tunnel.',flush=True)
                    print('Logs: '+str(logpath),flush=True)
                    print('Login password: '+json.loads((DATA/'config.json').read_text())['password'],flush=True)
                    print(match[0],flush=True)
                    process.wait()
                    return
                time.sleep(.3)
            raise RuntimeError('Tunnel did not connect. See '+str(logpath))
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
    except Exception as exc:raise SystemExit(str(exc))
