import io
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import zipfile

import release
from release import checked_patch, next_build


class ReleaseRetryTest(unittest.TestCase):
    def test_failed_publication_does_not_reuse_a_pushed_tag_or_version_code(self):
        refs = [{'ref': 'refs/tags/v0.9.3+8'}, {'ref': 'refs/tags/v0.9.4'},
                {'ref': 'refs/tags/v0.9.2+4'}]
        self.assertEqual(next_build({'build_number': 7}, refs), 9)
        self.assertEqual(next_build(None, refs), 9)
        self.assertEqual(next_build({'build_number': 10}, refs), 11)
        self.assertEqual(next_build(None, []), 1)

    def test_non_conflicting_upstream_edit_survives_patch_rebase(self):
        with TemporaryDirectory(prefix='personal-patch-') as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root)

            git('init', '-q')
            git('config', 'user.name', 'Patch test')
            git('config', 'user.email', 'patch@example.invalid')
            original = [f'line {i}\n' for i in range(20)]
            source = root / 'source.txt'
            source.write_text(''.join(original))
            git('add', 'source.txt')
            git('commit', '-qm', 'baseline')
            changed = list(original)
            changed[5] = 'personal feature\n'
            source.write_text(''.join(changed))
            patch = root / 'feature.patch'
            patch.write_bytes(git('diff', '--full-index'))
            changed = list(original)
            changed[7] = 'upstream improvement\n'
            source.write_text(''.join(changed))
            git('add', 'source.txt')
            git('commit', '-qm', 'upstream')
            checked_patch(patch, root)
            result = source.read_text()
            self.assertIn('personal feature', result)
            self.assertIn('upstream improvement', result)


class PrepareTest(unittest.TestCase):
    release = {'tag_name': 'v0.9.3', 'draft': False, 'prerelease': False}
    revision = 'a' * 40

    def setUp(self):
        temporary = TemporaryDirectory(prefix='personal-prepare-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        personal = root / '.personal'
        personal.mkdir()
        state = personal / 'work'
        self.enterContext(mock.patch.multiple(release, ROOT=root, STATE=state, SOURCE=state / 'source'))
        script = personal / 'release.py'
        script.write_text('packaging code')
        self.digest = release.inputs_digest([script])
        (personal / 'test_release.py').write_text('changed test code')
        self.output = self.enterContext(mock.patch.object(release, 'output'))
        self.run = self.enterContext(mock.patch.object(release, 'run'))

    def test_unchanged_release_does_not_fetch_or_prepare_worktree(self):
        previous = {'assets': [{'name': 'manifest.json', 'browser_download_url': 'https://example.invalid'}]}
        manifest = {'upstream_commit': self.revision, 'inputs_sha256': self.digest}
        with mock.patch.object(release, 'api', side_effect=[self.release, {'sha': self.revision}, previous]), \
             mock.patch.object(release.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(manifest).encode())):
            release.prepare()

        self.output.assert_called_once_with(needed=False)
        self.run.assert_not_called()

    def test_moved_tag_stops_before_creating_worktree(self):
        self.run.side_effect = [None, 'b' * 40]
        with mock.patch.object(release, 'api', side_effect=[self.release, {'sha': self.revision}, None, []]), \
             self.assertRaisesRegex(RuntimeError, 'changed during preparation'):
            release.prepare()

        self.assertEqual(self.run.call_args_list, [
            mock.call('git', 'fetch', '--depth', '1', '--no-tags', release.UPSTREAM_GIT, 'refs/tags/v0.9.3'),
            mock.call('git', 'rev-parse', 'FETCH_HEAD^{commit}', capture=True),
        ])


