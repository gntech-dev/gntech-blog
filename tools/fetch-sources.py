#!/usr/bin/env python3
"""Fetch blog content sources for topic discovery. Outputs JSON to stdout."""
import json, os, subprocess, sys, time, hashlib
from urllib.request import Request, urlopen
from urllib.error import URLError
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(SCRIPT_DIR, "sources.yaml")
CACHE_DIR = os.path.join(SCRIPT_DIR, ".source_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Try to import yaml, fallback to simple parsing
try:
    import yaml
except ImportError:
    yaml = None

def load_sources():
    """Load sources.yaml config."""
    if not os.path.exists(SOURCES_FILE):
        print(json.dumps({"sources": [], "searches": []}), file=sys.stderr)
        sys.exit(1)
    
    if yaml:
        with open(SOURCES_FILE) as f:
            return yaml.safe_load(f)
    else:
        # Fallback: use python3 yaml via subprocess
        result = subprocess.run(
            [sys.executable, "-c", f"""
import yaml, json
with open('{SOURCES_FILE}') as f:
    print(json.dumps(yaml.safe_load(f)))
"""], capture_output=True, text=True, timeout=10
        )
        return json.loads(result.stdout)

def fetch_url(url, timeout=12):
    """Fetch a URL with a User-Agent."""
    req = Request(url, headers={"User-Agent": "gntech-blog/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None

def parse_rss(text):
    """Parse RSS/Atom XML, return up to 8 items."""
    items = []
    try:
        root = ET.fromstring(text)
        # RSS items
        for item in root.iter("item"):
            title = ""
            link = ""
            date = ""
            t = item.find("title")
            if t is not None and t.text:
                title = t.text[:120]
            l = item.find("link")
            if l is not None and l.text:
                link = l.text
            d = item.find("pubDate")
            if d is not None and d.text:
                date = d.text[:25]
            if title or link:
                items.append({"title": title, "link": link, "date": date})
        # Atom entries
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = ""
            link = ""
            date = ""
            t = entry.find("atom:title", ns)
            if t is not None and t.text:
                title = t.text[:120]
            l = entry.find("atom:link", ns)
            if l is not None:
                link = l.get("href", "")
            d = entry.find("atom:updated", ns)
            if d is not None and d.text:
                date = d.text[:25]
            if title or link:
                items.append({"title": title, "link": link, "date": date})
    except Exception:
        pass
    return items[:8]

def parse_reddit(text):
    """Parse Reddit JSON hot listing."""
    items = []
    try:
        data = json.loads(text)
        for child in data.get("data", {}).get("children", [])[:8]:
            d = child.get("data", {})
            items.append({
                "title": d.get("title", "")[:120],
                "link": "https://reddit.com" + d.get("permalink", ""),
                "date": str(d.get("created_utc", "")),
                "score": d.get("score", 0),
            })
    except Exception:
        pass
    return items

def parse_algolia(text):
    """Parse Algolia HN search results."""
    items = []
    try:
        data = json.loads(text)
        for hit in data.get("hits", [])[:8]:
            items.append({
                "title": hit.get("title", "")[:120],
                "link": hit.get("url", "") or hit.get("story_url", "") or "",
                "date": hit.get("created_at", "") or "",
            })
    except Exception:
        pass
    return items

def get_cached_or_fetch(name, url, source_type, ttl=14400):
    """Fetch with 4hr cache."""
    cache_key = hashlib.md5(f"{name}:{url}".encode()).hexdigest()[:12]
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    # Check cache freshness
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < ttl:
            with open(cache_path) as f:
                return json.load(f)
    
    raw = fetch_url(url)
    if raw is None:
        # Try stale cache
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                return json.load(f)
        return []
    
    if source_type == "rss":
        items = parse_rss(raw)
    elif source_type == "reddit":
        items = parse_reddit(raw)
    elif source_type == "algolia":
        items = parse_algolia(raw)
    else:
        items = []
    
    with open(cache_path, "w") as f:
        json.dump(items, f)
    return items

def main():
    conf = load_sources()
    feeds = conf.get("feeds", [])
    queries = conf.get("search_queries", [])
    
    output_sources = []
    for feed in feeds:
        name = feed.get("name", "unknown")
        url = feed.get("url", "")
        stype = feed.get("type", "rss")
        topics = feed.get("topics", [])
        
        items = get_cached_or_fetch(name, url, stype)
        output_sources.append({
            "name": name,
            "type": stype,
            "topics": topics,
            "items": items,
        })
    
    output_queries = []
    for q in queries:
        output_queries.append({
            "query": q.get("query", ""),
            "days_old": q.get("days_old", 30),
            "topics": q.get("topics", []),
        })
    
    result = {"sources": output_sources, "searches": output_queries}
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
