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


def _is_link(s) -> bool:
    return isinstance(s, str) and s.startswith("http") and media.id_from_url(s) is not None


def _entry_name(entry: dict) -> str | None:
    """Collection name of a header entry, in the known layouts:
    string_map_data {"Name": {"value": ...}} or label_values [{"label": "Name", "value": ...}].
    A field that carries a link is a saved item (its "Name" is the creator), not a collection."""
    smd = entry.get("string_map_data")
    if isinstance(smd, dict):
        for k, v in smd.items():
            if "name" in k.lower() and isinstance(v, dict) and isinstance(v.get("value"), str) and not v.get("href"):
                return v["value"].strip() or None
    for lv in entry.get("label_values") or []:
        if isinstance(lv, dict) and "name" in str(lv.get("label", "")).lower() and isinstance(lv.get("value"), str) \
                and not lv.get("href") and not _is_link(lv["value"]):
            return lv["value"].strip() or None
    for k in ("name", "collection_name"):
        if isinstance(entry.get(k), str) and entry[k].strip() and not _is_link(entry[k]):
            return entry[k].strip()
    return None


def _links(node) -> list[str]:
    return [s.split("?")[0] for s in _strings(node) if _is_link(s)]


def _entry_url(entry) -> str | None:
    found = _links(entry)
    return found[0] if found else None


def _own_and_nested_links(entry: dict) -> tuple[list[str], list[str]]:
    """Links on the entry itself (a saved item) vs links inside its child lists (a collection holding its items)."""
    own, nested = [], []
    for k, v in entry.items():
        if isinstance(v, list) and k != "label_values":
            nested += _links(v)
        elif k == "label_values" and isinstance(v, list):
            for lv in v:  # newer layout: [{"label": "Name", ...}, {"label": "Items", "vec": [...]}]
                if isinstance(lv, dict) and any(isinstance(x, list) for x in lv.values()):
                    nested += _links(lv)
                else:
                    own += _links(lv)
        else:
            own += _links(v)
    return own, nested


def _parse_entries(entries) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None

    def add(name, urls):
        lst = out.setdefault(name, [])
        for u in urls:
            if u not in lst:
                lst.append(u)
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        name = _entry_name(e)
        own, nested = _own_and_nested_links(e)
        if name and nested and not own:
            current = name  # one entry holds a whole collection
            add(name, nested)
        elif name and not own:
            current = name  # header; its items follow as separate entries
            add(name, [])
        elif own and current is not None:
            add(current, own[:1])
    return out


def _lists_of_dicts(node, depth=0):
    if depth > 6:
        return
    if isinstance(node, list):
        if node and sum(isinstance(x, dict) for x in node) >= len(node) / 2:
            yield node
        for x in node:
            yield from _lists_of_dicts(x, depth + 1)
    elif isinstance(node, dict):
        for v in node.values():
            yield from _lists_of_dicts(v, depth + 1)


def parse_collections(data) -> dict[str, list[str]]:
    """saved_collections.json -> {collection name: [urls in order]}.
    Handles a flat list where a header entry (a name, no link) starts each collection and the following entries
    carry its links, and a layout where each entry holds its collection's links in a child list. Instagram changes
    the wrappers, so every list in the file is tried and the one that yields the most links wins."""
    best: dict[str, list[str]] = {}
    preferred = data.get("saved_saved_collections") if isinstance(data, dict) else None
    candidates = ([preferred] if isinstance(preferred, list) else []) + list(_lists_of_dicts(data))
    for entries in candidates:
        got = _parse_entries(entries)
        score = (sum(len(v) for v in got.values()), len(got))
        if score > (sum(len(v) for v in best.values()), len(best)):
            best = got
    return best


def outline(node, depth: int = 0) -> str:
    """Field names of a JSON file without any of its values, to report an unknown layout safely."""
    if depth > 4:
        return "..."
    if isinstance(node, dict):
        keys = list(node)[:6]
        inner = ", ".join(f"{k}: {outline(node[k], depth + 1)}" for k in keys)
        return "{" + inner + (", ..." if len(node) > 6 else "") + "}"
    if isinstance(node, list):
        return f"[{len(node)} x {outline(node[0], depth + 1)}]" if node else "[]"
    if isinstance(node, str):
        return "link" if node.startswith("http") else "text"
    return type(node).__name__


MAX_EXPORT_FILE = 150 * 2**20  # a very large saved list is a few MB; more than this is not an Instagram export
EXPORT_FILES = ("saved_collections.json", "saved_posts.json", "saved_collections.html", "saved_posts.html")


def export_file_name(name: str, text: str) -> str | None:
    """Which export file this is (one of EXPORT_FILES), from its name or, if renamed, from its content."""
    low = (name or "").lower()
    known = next((f for f in EXPORT_FILES if low.endswith(f)), None)
    if known:
        return known
    try:
        data = json.loads(text)
    except ValueError:
        return None
    keys = set(data) if isinstance(data, dict) else set()
    if keys & {"saved_saved_collections", "saved_collections"}:
        return "saved_collections.json"
    if keys & {"saved_saved_media", "saved_posts"}:
        return "saved_posts.json"
    return None


def _gather(path: Path) -> dict[str, str]:
    """The export files found in a .zip, an unzipped folder, or a single file: {canonical name: text}."""
    import zipfile
    path = Path(path).expanduser()
    files: dict[str, str] = {}
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                base = n.rsplit("/", 1)[-1].lower()
                if base in EXPORT_FILES:
                    with z.open(n) as f:  # read at most the limit: a small zip can expand to gigabytes
                        data = f.read(MAX_EXPORT_FILE + 1)
                    if len(data) > MAX_EXPORT_FILE:
                        raise ValueError(f"{base} is larger than {MAX_EXPORT_FILE // 2**20} MB")
                    files[base] = data.decode("utf-8", errors="replace")
    elif path.is_dir():
        for p in path.rglob("*"):
            if p.name.lower() in EXPORT_FILES:
                files[p.name.lower()] = p.read_text(encoding="utf-8", errors="replace")
    elif path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        files[export_file_name(path.name, text) or path.name.lower()] = text
    return {k: v.lstrip("\ufeff") for k, v in files.items()}


def describe(path: Path) -> str:
    """Field-name outline of each export file, for an error message when nothing could be read."""
    parts = []
    for name, text in _gather(path).items():
        try:
            parts.append(f"{name}: {outline(json.loads(text))}")
        except ValueError:
            parts.append(f"{name}: not JSON")
    return "; ".join(parts)


def read_export(path: Path) -> dict[str, list[str]]:
    """Instagram export (the .zip, the unzipped folder, or the JSON files) -> {collection: [urls]}.
    Saved posts that are in no collection go to UNSORTED. Every URL appears once per collection."""
    files = _gather(path)
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
    # a reel imported earlier as Unsorted (saved_posts.json alone) moves out once its collection is known
    named = [f"reel:{media.id_from_url(u)[3:]}" for n, urls in cols.items() if n != UNSORTED for u in urls]
    for i in range(0, len(named), 500):
        part = named[i:i + 500]
        lib.x(f"DELETE FROM item_collections WHERE collection=? AND item_id IN (SELECT id FROM items WHERE key IN ({','.join('?' * len(part))}))",
              (UNSORTED, *part))
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
