"""Check the public static site's metadata, structured data, sitemap, and links."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'docs'
SITE = 'https://saireddybv.github.io/wirebrain/'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.links = []
        self.ids = set()
        self.h1 = 0
        self.canonical = None
        self.title = ''
        self.json_ld = []
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if 'id' in attr:
            assert attr['id'] not in self.ids, 'Duplicate HTML id'
            self.ids.add(attr['id'])
        if tag == 'meta':
            self.meta[attr.get('name') or attr.get('property')] = attr.get('content', '')
        if tag == 'h1':
            self.h1 += 1
        if tag == 'link' and attr.get('rel') == 'canonical':
            self.canonical = attr['href']
        if tag == 'title':
            self.capture = 'title'
        if tag == 'script' and attr.get('type') == 'application/ld+json':
            self.capture = 'json'
        for key in ('href', 'src'):
            if attr.get(key):
                self.links.append(attr[key])

    def handle_data(self, data):
        if self.capture == 'title':
            self.title += data
        elif self.capture == 'json':
            self.json_ld.append(data)

    def handle_endtag(self, tag):
        if tag in ('title', 'script'):
            self.capture = None


def check():
    page = Page()
    page.feed((ROOT / 'index.html').read_text(encoding='utf-8'))
    assert page.title.strip() and page.h1 == 1, 'Provide a title and one H1'
    assert page.meta.get('description') and page.meta.get('viewport')
    assert 'noindex' not in page.meta.get('robots', '')
    assert page.canonical == SITE and page.meta.get('og:url') == SITE
    app = json.loads(''.join(page.json_ld))
    assert app['@type'] == 'SoftwareApplication' and app['url'] == SITE
    for href in page.links:
        url = urlsplit(href)
        if url.scheme or url.netloc:
            continue
        path = unquote(url.path)
        target = (ROOT / path.lstrip('/')).resolve()
        assert target.is_relative_to(ROOT.resolve()), f'Link escapes site: {href}'
        assert target.exists(), f'Missing local resource: {href}'
        if not path or path in ('.', './'):
            assert not url.fragment or url.fragment in page.ids, f'Missing section: {href}'
    sitemap = ET.parse(ROOT / 'sitemap.xml')
    urls = [loc.text for loc in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    assert urls == [SITE], 'Sitemap must list canonical public pages'
    assert (ROOT / '.nojekyll').exists(), 'Keep static publishing enabled'
    print('Public site metadata, structured data, sitemap, and local links pass.')


if __name__ == '__main__':
    check()
