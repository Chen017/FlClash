#!/usr/bin/env python3
"""Rebuild stable FLClash with maintained Android-compatible transport patches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.personal/work'
SOURCE = STATE / 'source'
DIST = ROOT / '.personal/dist'
REPO = 'Chen017/FlClash'
UPSTREAM = 'chen08209/FlClash'
UPSTREAM_GIT = f'https://github.com/{UPSTREAM}.git'
APP_PATCH_BASE = 'be84736605527034689c95bf27828ff27d912c5e'
CORE_PATCH_BASE = '024245dc72bc92f48237f865119afe0cd53ac9e6'


def run(*args, cwd=ROOT, capture=False, env=None):
    return subprocess.run(args, cwd=cwd, check=True, env=env, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def api(path, missing=False):
    result = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if result.returncode:
        if missing and '404' in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def output(**values):
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a', encoding='utf-8') as stream:
            for key, value in values.items():
                stream.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inputs_digest(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def checked_patch(path, cwd, merge_base=None):
    for reverse in (False, True):
        command = ['git', 'apply', '--check'] + (['--reverse'] if reverse else []) + [str(path)]
        if subprocess.run(command, cwd=cwd, capture_output=True).returncode == 0:
            if not reverse:
                run('git', 'apply', str(path), cwd=cwd)
            return
    if merge_base:
        repository, revision = merge_base
        if subprocess.run(['git', 'cat-file', '-e', revision + '^{commit}'],
                          cwd=cwd, capture_output=True).returncode:
            run('git', 'fetch', '--depth', '1', '--no-tags', repository, revision, cwd=cwd)
    merged = subprocess.run(['git', 'apply', '--3way', str(path)], cwd=cwd)
    if merged.returncode:
        raise RuntimeError(f'{path.name} conflicts with upstream; last working release is preserved')


def next_build(previous, refs):
    numbers = [previous['build_number'] if previous else 0]
    for ref in refs:
        if match := re.fullmatch(r'refs/tags/v\d+\.\d+\.\d+\+(\d+)', ref['ref']):
            numbers.append(int(match[1]))
    return max(numbers) + 1


def prepare():
    STATE.mkdir(parents=True, exist_ok=True)
    release = api(f'repos/{UPSTREAM}/releases/latest')
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise RuntimeError('Expected an official stable release')
    revision = api(f'repos/{UPSTREAM}/commits/tags/{tag}')['sha']
    scripts = [path for path in ROOT.glob('.personal/*.py') if not path.name.startswith('test_')]
    files = [*scripts, *ROOT.glob('.personal/*.patch'),
             *ROOT.glob('.github/workflows/personal*.yml')]
    digest = inputs_digest(files)
    previous = api(f'repos/{REPO}/releases/latest', missing=True)
    last = None
    if previous:
        asset = next((a for a in previous['assets'] if a['name'] == 'manifest.json'), None)
        if asset is None:
            raise RuntimeError('Latest personal release is missing manifest.json')
        with urllib.request.urlopen(asset['browser_download_url'], timeout=30) as response:
            last = json.load(response)
    needed = not last or (last['upstream_commit'], last['inputs_sha256']) != (revision, digest)
    output(needed=needed)
    if not needed:
        print('Stable app and maintained patches unchanged; no rebuild required.')
        return
    number = next_build(last, api(f'repos/{REPO}/git/matching-refs/tags/v'))
    if SOURCE.exists():
        raise RuntimeError('Use a fresh checkout; existing prepared source is kept for inspection')
    run('git', 'fetch', '--depth', '1', '--no-tags', UPSTREAM_GIT, f'refs/tags/{tag}')
    if run('git', 'rev-parse', 'FETCH_HEAD^{commit}', capture=True).strip() != revision:
        raise RuntimeError(f'Upstream tag {tag} changed during preparation; retry the workflow')
    run('git', 'worktree', 'add', '--detach', str(SOURCE), revision)
    run('git', '-c', 'url.https://github.com/.insteadOf=git@github.com:',
        'submodule', 'update', '--init', '--depth', '1', cwd=SOURCE)
    core = SOURCE / 'core/Clash.Meta'
    core_revision = run('git', 'rev-parse', 'HEAD', cwd=core, capture=True).strip()
    workflow = (SOURCE / '.github/workflows/build.yaml').read_text()
    pins = {key: re.search(rf"{name}:\s*'?([\w.]+)'?", workflow)[1]
            for key, name in [('flutter', 'FLUTTER_VERSION'), ('go', 'GO_VERSION'), ('ndk', 'NDK_VERSION')]}
    checked_patch(ROOT / '.personal/app.patch', SOURCE, (UPSTREAM_GIT, APP_PATCH_BASE))
    checked_patch(ROOT / '.personal/core.patch', core,
                  ('https://github.com/chen08209/Clash.Meta.git', CORE_PATCH_BASE))
    shutil.copytree(ROOT / '.personal', SOURCE / '.personal',
                    ignore=shutil.ignore_patterns('work', 'dist', '__pycache__'))
    readme = SOURCE / 'README.md'
    readme.write_text('> FLClash Personal: unofficial signed Android builds. '
                      '[Downloads](https://github.com/Chen017/FlClash/releases/latest) · '
                      '[Migration and maintenance](.personal/README.md). Upstream documentation follows.\n\n'
                      + readme.read_text())
    version = f'{tag[1:]}+{number}'
    pubspec = SOURCE / 'pubspec.yaml'
    pubspec.write_text(re.sub(r'^version:.*$', f'version: {version}', pubspec.read_text(), flags=re.M))
    config = SOURCE / 'build_config.yaml'
    config.write_text(re.sub(r'^(core_version:\s*)(\S+)$', rf'\1\2-personal.{digest[:8]}',
                             config.read_text(), flags=re.M))
    plan = dict(upstream_repository=UPSTREAM, upstream_tag=tag, upstream_commit=revision,
                core_repository='chen08209/Clash.Meta', core_revision=core_revision,
                inputs_sha256=digest, build_number=number, version=version, tag=f'v{version}',
                maintenance_commit=run('git', 'rev-parse', 'HEAD', capture=True).strip(),
                package_id='io.github.chen017.flclash', android_abi='arm64-v8a', capabilities=[
                    'xhttp-download-dialer', 'provider-scoped-dialer', 'vless-0rtt-ticket-recovery',
                    'xhttp-h2-window', 'unified-delay-warm-fallback', 'android-vless-first-write-fragment'],
                flutter_version=pins['flutter'], go_version=pins['go'], ndk_version=pins['ndk'])
    write_json(STATE / 'plan.json', plan)
    output(tag=plan['tag'], flutter=plan['flutter_version'], go=plan['go_version'], ndk=plan['ndk_version'])
    print(f'Prepared {plan["tag"]} from {tag} ({revision[:12]}); core {core_revision[:12]}.')


def package():
    plan = json.loads((STATE / 'plan.json').read_text())
    DIST.mkdir(exist_ok=True)
    if any(DIST.iterdir()):
        raise RuntimeError('Refusing to mix release outputs')
    certificate = os.environ.get('ANDROID_CERT_SHA256', '').strip().lower().replace(':', '')
    if not re.fullmatch(r'[0-9a-f]{64}', certificate):
        raise RuntimeError('ANDROID_CERT_SHA256 must contain the full signing certificate SHA-256')
    path = SOURCE / 'build/app/outputs/flutter-apk/app-arm64-v8a-release.apk'
    verified = run('apksigner', 'verify', '--verbose', '--print-certs', str(path), capture=True)
    signers = re.findall(
        r'^(?:Signer #\d+|V[1-4](?:\.\d+)? Signer(?: #\d+)?):? '
        r'certificate SHA-256 digest: ([0-9a-fA-F]{64})$', verified, re.M,
    )
    signer_counts = re.findall(r'^Number of signers: (\d+)$', verified, re.M)
    if signer_counts != ['1'] or [signer.lower() for signer in signers] != [certificate]:
        raise RuntimeError('APK must have the permanent personal key as its sole signer')
    info = run('aapt', 'dump', 'badging', str(path), capture=True)
    identity = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", info, re.M)
    expected = (plan['package_id'], str(plan['build_number']), plan['upstream_tag'][1:])
    if not identity or identity.groups() != expected:
        raise RuntimeError('Wrong APK package identity/version')
    with zipfile.ZipFile(path) as apk:
        abis = {name.split('/')[1] for name in apk.namelist()
                if name.startswith('lib/') and not name.endswith('/')}
        if abis != {'arm64-v8a'} or 'lib/arm64-v8a/libclash.so' not in apk.namelist():
            raise RuntimeError(f'Expected only arm64 with libclash.so; found ABIs: {sorted(abis)}')
    name = f'FlClash-{plan["version"]}-android-arm64-v8a.apk'
    shutil.copy2(path, DIST / name)
    artifact = dict(url=f'https://github.com/{REPO}/releases/download/{plan["tag"]}/{name}',
                    sha256=sha(DIST / name), size=(DIST / name).stat().st_size)
    provenance = dict(plan, apk=artifact, signing_certificate_sha256=certificate,
                      core_patch_sha256=sha(ROOT / '.personal/core.patch'))
    write_json(DIST / 'manifest.json', provenance)
    with tarfile.open(DIST / 'complete-source.tar.gz', 'w:gz') as archive:
        paths = run('git', 'ls-files', '-z', '--recurse-submodules', cwd=SOURCE, capture=True).split('\0')
        paths += run('git', 'ls-files', '-z', '--others', '--exclude-standard', cwd=SOURCE, capture=True).split('\0')
        paths += ['core/Clash.Meta/' + p for p in run('git', 'ls-files', '-z', '--others', '--exclude-standard', cwd=SOURCE / 'core/Clash.Meta', capture=True).split('\0') if p]
        for path in sorted(set(paths)):
            item = SOURCE / path
            if item.is_file() and '.git' not in item.parts:
                archive.add(item, arcname='FlClash-personal/' + item.relative_to(SOURCE).as_posix())
    (DIST / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(DIST.iterdir())), encoding='utf-8')


def publish():
    plan = json.loads((STATE / 'plan.json').read_text())
    run('git', 'add', '-A', cwd=SOURCE)
    run('git', '-c', 'user.name=Chen017', '-c', 'user.email=Chen017@users.noreply.github.com',
        'commit', '-m', f'build(android): signed personal {plan["version"]}', cwd=SOURCE)
    run('git', 'tag', plan['tag'], cwd=SOURCE)
    run('git', '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
        'push', 'origin', f'refs/tags/{plan["tag"]}', cwd=SOURCE)
    notes = STATE / 'notes.md'
    notes.write_text(f'''FLClash Personal · Android · unofficial maintained build

Android arm64 only. Based on {UPSTREAM} {plan['upstream_tag']}. Install alongside the official app, export/import its local backup once, then use Check for updates here.
Uses a permanent signing key; subsequent releases update this personal app in place.

<!-- flclash:changelog:begin -->
- Independent XHTTP upload/download routes, including NAT IPv4 upload and direct IPv6 download.
- Scoped Proxy Provider chaining, configurable H2 windows and 0-RTT ticket recovery.
- Automatic stable upstream checks every six hours; SHA256 verified application updates, including core-only builds.
<!-- flclash:changelog:end -->

Upstream source: `{plan['upstream_commit']}`; core: `{plan['core_revision']}`.
Exact complete app and patched submodule source, licenses and manifest are attached.
Physical-phone VPN behavior still needs confirmation on your handset.
''', encoding='utf-8')
    run('gh', 'release', 'create', plan['tag'], '--repo', REPO, '--verify-tag', '--draft', '--title',
        f'FLClash Personal {plan["version"]}', '--notes-file', str(notes), *map(str, DIST.iterdir()))
    data = json.loads(run('gh', 'release', 'view', plan['tag'], '--repo', REPO,
                          '--json', 'assets', capture=True))
    if {a['name']: a['size'] for a in data['assets']} != {p.name: p.stat().st_size for p in DIST.iterdir()}:
        raise RuntimeError('Uploaded assets incomplete; release stays draft')
    run('gh', 'release', 'edit', plan['tag'], '--repo', REPO, '--draft=false', '--prerelease=false', '--latest')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'package', 'publish'])
    globals()[parser.parse_args().command]()
