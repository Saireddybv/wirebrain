# Search visibility

The public project site is https://saireddybv.github.io/wirebrain/. It is plain HTML and CSS served from `main:/docs` with GitHub Pages. It has no JavaScript bundle, tracking, animation, external fonts, or connection to anyone's local diary. GitHub Pages publishes only the public documentation folder; never put real conversations or account data here.

## What is configured

- A descriptive page title, readable product content, one main heading, and installation instructions.
- A canonical URL, mobile viewport, social sharing metadata, and SoftwareApplication JSON-LD describing the free MIT-licensed tool.
- A sitemap at https://saireddybv.github.io/wirebrain/sitemap.xml with only canonical public pages.
- Repository topics, a clear About description, a website link, and Python package discovery metadata.
- A noindex 404 page. Ordinary pages are crawlable by default; a robots file is not required. A robots.txt inside this project subdirectory would not control the host's root crawl policy.

Structured data describes the application; it does not guarantee a rich result. No fabricated ratings, user counts, keyword stuffing, or duplicate keyword pages are used. Content must reflect the published version, not unpublished local features.

## Owner's indexing setup

1. Open [Google Search Console](https://search.google.com/search-console) using the account that should own this project property.
2. Add the URL-prefix property `https://saireddybv.github.io/wirebrain/` and complete Google's ownership verification. For HTML-file verification, place the exact supplied file in `docs/` through a PR. For HTML-tag verification, add the exact supplied meta tag to `docs/index.html`. Do not invent a verification token.
3. Submit `https://saireddybv.github.io/wirebrain/sitemap.xml` and inspect the home URL to request indexing.
4. Check indexing coverage and search queries after Google has crawled it. Improve useful docs and earn relevant community links through real contributions and releases.

Search Console ownership has not been configured by this change. Google decides whether and when to index a site and how to rank it. A sitemap, metadata, or Search Console submission cannot guarantee a top result. See Google's [SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide) and [indexing FAQ](https://developers.google.com/search/help/crawling-index-faq).

## Keeping it accurate

Run `python scripts/check_site.py` after editing the site. Keep the canonical URL, sitemap, structured data, repository homepage, and package URLs consistent. If you add a useful public page, give it its own title and description, link it from the site, and add its canonical URL to the sitemap. Keep private diary pages out of the public site. On a future domain migration, plan redirects and update these URLs together.
