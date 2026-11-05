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

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.personal/work'
SOURCE = STATE / 'source'
DIST = ROOT / '.personal/dist'
REPO = 'Chen017/FlClash'
UPSTREAM = 'chen08209/FlClash'


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


def checked_patch(path, cwd):
    for reverse in (False, True):
        command = ['git', 'apply', '--check'] + (['--reverse'] if reverse else []) + [str(path)]
        if subprocess.run(command, cwd=cwd, capture_output=True).returncode == 0:
            if not reverse:
                run('git', 'apply', str(path), cwd=cwd)
            return
    raise RuntimeError(f'{path.name} conflicts with upstream; last working release is preserved')


def prepare():
    STATE.mkdir(parents=True, exist_ok=True)
    release = api(f'repos/{UPSTREAM}/releases/latest')
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise RuntimeError('Expected an official stable release')
    run('git', 'fetch', '--no-tags', f'https://github.com/{UPSTREAM}.git', f'refs/tags/{tag}')
    revision = run('git', 'rev-parse', 'FETCH_HEAD^{commit}', capture=True).strip()
    files = [*ROOT.glob('.personal/*.py'), *ROOT.glob('.personal/*.patch'),
             *ROOT.glob('.github/workflows/personal*.yml')]
    digest = inputs_digest(files)
    previous = api(f'repos/{REPO}/releases/latest', missing=True)
    last = None
    if previous:
        asset = next(a for a in previous['assets'] if a['name'] == 'manifest.json')
        with urllib.request.urlopen(asset['browser_download_url']) as response:
            last = json.load(response)
        write_json(STATE / 'previous.json', last)
    needed = not last or (last['upstream_commit'], last['inputs_sha256']) != (revision, digest)
    output(needed=needed)
    if not needed:
        print('Stable app and maintained patches unchanged; no rebuild required.')
        return
    number = last['build_number'] + 1 if last else 1
    if SOURCE.exists():
        raise RuntimeError('Use a fresh checkout; existing prepared source is kept for inspection')
    run('git', 'worktree', 'add', '--detach', str(SOURCE), revision)
    run('git', '-c', 'url.https://github.com/.insteadOf=git@github.com:',
        'submodule', 'update', '--init', '--depth', '1', cwd=SOURCE)
    core = SOURCE / 'core/Clash.Meta'
    core_revision = run('git', 'rev-parse', 'HEAD', cwd=core, capture=True).strip()
    workflow = (SOURCE / '.github/workflows/build.yaml').read_text()
    pins = {key: re.search(rf"{name}:\s*'?([\w.]+)'?", workflow)[1]
            for key, name in [('flutter', 'FLUTTER_VERSION'), ('go', 'GO_VERSION'), ('ndk', 'NDK_VERSION')]}
    checked_patch(ROOT / '.personal/app.patch', SOURCE)
    checked_patch(ROOT / '.personal/core.patch', core)
    for workflow in (SOURCE / '.github/workflows').iterdir():
        workflow.unlink()
    for workflow in ROOT.glob('.github/workflows/personal*.yml'):
        shutil.copy2(workflow, SOURCE / '.github/workflows' / workflow.name)
    shutil.copytree(ROOT / '.personal', SOURCE / '.personal',
                    ignore=shutil.ignore_patterns('work', 'dist', '__pycache__'))
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
                package_id='io.github.chen017.flclash', capabilities=[
                    'xhttp-download-dialer', 'provider-scoped-dialer', 'vless-0rtt-ticket-recovery',
                    'xhttp-h2-window', 'unified-delay-warm-fallback'],
                flutter_version=pins['flutter'], go_version=pins['go'], ndk_version=pins['ndk'])
    write_json(STATE / 'plan.json', plan)
    output(tag=plan['tag'], flutter=plan['flutter_version'], go=plan['go_version'], ndk=plan['ndk_version'])
    print(f'Prepared {plan["tag"]} from {tag} ({revision[:12]}); core {core_revision[:12]}.')


