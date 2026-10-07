"""Full details for a title, gathered from several free sources and cross-checked.

anime / manga : AniList (synopsis, status, studio or author, episodes/chapters, score, official streaming and
                reading links, related works) + MyAnimeList via Jikan (second opinion: MAL score, rank, title)
series        : Wikidata (year, language, cast, IMDb) + TVmaze (status, network, rating, summary) + Wikipedia summary
movie / book  : Wikidata (director, cast, language, IMDb, runtime) + Wikipedia summary
optional      : TMDB (free key) adds a poster and the streaming services in your country
"""
from __future__ import annotations

import time

from . import lookups


def enrich(title: dict, region: str = "IN") -> dict:
    """title: a titles row (ext_key, name, type, year, extra). Returns fields to merge into extra.
    Each source is optional: if one fails or is rate limited, the others still fill in."""
    ext, kind, name, year = title["ext_key"], title.get("type") or "", title["name"], title.get("year")
    extra = dict(title.get("extra") or {})
    out: dict = {"checked_at": int(time.time()), "sources": []}

    def safe(fn, *a):
        try:
            return fn(*a) or {}
        except (lookups.ServiceError, lookups.RateLimited, lookups.QuotaExceeded, OSError, ValueError, KeyError):
            return {}

    if ext.startswith("anilist:"):
        d = safe(lookups.anilist_details, int(ext.split(":")[1]))
        if d:
            out.update(d)
            out["sources"].append("AniList")
        mal = d.get("mal_id") or extra.get("mal_id")
        if mal:
            j = safe(lookups.jikan_check, mal, "manga" if kind == "manga" else "anime")
            if j:
                out.update(j)
                out["sources"].append("MyAnimeList")
                # cross-check: both databases should agree on the title
                if j.get("mal_title") and max(lookups.similarity(j["mal_title"], n) for n in [name, d.get("native_title") or name]) < 0.6:
                    out["cross_check"] = f"MyAnimeList calls it '{j['mal_title']}'"
    elif ext.startswith(("wikidata:", "web:")):
        wp_title = extra.get("wikipedia_title")
        if wp_title:
            w = safe(lookups.wikipedia_summary, wp_title)
            if w:
                out.update(w)
                out["sources"].append("Wikipedia")
        if kind == "series":
            tv = safe(lookups.tvmaze, name, year)
            if tv:
                if not out.get("synopsis") and tv.get("tv_synopsis"):
                    out["synopsis"] = tv["tv_synopsis"]
                tv.pop("tv_synopsis", None)
                out.update({k: v for k, v in tv.items() if k != "image" or not out.get("image")})
                out["sources"].append("TVmaze")
        if kind in ("movie", "series"):
            tm = safe(lookups.tmdb_watch, name, kind, year, region)
            if tm:
                out.update(tm)
                out["sources"].append("TMDB")
    return {k: v for k, v in out.items() if v not in (None, "", [], {})}


def cover_from(details: dict) -> str:
    return details.get("poster") or details.get("image") or ""
