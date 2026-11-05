import unittest

from release import next_build


class ReleaseRetryTest(unittest.TestCase):
    def test_failed_publication_does_not_reuse_a_pushed_tag_or_version_code(self):
        refs = [{'ref': 'refs/tags/v0.9.3+8'}, {'ref': 'refs/tags/v0.9.4'},
                {'ref': 'refs/tags/v0.9.2+4'}]
        self.assertEqual(next_build({'build_number': 7}, refs), 9)
        self.assertEqual(next_build(None, refs), 9)
        self.assertEqual(next_build({'build_number': 10}, refs), 11)
        self.assertEqual(next_build(None, []), 1)


if __name__ == '__main__':
    unittest.main()
