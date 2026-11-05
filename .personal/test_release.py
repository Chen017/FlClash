import unittest
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

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


if __name__ == '__main__':
    unittest.main()
