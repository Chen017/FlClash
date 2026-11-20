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
        output(patch_conflict=True)
        raise RuntimeError(f'{path.name} conflicts with upstream; last working release is preserved')


CHANGELOG_JSON_BEGIN = '<!-- flclash:changelog:json'
CHANGELOG_JSON_END = '-->'
CHANGELOG_BEGIN = '<!-- flclash:changelog:begin -->'
CHANGELOG_END = '<!-- flclash:changelog:end -->'
PERSONAL_ITEMS = [
    'Independent XHTTP upload/download routes, including NAT IPv4 upload and direct IPv6 download.',
    'Scoped Proxy Provider chaining, configurable H2 windows, 0-RTT ticket recovery and Android first-write fragment.',
    'Permanent signing key for in-place Android arm64 updates with SHA256 verification.',
]


def next_build_code(previous, refs):
    numbers = [previous['build_number'] if previous and previous.get('build_number') else 0]
    for ref in refs:
        if match := re.fullmatch(r'refs/tags/v\d+\.\d+\.\d+\+(\d+)', ref['ref']):
            numbers.append(int(match[1]))
    return max(numbers) + 1


def next_version_name(upstream_tag, refs):
    base = f'{upstream_tag.removeprefix("v")}-personal'
    numbers = []
    for ref in refs:
        name = ref['ref']
        if name == f'refs/tags/v{base}':
            numbers.append(1)
        elif match := re.fullmatch(rf'refs/tags/v{re.escape(base)}\.(\d+)', name):
            numbers.append(int(match[1]))
    if not numbers:
        return base
    return f'{base}.{max(numbers) + 1}'


def format_release_notes(plan):
    upstream_notes = (plan.get('upstream_notes') or '').strip()
    json_marker = ''
    visible_upstream = upstream_notes

    begin = upstream_notes.find(CHANGELOG_JSON_BEGIN)
    if begin >= 0:
        start = begin + len(CHANGELOG_JSON_BEGIN)
        end = upstream_notes.find(CHANGELOG_JSON_END, start)
        if end >= 0:
            raw_json = upstream_notes[start:end].strip()
            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get('versions'), list) and payload['versions']:
                first = payload['versions'][0]
                if isinstance(first, dict):
                    first['version'] = plan['version']
                    first['tag'] = plan['tag']
                    groups = first.setdefault('groups', [])
                    if isinstance(groups, list):
                        groups.append({
                            'type': 'feat',
                            'entries': [
                                {'id': f'personal-{i}', 'scope': 'personal', 'text': f'[Personal] {item}'}
                                for i, item in enumerate(PERSONAL_ITEMS, 1)
                            ],
                        })
                    json_marker = (
                        f'{CHANGELOG_JSON_BEGIN}\n'
                        f'{json.dumps(payload, ensure_ascii=False, indent=2)}\n'
                        f'{CHANGELOG_JSON_END}'
                    )
                    visible_upstream = (
                        upstream_notes[:begin].rstrip() + '\n\n' +
                        upstream_notes[end + len(CHANGELOG_JSON_END):].lstrip()
                    ).strip()

    personal_bullets = '\n'.join(f'- {item}' for item in PERSONAL_ITEMS)
    custom_body = (
        '## Personal Customizations\n\n'
        f'{personal_bullets}\n\n'
        f'Android arm64 only. Based on `{UPSTREAM}` `{plan["upstream_tag"]}`. '
        'Install alongside the official app, export/import its local backup once, then use Check for updates here.\n'
        'Uses a permanent signing key; subsequent releases update this personal app in place.\n\n'
        f'Upstream source: `{plan["upstream_commit"]}`; core: `{plan["core_revision"]}`.\n'
        'Exact complete app and patched submodule source, licenses and manifest are attached.'
    )

    if json_marker:
        body = f'{visible_upstream}\n\n---\n\n{custom_body}' if visible_upstream else custom_body
        return f'{body}\n\n{json_marker}\n'

    cleaned_upstream = visible_upstream.replace(CHANGELOG_BEGIN, '').replace(CHANGELOG_END, '').strip()
    if cleaned_upstream:
        return f'{CHANGELOG_BEGIN}\n{cleaned_upstream}\n\n---\n\n{custom_body}\n{CHANGELOG_END}\n'
    return f'{CHANGELOG_BEGIN}\n{custom_body}\n{CHANGELOG_END}\n'


