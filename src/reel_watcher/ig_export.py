"""Turn an Instagram "Download your information" export into a URL list for reel-watcher.

How to get the export (Instagram app or web, Accounts Center):
  Settings > Accounts Center > Your information and permissions > Download your information
  > Download or transfer information > choose your Instagram account > Some of your information
  > tick "Saved" (under Your Instagram activity) > Export to device > Format: JSON.
Unzip the download. The saved posts are in a JSON file such as
  your_instagram_activity/saved/saved_posts.json
and named collections, if you have any, in saved_collections.json next to it.

Shape this parser expects (as documented by users of the export; Instagram changes it
from time to time, so the parser is deliberately tolerant):
  {"saved_saved_media": [
      {"title": "<creator username>",
       "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/<code>/", "timestamp": 1700000000}}}]}
Rather than trust one exact layout, it walks the whole JSON and collects every
instagram.com/reel|p|tv link, using the nearest "title" as the creator hint. HTML exports work
too (links are read with a regex). If your export looks different, any file with one URL per line
is accepted by `reel-watcher study` directly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import media

URL_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:reels?|p|tv)/[A-Za-z0-9_-]+/?[^\s\"'<>]*")


def _walk(node, title: str | None, out: list[tuple[str, str | None]]) -> None:
    if isinstance(node, dict):
        t = node.get("title") if isinstance(node.get("title"), str) and node.get("title") else title
        for k, v in node.items():
            if k == "href" and isinstance(v, str) and media.id_from_url(v):
                out.append((v, t))
            else:
                _walk(v, t, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, title, out)
    elif isinstance(node, str) and media.id_from_url(node) and node.startswith("http"):
        out.append((node, title))


def extract_urls(path: Path, collection: str = "") -> list[dict]:
    """Return [{url, creator, collection}] from a JSON or HTML export file, deduped by shortcode, order kept."""
    text = path.read_text(encoding="utf-8", errors="replace")
    pairs: list[tuple[str, str | None]] = []
    if path.suffix.lower() == ".json":
        _walk(json.loads(text), None, pairs)
    else:
        pairs = [(m.group(0).split("?")[0], None) for m in URL_RE.finditer(text)]
    seen, rows = set(), []
    for url, creator in pairs:
        code = media.id_from_url(url)
        if code in seen:
            continue
        seen.add(code)
        rows.append({"url": url.split("?")[0], "creator": creator, "collection": collection})
    return rows


UNSORTED = "Saved (no collection)"


def _strings(node) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for v in node.values():
            out += _strings(v)
    elif isinstance(node, list):
        for v in node:
            out += _strings(v)
    elif isinstance(node, str):
        out.append(node)
    return out


def _entry_name(entry: dict) -> str | None:
    """Collection name of a header entry, in either known layout:
    string_map_data {"Name": {"value": ...}} or label_values [{"label": "Name", "value": ...}]."""
    smd = entry.get("string_map_data")
    if isinstance(smd, dict):
        for k in ("Name", "Collection name", "Collection Name"):
            v = smd.get(k)
            if isinstance(v, dict) and isinstance(v.get("value"), str) and not v.get("href"):
                return v["value"].strip() or None
    for lv in entry.get("label_values") or []:
        if isinstance(lv, dict) and str(lv.get("label", "")).lower() in ("name", "collection name") and isinstance(lv.get("value"), str) \
                and not lv.get("href"):
            return lv["value"].strip() or None
    return None


def _entry_url(entry) -> str | None:
    for s in _strings(entry):
        if s.startswith("http") and media.id_from_url(s):
            return s.split("?")[0]
    return None


def parse_collections(data) -> dict[str, list[str]]:
    """saved_collections.json -> {collection name: [urls in order]}.
    The file is one flat list where a header entry (a name, no link) starts each collection and the following
    entries carrying an instagram link belong to it. Unknown wrappers are walked to find that list."""
    entries = None
    if isinstance(data, dict):
        for k in ("saved_saved_collections", "saved_collections"):
            if isinstance(data.get(k), list):
                entries = data[k]
        if entries is None:
            entries = next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        entries = data
    out: dict[str, list[str]] = {}
    current = None
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        url = _entry_url(e)
        name = _entry_name(e)
        if url is None and name:
            current = name
            out.setdefault(current, [])
        elif url and current is not None:
            if url not in out[current]:
                out[current].append(url)
        # nested layout: a header entry may carry its items in a child list
        for v in e.values():
            if isinstance(v, list) and name and url is None and v and all(isinstance(x, dict) for x in v):
                for child in v:
                    cu = _entry_url(child)
                    if cu and cu not in out[name]:
                        out[name].append(cu)
    return out


def read_export(path: Path) -> dict[str, list[str]]:
    """Instagram export (the .zip, the unzipped folder, or the JSON files) -> {collection: [urls]}.
    Saved posts that are in no collection go to UNSORTED. Every URL appears once per collection."""
    import zipfile
    path = Path(path).expanduser()
    files: dict[str, str] = {}
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                base = n.rsplit("/", 1)[-1].lower()
                if base in ("saved_collections.json", "saved_posts.json", "saved_collections.html", "saved_posts.html"):
                    files[base] = z.read(n).decode("utf-8", errors="replace")
    elif path.is_dir():
        for p in path.rglob("*"):
            if p.name.lower() in ("saved_collections.json", "saved_posts.json", "saved_collections.html", "saved_posts.html"):
                files[p.name.lower()] = p.read_text(encoding="utf-8", errors="replace")
    elif path.is_file():
        files[path.name.lower()] = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, list[str]] = {}
    if "saved_collections.json" in files:
        out = parse_collections(json.loads(files["saved_collections.json"]))
    in_any = {media.id_from_url(u) for urls in out.values() for u in urls}
    posts: list[str] = []
    for name in ("saved_posts.json", "saved_posts.html"):
        if name in files:
            pairs: list[tuple[str, str | None]] = []
            if name.endswith(".json"):
                _walk(json.loads(files[name]), None, pairs)
            else:
                pairs = [(m.group(0), None) for m in URL_RE.finditer(files[name])]
            posts += [u.split("?")[0] for u, _ in pairs]
            break
    seen = set()
    for u in posts:
        code = media.id_from_url(u)
        if code and code not in in_any and code not in seen:
            seen.add(code)
            out.setdefault(UNSORTED, []).append(u)
    return out


def import_into(lib, path: Path) -> dict[str, int]:
    """Add every reel of an export to the library, tagged with its collections. Returns {collection: count}."""
    cols = read_export(path)
    counts = {}
    for name, urls in cols.items():
        for u in urls:
            code = media.id_from_url(u)
            # imported reels stay idle until the user starts reading their collection
            lib.add_item(f"reel:{code[3:]}", "reel", u, [name], status="idle")
        counts[name] = len(urls)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reel-watcher export", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="saved_posts.json (or other export JSON/HTML files)")
    ap.add_argument("-o", "--out", required=True, help="TSV to write (url<TAB>collection)")
    ap.add_argument("--collection", default="", help="label to attach to every URL from these files (e.g. the file's collection name)")
    a = ap.parse_args(argv)
    rows, seen = [], set()
    for f in a.files:
        for r in extract_urls(Path(f).expanduser(), a.collection):
            if r["url"] not in seen:
                seen.add(r["url"])
                rows.append(r)
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"{r['url']}\t{r['collection']}\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} urls to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
