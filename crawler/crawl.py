#!/usr/bin/env python3
"""Read-only crawler for staticmania.com blog articles. Stdlib only.
Writes everything into ./crawl_out next to this script."""
import os, re, sys, json, time, gzip, ssl, threading
import urllib.request, urllib.error, urllib.parse
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor

BASE = "https://staticmania.com"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "crawl_out"); os.makedirs(os.path.join(OUT, "html"), exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36 SEO-audit-readonly"
CTX = ssl.create_default_context()
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    for _p in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"):
        if os.path.exists(_p):
            CTX = ssl.create_default_context(cafile=_p); break
lock = threading.Lock()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=CTX))

def fetch(url, method="GET", max_hops=6, read=True):
    chain = []; cur = url; t0 = time.time()
    for _ in range(max_hops):
        req = urllib.request.Request(cur, method=method, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*"})
        try:
            r = opener.open(req, timeout=30); code = r.status; hdrs = dict(r.headers)
            ttfb = time.time() - t0
            body = r.read() if read else b""
        except urllib.error.HTTPError as e:
            code = e.code; hdrs = dict(e.headers); ttfb = time.time() - t0
            try: body = e.read() if read else b""
            except Exception: body = b""
        except Exception as e:
            return {"url": url, "final": cur, "status": 0, "error": str(e)[:200], "chain": chain}
        if code in (301, 302, 303, 307, 308) and (hdrs.get("Location") or hdrs.get("location")):
            loc = hdrs.get("Location") or hdrs.get("location")
            chain.append([cur, code]); cur = urllib.parse.urljoin(cur, loc); continue
        if hdrs.get("Content-Encoding", hdrs.get("content-encoding", "")) == "gzip" and body:
            try: raw_len = len(body); body = gzip.decompress(body)
            except Exception: raw_len = len(body)
        else: raw_len = len(body)
        return {"url": url, "final": cur, "status": code, "chain": chain, "headers": hdrs,
                "ttfb": round(ttfb, 3), "total": round(time.time() - t0, 3), "transfer_bytes": raw_len, "body": body}
    return {"url": url, "final": cur, "status": -1, "error": "too many redirects", "chain": chain}

class Links(HTMLParser):
    def __init__(s): super().__init__(); s.a = []; s.img = []
    def handle_starttag(s, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"): s.a.append(d["href"])
        if tag in ("img", "source"):
            for k in ("src", "srcset", "data-src"):
                if d.get(k): s.img.append(d[k].split(",")[0].strip().split(" ")[0])

def log(*a):
    with lock: print(*a, flush=True)

def main():
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # robots + sitemaps
    rb = fetch(BASE + "/robots.txt"); robots = rb.get("body", b"").decode("utf-8", "replace")
    open(os.path.join(OUT, "robots.txt"), "w").write(robots)
    sitemaps = re.findall(r"(?im)^sitemap:\s*(\S+)", robots) or [BASE + "/sitemap.xml"]
    for s in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap-0.xml"):
        if BASE + s not in sitemaps: sitemaps.append(BASE + s)
    seen_sm = set(); sm_urls = {}; sm_files = {}
    while sitemaps:
        s = sitemaps.pop(0)
        if s in seen_sm: continue
        seen_sm.add(s); r = fetch(s); sm_files[s] = r.get("status")
        if r.get("status") != 200: continue
        x = r["body"].decode("utf-8", "replace")
        if "<sitemapindex" in x:
            sitemaps += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", x)
        else:
            for blk in re.findall(r"<url>(.*?)</url>", x, re.S):
                loc = re.search(r"<loc>\s*([^<\s]+)", blk); lm = re.search(r"<lastmod>\s*([^<\s]+)", blk)
                if loc: sm_urls[loc.group(1)] = lm.group(1) if lm else None
    log("sitemap files", sm_files, "urls", len(sm_urls))
    # blog listing pages (follow pagination)
    listing_seen = set(); queue = [BASE + "/blog"]; articles = set(); listing_status = {}
    def is_listing(u):
        p = urllib.parse.urlparse(u)
        return p.netloc.endswith("staticmania.com") and (re.match(r"^/blog/?$", p.path) and p.query or re.match(r"^/blog/page/\d+/?$", p.path) or re.match(r"^/blog/?$", p.path))
    while queue:
        u = queue.pop(0)
        if u in listing_seen or len(listing_seen) > 120: continue
        listing_seen.add(u); r = fetch(u); listing_status[u] = r.get("status")
        if r.get("status") != 200: continue
        p = Links(); p.feed(r["body"].decode("utf-8", "replace"))
        for h in p.a:
            full = urllib.parse.urljoin(u, h).split("#")[0]
            pu = urllib.parse.urlparse(full)
            if not pu.netloc.endswith("staticmania.com"): continue
            if is_listing(full):
                if full not in listing_seen: queue.append(full)
            elif re.match(r"^/blog/[^/]+/?$", pu.path) and not pu.query and not re.match(r"^/blog/(page|category|tag|tags|author)/?", pu.path):
                articles.add(full.rstrip("/") if full.endswith("/") and False else full)
        time.sleep(0.3)
    # fallback: probe common pagination patterns in case pagination is JS-only
    if len(listing_seen) < 5:
        for pat in (BASE + "/blog/page/{}", BASE + "/blog?page={}"):
            for n in range(2, 80):
                u = pat.format(n)
                if u in listing_seen: continue
                r = fetch(u); listing_status[u] = r.get("status"); listing_seen.add(u)
                if r.get("status") != 200 or r.get("final") != u: break
                p = Links(); p.feed(r["body"].decode("utf-8", "replace")); found = 0
                for h in p.a:
                    full = urllib.parse.urljoin(u, h).split("#")[0]; pu = urllib.parse.urlparse(full)
                    if pu.netloc.endswith("staticmania.com") and re.match(r"^/blog/[^/]+/?$", pu.path) and not pu.query and not re.match(r"^/blog/(page|category|tag|tags|author)/?", pu.path):
                        if full not in articles: found += 1
                        articles.add(full)
                if not found: break
                time.sleep(0.3)
    log("listing pages", len(listing_seen), "articles from listing", len(articles))
    sm_blog = {u for u in sm_urls if re.match(r"^https?://[^/]+/blog/[^/]+/?$", u)}
    seeds = set()
    sp = os.path.join(HERE, "seed_urls.txt")
    if os.path.exists(sp): seeds = {l.strip() for l in open(sp) if l.strip()}
    meta["articles_from_gsc_seed"] = sorted(seeds)
    all_articles = sorted(articles | sm_blog | seeds)
    meta.update({"sitemap_files": sm_files, "sitemap_url_count": len(sm_urls), "listing_status": listing_status,
                 "articles_from_listing": sorted(articles), "articles_from_sitemap": sorted(sm_blog), "sitemap_lastmod": sm_urls})
    # fetch articles
    pages = {}
    def get_article(u):
        r = fetch(u); body = r.pop("body", b"")
        fn = re.sub(r"[^a-zA-Z0-9]+", "_", urllib.parse.urlparse(u).path).strip("_") + ".html.gz"
        if body: open(os.path.join(OUT, "html", fn), "wb").write(gzip.compress(body))
        r["file"] = fn; r["html_bytes"] = len(body); pages[u] = r
        log(r.get("status"), r.get("ttfb"), u); time.sleep(0.2)
    with ThreadPoolExecutor(4) as ex: list(ex.map(get_article, all_articles))
    # collect link + image targets
    targets = set(); imgs = set()
    for u, r in pages.items():
        fp = os.path.join(OUT, "html", r["file"])
        if not os.path.exists(fp): continue
        p = Links(); p.feed(gzip.decompress(open(fp, "rb").read()).decode("utf-8", "replace"))
        for h in p.a:
            if h.startswith(("mailto:", "tel:", "javascript:", "#")): continue
            targets.add(urllib.parse.urljoin(u, h).split("#")[0])
        for s in p.img:
            if s.startswith("data:"): continue
            imgs.add(urllib.parse.urljoin(u, s))
    log("unique link targets", len(targets), "images", len(imgs))
    link_status = {}; img_info = {}
    def check(u):
        r = fetch(u, method="HEAD", read=False)
        if r.get("status") in (0, 403, 405, 400, 501) or r.get("status", 0) >= 500:
            r = fetch(u, method="GET", read=False)
        h = r.get("headers", {}) or {}
        link_status[u] = {"status": r.get("status"), "final": r.get("final"), "hops": len(r.get("chain", [])), "error": r.get("error")}
    def check_img(u):
        r = fetch(u, method="HEAD", read=False)
        h = {k.lower(): v for k, v in (r.get("headers") or {}).items()}
        img_info[u] = {"status": r.get("status"), "type": h.get("content-type"), "bytes": h.get("content-length"), "final": r.get("final")}
    with ThreadPoolExecutor(8) as ex: list(ex.map(check, sorted(targets)))
    with ThreadPoolExecutor(8) as ex: list(ex.map(check_img, sorted(imgs)))
    # misc checks
    extra = {}
    for name, u in {"blog_http": "http://staticmania.com/blog", "blog_www": "https://www.staticmania.com/blog",
                    "blog_slash": BASE + "/blog/", "notfound": BASE + "/blog/this-page-should-not-exist-xyz"}.items():
        r = fetch(u, read=False); extra[name] = {"status": r.get("status"), "final": r.get("final"), "chain": r.get("chain")}
    meta["extra"] = extra; meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1, default=str)
    json.dump(pages, open(os.path.join(OUT, "pages.json"), "w"), indent=1, default=str)
    json.dump(link_status, open(os.path.join(OUT, "links.json"), "w"), indent=1)
    json.dump(img_info, open(os.path.join(OUT, "images.json"), "w"), indent=1)
    # bundle for easy transfer
    import tarfile
    with tarfile.open(os.path.join(HERE, "crawl_out.tar.gz"), "w:gz") as t: t.add(OUT, arcname="crawl_out")
    log("DONE", len(pages), "articles")

if __name__ == "__main__": main()
