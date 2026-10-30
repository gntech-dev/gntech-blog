"""Regression checks for article publication mistakes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'publication', Path(__file__).with_name('check-publication.py'))
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.article = self.root / 'content/posts/example.md'
        self.article.parent.mkdir(parents=True)

    def check(self, metadata, allow=False):
        self.article.write_text('---\ntitle: Example\n' + metadata + '\n---\nBody\n')
        return publication.check_article(self.article, self.root, allow)

    def test_published_article(self):
        self.assertEqual(self.check('draft: false'), [])

    def test_ready_pr_rejects_hidden_post(self):
        self.assertTrue(self.check('draft: true'))

    def test_draft_pr_accepts_hidden_post(self):
        self.assertEqual(self.check('draft: true', allow=True), [])

    def test_string_draft_is_rejected(self):
        self.assertTrue(self.check('draft: "false"'))

    def test_missing_cover(self):
        self.assertTrue(self.check('cover:\n  image: /images/missing.webp\n  alt: A server'))

    def test_existing_cover(self):
        image = self.root / 'static/images/cover.webp'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'fixture')
        self.assertEqual(self.check('cover:\n  image: /images/cover.webp\n  alt: A server'), [])

    def test_missing_alt(self):
        self.assertTrue(self.check('cover:\n  image: https://example.com/image.webp'))

    def test_malformed_front_matter(self):
        self.assertTrue(self.check('cover: [broken'))

    def test_toml(self):
        self.article.write_text('+++\ntitle = "Example"\ndraft = false\n+++\nBody\n')
        self.assertEqual(publication.check_article(self.article, self.root), [])


if __name__ == '__main__':
    unittest.main()