class PackageTest(unittest.TestCase):
    certificate = 'a' * 64
    identity = "package: name='io.github.chen017.flclash' versionCode='7' versionName='0.9.3'"
    signer = f'Signer #1 certificate SHA-256 digest: {certificate}\n'

    def setUp(self):
        temporary = TemporaryDirectory(prefix='personal-package-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        state = root / '.personal/work'
        self.dist = root / '.personal/dist'
        self.source = state / 'source'
        self.enterContext(mock.patch.multiple(release, ROOT=root, STATE=state, SOURCE=self.source, DIST=self.dist))
        self.enterContext(mock.patch.dict(release.os.environ, ANDROID_CERT_SHA256=self.certificate))
        self.run = self.enterContext(mock.patch.object(release, 'run'))
        self.apk = self.source / 'build/app/outputs/flutter-apk/app-arm64-v8a-release.apk'
        self.apk.parent.mkdir(parents=True)
        self.write_apk('lib/arm64-v8a/libclash.so')
        release.write_json(state / 'plan.json', dict(
            package_id='io.github.chen017.flclash', build_number=7, version='0.9.3+7', tag='v0.9.3+7',
            upstream_tag='v0.9.3',
        ))
        (root / '.personal/core.patch').write_text('patch contents')
        (self.source / 'README.md').write_text('source')
        core = self.source / 'core/Clash.Meta'
        core.mkdir(parents=True)
        (core / 'fragment.go').write_text('patched core')

    def write_apk(self, *libraries):
        with zipfile.ZipFile(self.apk, 'w') as apk:
            for library in libraries:
                apk.writestr(library, 'test library')

    def test_verified_assets_contain_checksums_and_patched_submodule_source(self):
        self.run.side_effect = [self.signer, self.identity, 'README.md\0', '', 'fragment.go\0']
        release.package()

        manifest = json.loads((self.dist / 'manifest.json').read_text())
        apk = self.dist / 'FlClash-0.9.3+7-android-arm64-v8a.apk'
        self.assertEqual(manifest['apk']['sha256'], release.sha(apk))
        with tarfile.open(self.dist / 'complete-source.tar.gz') as archive:
            self.assertEqual(archive.getnames(), ['FlClash-personal/README.md', 'FlClash-personal/core/Clash.Meta/fragment.go'])
        self.assertEqual(set((self.dist / 'SHA256SUMS').read_text().splitlines()), {
            f'{release.sha(file)}  {file.name}' for file in self.dist.iterdir() if file.name != 'SHA256SUMS'
        })

    def test_truncated_certificate_is_rejected_before_running_apksigner(self):
        with mock.patch.dict(release.os.environ, ANDROID_CERT_SHA256=self.certificate[:8]), \
             self.assertRaisesRegex(RuntimeError, 'full signing certificate SHA-256'):
            release.package()
        self.run.assert_not_called()

    def test_a_matching_certificate_cannot_hide_an_extra_signer(self):
        self.run.return_value = self.signer + 'Signer #2 certificate SHA-256 digest: ' + 'b' * 64
        with self.assertRaisesRegex(RuntimeError, 'sole signer'):
            release.package()

    def test_package_line_must_match_identity_and_both_versions(self):
        for info in (
            self.identity.replace('io.github.chen017.flclash', 'com.follow.clash'),
            self.identity.replace("versionCode='7'", "versionCode='8'"),
            self.identity.replace("versionName='0.9.3'", "versionName='0.9.4'"),
        ):
            with self.subTest(info=info), self.assertRaisesRegex(RuntimeError, 'Wrong APK package identity/version'):
                self.run.side_effect = [self.signer, info + '\nother: ' + self.identity]
                release.package()

    def test_arm64_only_apk_must_include_clash_library(self):
        for libraries in (('lib/arm64-v8a/libother.so',),
                          ('lib/arm64-v8a/libclash.so', 'lib/x86_64/libclash.so')):
            with self.subTest(libraries=libraries), self.assertRaisesRegex(RuntimeError, 'only arm64 with libclash.so'):
                self.write_apk(*libraries)
                self.run.side_effect = [self.signer, self.identity]
                release.package()


if __name__ == '__main__':
    unittest.main()
