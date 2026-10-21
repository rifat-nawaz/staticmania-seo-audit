# StaticMania blog technical SEO audit

Technical SEO audit of every live article on https://staticmania.com/blog, run on 21 October 2026.

- `report/index.html` – the full report: sitewide template fixes, removed URLs, and all 240 articles ranked for refresh (open it in a browser).
- `report/StaticMania-blog-SEO-audit-2026-10-21.xlsx` – tracker: one row per issue with a Status column, plus sitewide fixes, broken links and removed URLs.
- `crawler/crawl.py` – the read-only crawler used to collect the data (Python 3, standard library only). `seed_urls.txt` is the article list from Search Console.

## Re-running the crawl

```
cd crawler && python3 crawl.py
```

It writes `crawl_out/` (page HTML, link and image status) next to the script. It only sends GET/HEAD requests.

## Top findings

1. 140 of 240 articles are missing from `sitemap.xml`.
2. Blog pagination links on `/blog` have no `href`, so crawlers can't reach older articles.
3. 237 articles have no Article/BlogPosting schema and no visible "Updated" date.
4. The hero (LCP) image is lazy-loaded on every article.
5. 104 articles link to old `/service/*` URLs that redirect; 41 broken links across 27 articles.
