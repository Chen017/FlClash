import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

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
    maps = ''.join(adb('shell', 'cat', f'/proc/{pid}/maps')
                   for pid in adb('shell', 'pidof', PACKAGE).split())
    if 'libclash.so' not in maps:
        raise RuntimeError('Signed APK did not load the bundled Android Go core')


def seed_preferences():
    prefs = ET.Element('map')
    ET.SubElement(prefs, 'string', name='flutter.config').text = json.dumps({
        'appSettingProps': {'acceptedDisclaimerVersion': 1, 'locale': 'en'},
        'themeProps': {},
    })
    fixture = WORK / 'emulator-preferences.xml'
    ET.ElementTree(prefs).write(fixture, encoding='utf-8', xml_declaration=True)
    directory = f'/data/user/0/{PACKAGE}/shared_prefs'
    uid = adb('shell', 'stat', '-c', '%u', f'/data/user/0/{PACKAGE}').strip()
    adb('shell', 'mkdir', '-p', directory)
    adb('push', str(fixture), directory + '/FlutterSharedPreferences.xml')
    adb('shell', 'chown', '-R', f'{uid}:{uid}', directory)
    adb('shell', 'restorecon', '-RF', directory)


older = APK
if (WORK / 'previous.json').exists():
    previous = json.loads((WORK / 'previous.json').read_text())['assets']['x86_64']
    older = WORK / 'previous.apk'
    urllib.request.urlretrieve(previous['url'], older)
    if hashlib.sha256(older.read_bytes()).hexdigest() != previous['sha256']:
        raise RuntimeError('Previous-release APK checksum mismatch')
adb('root')
adb('wait-for-device')
adb('install', '-r', str(older))
seed_preferences()
launch()
before = adb('shell', 'dumpsys', 'package', PACKAGE)
sentinel = f'/data/user/0/{PACKAGE}/files/personal-upgrade-smoke'
adb('shell', f'echo personal-data-survives > {sentinel}')
adb('shell', 'am', 'force-stop', PACKAGE)
adb('install', '-r', str(APK))
after = adb('shell', 'dumpsys', 'package', PACKAGE)
for field in ('userId', 'firstInstallTime'):
    pattern = rf'{field}=([^\r\n ]+)'
    if re.search(pattern, before)[1] != re.search(pattern, after)[1]:
        raise RuntimeError(f'Overlay install replaced {field}')
if adb('shell', 'cat', sentinel).strip() != 'personal-data-survives':
    raise RuntimeError('Overlay install lost private application data')
launch()
prefs = ET.fromstring(adb('shell', 'cat', f'/data/user/0/{PACKAGE}/shared_prefs/FlutterSharedPreferences.xml'))
config = json.loads(next(node.text for node in prefs if node.get('name') == 'flutter.config'))
if config['appSettingProps']['acceptedDisclaimerVersion'] != 1 or config['appSettingProps']['locale'] != 'en':
    raise RuntimeError('Overlay install lost persisted app settings')
print('Signed APK loads its bundled Go core; overlay preserves identity, private data and settings.')
