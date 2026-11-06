import hashlib
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.personal/work'
FIXTURE = WORK / 'e2e'
XRAY_SHA256 = '23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae'

archive = WORK / 'xray.zip'
urllib.request.urlretrieve('https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip', archive)
if hashlib.sha256(archive.read_bytes()).hexdigest() != XRAY_SHA256:
    raise RuntimeError('Pinned Xray checksum mismatch')
with zipfile.ZipFile(archive) as bundle:
    bundle.extract('xray', WORK)
(WORK / 'xray').chmod(0o755)
subprocess.run(['go', 'build', '-tags', 'with_gvisor', '-o', str(WORK / 'mihomo-probe'), '.'],
               cwd=WORK / 'source/core/Clash.Meta', check=True)
subprocess.run(['npm', 'ci', '--ignore-scripts'], cwd=FIXTURE, check=True)
script = (FIXTURE / 'tests/nat-split-e2e.mjs').read_text()
anchor = 'await ready(controller,clientWorker);'
if script.count(anchor) != 1:
    raise RuntimeError('Pinned test fixture changed')
script = script.replace(anchor, anchor + '''
  assert.equal((await fetch(`http://127.0.0.1:${controller}/configs`, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({'mixed-port':mixed,'lan-allowed-ips':['127.0.0.0/8','::1/128']})
  })).status,204);
''')
(FIXTURE / '.local').mkdir(exist_ok=True)
(FIXTURE / '.local/mobile-e2e.mjs').write_text(script)
import os
env = dict(os.environ, MIHOMO_NAT_BIN=str(WORK / 'mihomo-probe'), XRAY_NATIVE_BIN=str(WORK / 'xray'))
subprocess.run(['node', '.local/mobile-e2e.mjs'], cwd=FIXTURE, env=env, check=True)
