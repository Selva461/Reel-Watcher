"""Real-world checks you can run on your own PC or phone (they use the live free services).

  reel-watcher selftest                      one request to each service; shows OK / problem and what came back
  reel-watcher selftest --image shot.jpg     also tries the screenshot search (uses 1 trace.moe + 1 SauceNAO search)
  reel-watcher lookup "Vikram Vedha" --type movie --year 2017 --lang ta
  reel-watcher lookup --image screenshot.jpg
Add --json to get output you can paste back for checking.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import details, lookups


def _try(name, fn):
    t0 = time.time()
    try:
        out = fn()
        return {"service": name, "ok": True, "seconds": round(time.time() - t0, 1), "result": out}
    except Exception as e:  # noqa: BLE001  report every failure, keep going
        return {"service": name, "ok": False, "seconds": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {e}"[:300]}


def _brief(hit: dict | None) -> dict | None:
    if not hit:
        return None
    return {k: hit.get(k) for k in ("ext_key", "name", "type", "year", "language", "genres", "score", "ambiguous", "alternatives") if k in hit}


def selftest(image: str | None = None) -> list[dict]:
    rows = []
    fr = {}

    def anilist_search():
        r = lookups.anilist("Frieren", media_type="ANIME")
        fr["hit"] = r[0] if r else None
        return _brief(fr["hit"])
    rows.append(_try("AniList search (Frieren)", anilist_search))
    if fr.get("hit"):
        aid = int(fr["hit"]["ext_key"].split(":")[1])
        rows.append(_try("AniList details", lambda: {k: v for k, v in lookups.anilist_details(aid).items() if k in ("status", "studios", "episodes", "score", "where_to_watch", "mal_id")}))
        mal = fr["hit"]["extra"].get("mal_id")
        if mal:
            rows.append(_try("MyAnimeList via Jikan", lambda: lookups.jikan_check(mal)))
    rows.append(_try("Wikidata movie (Parasite 2019)", lambda: _brief(lookups.resolve_name("Parasite", "movie", year=2019))))
    rows.append(_try("Wikidata Tamil search (Vikram Vedha)", lambda: _brief(lookups.resolve_name("Vikram Vedha", "movie", year=2017, language="ta"))))
    rows.append(_try("Wikipedia summary", lambda: {k: (v[:120] if isinstance(v, str) else v) for k, v in lookups.wikipedia_summary("Parasite (2019 film)").items()}))
    rows.append(_try("TVmaze series (Dark 2017)", lambda: {k: v for k, v in lookups.tvmaze("Dark", 2017).items() if k in ("status", "network", "premiered", "tvmaze_rating")}))
    rows.append(_try("trace.moe monthly budget", lookups.trace_me))
    if lookups.os.environ.get("TMDB_API_KEY"):
        rows.append(_try("TMDB where to watch (India)", lambda: lookups.tmdb_watch("Parasite", "movie", 2019, "IN")))
    if image:
        data = Path(image).read_bytes()
        rows.append(_try("trace.moe screenshot search", lambda: lookups.trace_moe(data)))
        rows.append(_try("SauceNAO screenshot search", lambda: lookups.saucenao(data)))
    return rows


def lookup(name: str | None, kind: str = "", year: int | None = None, lang: str | None = None, image: str | None = None,
           region: str = "IN") -> dict:
    out: dict = {}
    if image:
        data = Path(image).read_bytes()
        out["trace.moe"] = _try("trace.moe", lambda: lookups.trace_moe(data))
        out["saucenao"] = _try("saucenao", lambda: lookups.saucenao(data))
        if not name:
            for key in ("trace.moe", "saucenao"):
                r = out[key].get("result")
                if out[key]["ok"] and r and r.get("score", 0) >= (0.9 if key == "trace.moe" else 0.8):
                    name, kind = r["name"], kind or r.get("kind") or "anime"
                    break
    if name:
        hit = lookups.resolve_name(name, kind, year=year, language=lang)
        out["match"] = _brief(hit)
        if hit:
            t = {"ext_key": hit["ext_key"], "name": hit["name"], "type": hit["type"], "year": hit.get("year"), "extra": hit.get("extra") or {}}
            out["details"] = details.enrich(t, region)
    return out


def _print_rows(rows: list[dict]) -> None:
    for r in rows:
        mark = "OK  " if r["ok"] else "FAIL"
        print(f"[{mark}] {r['service']}  ({r['seconds']}s)")
        print("       " + json.dumps(r.get("result") if r["ok"] else r.get("error"), ensure_ascii=False)[:400])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "selftest"
    ap = argparse.ArgumentParser(prog=f"reel-watcher {cmd}", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if cmd == "lookup":
        ap.add_argument("name", nargs="?")
        ap.add_argument("--type", default="", choices=["", "anime", "manga", "movie", "series", "book", "game"])
        ap.add_argument("--year", type=int)
        ap.add_argument("--lang", help="language code of the reel, e.g. ta, hi, ko, ja")
        ap.add_argument("--region", default="IN")
    ap.add_argument("--image", help="a screenshot to search")
    ap.add_argument("--json", action="store_true", help="machine-readable output to paste back")
    a = ap.parse_args(argv)
    if cmd == "lookup":
        if not a.name and not a.image:
            ap.error("give a name or --image")
        res = lookup(a.name, a.type, a.year, a.lang, a.image, a.region)
        print(json.dumps(res, ensure_ascii=False, indent=None if a.json else 2))
        return 0 if res.get("match") or not a.name else 1
    rows = selftest(a.image)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        _print_rows(rows)
        bad = [r["service"] for r in rows if not r["ok"]]
        print("\nAll services reachable." if not bad else f"\nProblems with: {', '.join(bad)}")
    return 0 if all(r["ok"] for r in rows) else 1
