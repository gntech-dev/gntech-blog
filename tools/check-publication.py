#!/usr/bin/env python3
"""Check changed Hugo articles before publication; never execute article commands."""
import argparse
from pathlib import Path
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit

import yaml


def front_matter(text):
    lines = text.splitlines()
    if not lines or lines[0] not in ('---', '+++'):
        raise ValueError('missing YAML or TOML front matter')
    marker = lines[0]
    try:
        end = lines.index(marker, 1)
    except ValueError:
        raise ValueError('front matter has no closing delimiter') from None
    body = '\n'.join(lines[1:end])
    data = yaml.safe_load(body) if marker == '---' else tomllib.loads(body)
    if not isinstance(data, dict):
        raise ValueError('front matter must be a mapping')
    return data


def check_article(path, root, allow_drafts=False):
    errors = []
    try:
        data = front_matter(path.read_text(encoding='utf-8'))
    except (ValueError, yaml.YAMLError) as exc:
        return [f'{path.relative_to(root)}: {exc}']
    if not isinstance(data.get('title'), str) or not data['title'].strip():
        errors.append('title must be a nonempty string')
    draft = data.get('draft', False)
    if not isinstance(draft, bool):
        errors.append('draft must be a boolean, not a quoted string')
    elif draft and not allow_drafts:
        errors.append('draft: true hides this article; publish it or keep the PR in draft')
    cover = data.get('cover')
    if cover is not None:
        if not isinstance(cover, dict):
            errors.append('cover must be a mapping')
        elif cover.get('image'):
            image = cover['image']
            if not isinstance(image, str):
                errors.append('cover.image must be a string')
            else:
                url = urlsplit(image)
                if url.scheme or url.netloc:
                    if url.scheme not in ('http', 'https') or not url.netloc:
                        errors.append('cover.image must be a local asset or HTTP(S) URL')
                else:
                    asset = unquote(url.path)
                    candidates = [root / 'static' / asset.lstrip('/'),
                                  root / 'assets' / asset.lstrip('/')]
                    if not asset.startswith('/'):
                        candidates.insert(0, path.parent / asset)
                    if not any(p.resolve().is_relative_to(root) and p.is_file()
                               for p in candidates):
                        errors.append(f'missing local cover image: {image}')
            if not isinstance(cover.get('alt'), str) or not cover['alt'].strip():
                errors.append('cover.alt must describe the image')
    return [f'{path.relative_to(root)}: {error}' for error in errors]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--allow-drafts', action='store_true')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    changed = subprocess.check_output([
        'git', 'diff', '--name-only', '-z', '--diff-filter=ACMR',
        args.base, args.head, '--', 'content',
    ]).decode().split('\0')
    errors = []
    checked = 0
    for name in changed:
        path = Path(name)
        if path.suffix != '.md' or 'posts' not in path.parts or path.name == '_index.md':
            continue
        checked += 1
        errors.extend(check_article(root / path, root, args.allow_drafts))
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'PASS: publication metadata and cover assets for {checked} changed articles')
    return 0


if __name__ == '__main__':
    sys.exit(main())