def package():
    plan = json.loads((STATE / 'plan.json').read_text())
    DIST.mkdir(exist_ok=True)
    if any(DIST.iterdir()):
        raise RuntimeError('Refusing to mix release outputs')
    assets = {}
    certificate = os.environ['ANDROID_CERT_SHA256'].lower().replace(':', '')
    for abi in ('arm64-v8a', 'armeabi-v7a', 'x86_64'):
        path = SOURCE / f'build/app/outputs/flutter-apk/app-{abi}-release.apk'
        verified = run('apksigner', 'verify', '--verbose', '--print-certs', str(path), capture=True)
        if f'certificate SHA-256 digest: {certificate}' not in verified:
            raise RuntimeError('APK is not signed with the permanent personal key')
        info = run('aapt', 'dump', 'badging', str(path), capture=True)
        if f"name='{plan['package_id']}'" not in info or f"versionCode='{plan['build_number']}'" not in info:
            raise RuntimeError(f'{abi}: wrong package identity/version')
        name = f'FlClash-{plan["version"]}-android-{abi}.apk'
        shutil.copy2(path, DIST / name)
        assets[abi] = dict(url=f'https://github.com/{REPO}/releases/download/{plan["tag"]}/{name}',
                           sha256=sha(DIST / name), size=(DIST / name).stat().st_size)
    provenance = dict(plan, assets=assets, signing_certificate_sha256=certificate,
                      core_patch_sha256=sha(ROOT / '.personal/core.patch'))
    write_json(DIST / 'manifest.json', provenance)
    with tarfile.open(DIST / 'complete-source.tar.gz', 'w:gz') as archive:
        paths = run('git', 'ls-files', '--recurse-submodules', cwd=SOURCE, capture=True).splitlines()
        paths += run('git', 'ls-files', '--others', '--exclude-standard', cwd=SOURCE, capture=True).splitlines()
        paths += ['core/Clash.Meta/' + p for p in run('git', 'ls-files', '--others', '--exclude-standard', cwd=SOURCE / 'core/Clash.Meta', capture=True).splitlines()]
        for path in sorted(set(paths)):
            item = SOURCE / path
            if not item.exists():
                item = SOURCE / 'core/Clash.Meta' / path
            if item.is_file() and '.git' not in item.parts:
                archive.add(item, arcname='FlClash-personal/' + item.relative_to(SOURCE).as_posix())
    (DIST / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(DIST.iterdir())), encoding='utf-8')


def publish():
    plan = json.loads((STATE / 'plan.json').read_text())
    run('git', 'add', '-A', cwd=SOURCE)
    run('git', '-c', 'user.name=Chen017', '-c', 'user.email=Chen017@users.noreply.github.com',
        'commit', '-m', f'build(android): signed personal {plan["version"]}', cwd=SOURCE)
    run('git', 'tag', plan['tag'], cwd=SOURCE)
    run('git', 'push', 'origin', f'refs/tags/{plan["tag"]}', cwd=SOURCE)
    notes = STATE / 'notes.md'
    notes.write_text(f'''FLClash Personal · Android · unofficial maintained build

Based on {UPSTREAM} {plan['upstream_tag']}. Install alongside the official app, export/import its local backup once, then use Check for updates here.
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
    run('gh', 'release', 'create', plan['tag'], '--repo', REPO, '--draft', '--title',
        f'FLClash Personal {plan["version"]}', '--notes-file', str(notes), *map(str, DIST.iterdir()))
    data = api(f'repos/{REPO}/releases/tags/{plan["tag"]}')
    if {a['name']: a['size'] for a in data['assets']} != {p.name: p.stat().st_size for p in DIST.iterdir()}:
        raise RuntimeError('Uploaded assets incomplete; release stays draft')
    run('gh', 'release', 'edit', plan['tag'], '--repo', REPO, '--draft=false', '--prerelease=false', '--latest')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'package', 'publish'])
    globals()[parser.parse_args().command]()
