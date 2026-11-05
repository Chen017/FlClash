import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.personal/work'
PLAN = json.loads((WORK / 'plan.json').read_text())
PACKAGE = PLAN['package_id']
APK = WORK / 'source/build/app/outputs/flutter-apk/app-x86_64-release.apk'


def adb(*args):
    return subprocess.check_output(['adb', *args], text=True, stderr=subprocess.STDOUT)


def launch():
    adb('logcat', '-c')
    result = adb('shell', 'am', 'start', '-W', '-n', f'{PACKAGE}/com.follow.clash.MainActivity')
    if 'Error' in result:
        raise RuntimeError(result)
    time.sleep(20)
    adb('shell', 'pidof', PACKAGE)
    log = adb('logcat', '-d')
    (WORK / 'emulator-log.txt').write_text(log)
    if 'FATAL EXCEPTION' in log or 'Fatal signal' in log:
        raise RuntimeError('Native crash during emulator startup')
    adb('shell', 'uiautomator', 'dump', '/sdcard/ui.xml')
    ui = adb('shell', 'cat', '/sdcard/ui.xml')
    (WORK / 'emulator-ui.txt').write_text(ui)
    if PACKAGE not in ui:
        raise RuntimeError('Personal app did not present its window')


adb('install', '-r', str(APK))
launch()
before = adb('shell', 'dumpsys', 'package', PACKAGE)
adb('shell', 'am', 'force-stop', PACKAGE)
adb('install', '-r', str(APK))
after = adb('shell', 'dumpsys', 'package', PACKAGE)
for field in ('userId', 'firstInstallTime'):
    pattern = rf'{field}=([^\r\n ]+)'
    if re.search(pattern, before)[1] != re.search(pattern, after)[1]:
        raise RuntimeError(f'Overlay install replaced {field}')
launch()
print('Signed x86_64 APK starts and overlays without replacing Android app identity.')