def prepare():
    STATE.mkdir(parents=True, exist_ok=True)
    release = api(f'repos/{UPSTREAM}/releases/latest')
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise RuntimeError('Expected an official stable release')
    revision = api(f'repos/{UPSTREAM}/commits/tags/{tag}')['sha']
    scripts = [path for path in ROOT.glob('.personal/*.py') if not path.name.startswith('test_')]
    patches = list(ROOT.glob('.personal/*.patch'))
    files = [*scripts, *patches, *ROOT.glob('.github/workflows/personal*.yml')]
    digest = inputs_digest(files)
    patch_digest = inputs_digest(patches)
    previous = api(f'repos/{REPO}/releases/latest', missing=True)
    last = None
    if previous:
        asset = next((a for a in previous['assets'] if a['name'] == 'manifest.json'), None)
        if asset is None:
            raise RuntimeError('Latest personal release is missing manifest.json')
        with urllib.request.urlopen(asset['browser_download_url'], timeout=30) as response:
            last = json.load(response)
    needed = not isinstance(last, dict) or (last.get('upstream_tag'), last.get('upstream_commit')) != (tag, revision)
    output(needed=needed)
    if not needed:
        print('Stable upstream app unchanged; core-only and maintenance-only updates are deferred.')
        return
    refs = api(f'repos/{REPO}/git/matching-refs/tags/v', missing=True) or []
    number = next_build_code(last, refs)
    version_name = next_version_name(tag, refs)
    pubspec_version = f'{version_name}+{number}'
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
    pubspec = SOURCE / 'pubspec.yaml'
    pubspec.write_text(re.sub(r'^version:.*$', f'version: {pubspec_version}', pubspec.read_text(), flags=re.M))
    config = SOURCE / 'build_config.yaml'
    config.write_text(re.sub(r'^(core_version:\s*)(\S+)$', rf'\1\2-personal.{patch_digest[:8]}',
                             config.read_text(), flags=re.M))
    plan = dict(upstream_repository=UPSTREAM, upstream_tag=tag, upstream_commit=revision,
                upstream_notes=(release.get('body') or '').strip(),
                core_repository='chen08209/Clash.Meta', core_revision=core_revision,
                inputs_sha256=digest, patch_sha256=patch_digest,
                build_number=number, version_name=version_name, version=version_name,
                pubspec_version=pubspec_version, tag=f'v{version_name}',
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
    expected = (plan['package_id'], str(plan['build_number']), plan.get('version_name') or plan['upstream_tag'][1:])
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



def create_release_source_tag(plan):
    """Tag a complete app tree while keeping GitHub workflows identical to main.

    GITHUB_TOKEN has contents:write but cannot push a tag whose commit introduces
    workflow files. Use the maintenance revision as the tag commit's parent and
    stage its workflows (without changing the actual built source worktree).
    The complete-source.tar.gz release asset, created before this step, remains
    the exact patched build tree including upstream workflows and submodules.
    """
    base = plan['maintenance_commit']
    current = run('git', 'rev-parse', 'HEAD', cwd=ROOT, capture=True).strip()
    if current != base:
        raise RuntimeError('Maintenance checkout changed after source preparation')
    run('git', 'add', '-A', cwd=SOURCE)
    run('git', 'restore', '--staged', f'--source={base}', '--',
        '.github/workflows', cwd=SOURCE)
    tree = run('git', 'write-tree', cwd=SOURCE, capture=True).strip()
    staged_workflows = run('git', 'rev-parse', f'{tree}:.github/workflows',
                           cwd=SOURCE, capture=True).strip()
    maintained_workflows = run('git', 'rev-parse', f'{base}:.github/workflows',
                               cwd=SOURCE, capture=True).strip()
    if staged_workflows != maintained_workflows:
        raise RuntimeError('Release tag would modify maintained GitHub workflows')
    commit = run('git', '-c', 'user.name=Chen017',
                 '-c', 'user.email=Chen017@users.noreply.github.com',
                 'commit-tree', tree, '-p', base,
                 '-m', f'build(android): signed personal {plan["version"]}',
                 cwd=SOURCE, capture=True).strip()
    run('git', 'tag', plan['tag'], commit, cwd=SOURCE)
    return commit


def publish():
    plan = json.loads((STATE / 'plan.json').read_text())
    create_release_source_tag(plan)
    run('git', '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
        'push', 'origin', f'refs/tags/{plan["tag"]}', cwd=SOURCE)
    notes = STATE / 'notes.md'
    notes.write_text(format_release_notes(plan), encoding='utf-8')
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
