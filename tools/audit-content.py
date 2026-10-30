#!/usr/bin/env python3
"""Check source invariants and links/images in Hugo-rendered article bodies.

Run from the repository root after: hugo --destination public
This does not test commands against live infrastructure or crawl external sites.
"""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.article_depth = None
        self.links = []
        self.ids = set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'div':
            self.depth += 1
            if 'post-content' in attrs.get('class', '').split():
                self.article_depth = self.depth
        if self.article_depth is not None:
            attr = 'href' if tag == 'a' else 'src' if tag == 'img' else None
            if attr and attrs.get(attr):
                self.links.append(attrs[attr])

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.depth == self.article_depth:
                self.article_depth = None
            self.depth -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', default='public')
    args = parser.parse_args()
    errors = []
    shell_blocks = 0
    sources = list(Path('content').rglob('*.md'))
    for path in sources:
        text = path.read_text()
        if not (text.startswith('---\n') or text.startswith('+++\n')):
            errors.append(f'{path}: missing front matter')
        fence = None
        for line in text.splitlines():
            match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
            if match:
                marker, rest = match.groups()
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip():
                    fence = None
        if fence:
            errors.append(f'{path}: unclosed code fence')
        if re.search(r'^canonical:', text, re.M):
            errors.append(f'{path}: unsupported canonical field; use theme canonicalURL only for an intentional override')
        if re.search(r'^>.*Image placeholders?', text, re.M | re.I):
            errors.append(f'{path}: unfinished screenshot note')
        for block in re.findall(r'^```powershell\n(.*?)^```', text, re.M | re.S):
            if re.search(r'\\[ \t]*$', block, re.M):
                errors.append(f'{path}: Bash continuation in PowerShell block')
        for block in re.findall(r'^```(?:bash|sh|shell)\n(.*?)^```', text, re.M | re.S):
            shell_blocks += 1
            result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
            if result.returncode:
                errors.append(f'{path}: shell syntax error: {result.stderr.strip()}')
    site = Path(args.site).resolve()
    files = list(site.rglob('*.html'))
    if not files:
        errors.append(f'{site}: no rendered HTML; run hugo first')
    pages = {p.resolve(): Page(p.read_text()) for p in files}
    checked = 0
    for path, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                if url.netloc != 'blog.gntech.me':
                    continue
            if url.query:
                continue
            checked += 1
            if not url.path:
                dest = path
            else:
                base = site if url.path.startswith('/') else path.parent
                dest = (base / unquote(url.path).lstrip('/')).resolve()
                if dest.is_dir():
                    dest /= 'index.html'
            if not dest.is_relative_to(site) or not dest.is_file():
                errors.append(f'{path.relative_to(site)}: missing article target {link}')
            elif url.fragment and dest.suffix == '.html':
                target_page = pages.get(dest)
                if target_page and unquote(url.fragment) not in target_page.ids:
                    errors.append(f'{path.relative_to(site)}: missing anchor {link}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'PASS: {len(sources)} Markdown files; {shell_blocks} shell blocks parsed without execution; {len(files)} rendered HTML files; {checked} internal article links/images/anchors.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
