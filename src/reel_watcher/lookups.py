"""Free online lookups. No accounts, no API keys required, no payment.

- AniList (graphql.anilist.co): anime and manga names, years, genres, country -> language, covers.
- Wikidata (www.wikidata.org): movies, TV series, books, games: year, original language, genres.
- trace.moe (api.trace.moe): find the anime, episode and timestamp of a screenshot. Free tier has a limit.
- SauceNAO (saucenao.com): find the manga or artwork of an image. Free tier has a daily limit;
  an optional free API key (SAUCENAO_API_KEY) raises it.

Every network call goes through `http` so tests can fake it. A `QuotaExceeded` error means the
service's free limit is used up for now; the caller retries the item later.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

UA = "ReelShelf/0.2 (personal use; https://github.com/selva461/Reel-Watcher)"
ANILIST = "https://graphql.anilist.co"
WIKIDATA = "https://www.wikidata.org/w/api.php"
TRACE = "https://api.trace.moe/search"
SAUCE = "https://saucenao.com/search.php"

# Conservative daily caps so a big folder never burns a month's free allowance in one night.
DAILY_LIMITS = {
    "trace": int(os.environ.get("REEL_SHELF_TRACE_DAILY", "30")),
    "sauce": int(os.environ.get("REEL_SHELF_SAUCE_DAILY", "90")),
}


class QuotaExceeded(Exception):
    pass


class ServiceError(Exception):
    pass


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 30):
    """Returns (status, parsed JSON or None). Raises QuotaExceeded on 402/429."""
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        if e.code in (402, 429):
            raise QuotaExceeded(f"{urllib.parse.urlparse(url).hostname}: HTTP {e.code}") from e
        raise ServiceError(f"{urllib.parse.urlparse(url).hostname}: HTTP {e.code}") from e


def _multipart(field: str, filename: str, data: bytes, ctype: str = "image/jpeg") -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def norm(s: str) -> str:
    s = (s or "").lower().replace("&", "and")
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    # "Frieren" vs "Frieren: Beyond Journey's End": a clear prefix of the official title counts as strong
    if len(na) >= 5 and (nb.startswith(na) or na.startswith(nb)):
        r = max(r, 0.9)
    return r


# ---------------------------------------------------------------- AniList

COUNTRY_LANG = {"JP": "Japanese", "KR": "Korean", "CN": "Chinese", "TW": "Chinese"}
ANILIST_Q = """query ($s: String, $id: Int, $t: MediaType) { Page(perPage: 6) { media(search: $s, id: $id, type: $t, sort: SEARCH_MATCH) {
  id type format title { romaji english native } synonyms startDate { year } episodes chapters genres countryOfOrigin
  coverImage { medium } siteUrl } } }"""


def _anilist_media(m: dict) -> dict:
    t = m.get("title") or {}
    fmt = m.get("format") or ""
    kind = "manga" if m.get("type") == "MANGA" and fmt not in ("NOVEL",) else "book" if fmt == "NOVEL" else "anime"
    return {
        "ext_key": f"anilist:{m['id']}", "name": t.get("english") or t.get("romaji") or t.get("native") or "",
        "names": [x for x in (t.get("english"), t.get("romaji"), t.get("native"), *(m.get("synonyms") or [])) if x],
        "type": kind, "year": (m.get("startDate") or {}).get("year"),
        "language": COUNTRY_LANG.get(m.get("countryOfOrigin") or "", ""), "genres": m.get("genres") or [],
        "cover": (m.get("coverImage") or {}).get("medium") or "",
        "extra": {k: v for k, v in (("format", fmt), ("episodes", m.get("episodes")), ("chapters", m.get("chapters")),
                                     ("url", m.get("siteUrl"))) if v},
    }


def anilist(search: str | None = None, id_: int | None = None, media_type: str | None = None) -> list[dict]:
    variables = {k: v for k, v in (("s", search), ("id", id_), ("t", media_type)) if v is not None}
    _, j = http("POST", ANILIST, json.dumps({"query": ANILIST_Q, "variables": variables}).encode(),
                {"Content-Type": "application/json", "Accept": "application/json"})
    media = (((j or {}).get("data") or {}).get("Page") or {}).get("media") or []
    return [_anilist_media(m) for m in media]


# ---------------------------------------------------------------- Wikidata

WD_TYPES = {
    "Q11424": "movie", "Q202866": "movie", "Q24869": "movie", "Q506240": "movie", "Q29168811": "movie",
    "Q5398426": "series", "Q1259759": "series", "Q526877": "series", "Q117467246": "series", "Q21191270": "series",
    "Q63952888": "anime", "Q1107": "anime", "Q20650540": "anime",
    "Q21198342": "manga", "Q8274": "manga", "Q74262765": "manga",
    "Q7725634": "book", "Q571": "book", "Q8261": "book", "Q47461344": "book",
    "Q7889": "game",
}


def _claim_ids(ent: dict, prop: str) -> list[str]:
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def _claim_year(ent: dict, *props: str) -> int | None:
    years = []
    for p in props:
        for c in (ent.get("claims") or {}).get(p, []):
            v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(v, dict) and isinstance(v.get("time"), str):
                m = re.match(r"[+-](\d{4})", v["time"])
                if m:
                    years.append(int(m.group(1)))
    return min(years) if years else None


def wikidata(search: str, limit: int = 6) -> list[dict]:
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": search, "language": "en", "uselang": "en",
                                "type": "item", "limit": limit, "format": "json"})
    _, j = http("GET", f"{WIKIDATA}?{q}")
    ids = [r["id"] for r in (j or {}).get("search", []) if r.get("id")]
    if not ids:
        return []
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|aliases",
                                "languages": "en", "format": "json"})
    _, ents = http("GET", f"{WIKIDATA}?{q}")
    ents = (ents or {}).get("entities", {})
    out, need = [], set()
    for qid in ids:
        e = ents.get(qid) or {}
        kinds = [WD_TYPES[t] for t in _claim_ids(e, "P31") if t in WD_TYPES]
        if not kinds:
            continue
        langs, genres = _claim_ids(e, "P364")[:1], _claim_ids(e, "P136")[:4]
        need.update(langs + genres)
        label = ((e.get("labels") or {}).get("en") or {}).get("value") or qid
        aliases = [a.get("value") for a in (e.get("aliases") or {}).get("en", []) if a.get("value")]
        out.append({"ext_key": f"wikidata:{qid}", "name": label, "names": [label, *aliases], "type": kinds[0],
                    "year": _claim_year(e, "P577", "P580"), "_lang": langs, "_genres": genres, "language": "", "genres": [],
                    "cover": "", "extra": {"url": f"https://www.wikidata.org/wiki/{qid}"}})
    if need:
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(sorted(need)[:50]), "props": "labels",
                                    "languages": "en", "format": "json"})
        _, lab = http("GET", f"{WIKIDATA}?{q}")
        names = {k: ((v.get("labels") or {}).get("en") or {}).get("value", "") for k, v in ((lab or {}).get("entities") or {}).items()}
        for o in out:
            o["language"] = next((names.get(x, "").replace(" language", "").capitalize() for x in o["_lang"] if names.get(x)), "")
            o["genres"] = [names[g] for g in o["_genres"] if names.get(g)]
    for o in out:
        o.pop("_lang", None)
        o.pop("_genres", None)
    return out


# ---------------------------------------------------------------- name -> best database entry

KIND_SOURCES = {
    "anime": ("anilist_anime",), "manga": ("anilist_manga",), "book": ("wikidata", "anilist_manga"),
    "movie": ("wikidata",), "series": ("wikidata",), "game": ("wikidata",),
}


def resolve_name(name: str, kind_hint: str = "", min_score: float = 0.82) -> dict | None:
    """Best database entry for a name, or None. kind_hint ('anime', 'movie', ...) picks which databases to ask;
    without one, AniList anime, AniList manga and Wikidata are all tried."""
    order = KIND_SOURCES.get(kind_hint, ("anilist_anime", "wikidata", "anilist_manga"))
    best, best_s = None, 0.0
    for src in order:
        try:
            cands = (anilist(name, media_type="ANIME") if src == "anilist_anime" else
                     anilist(name, media_type="MANGA") if src == "anilist_manga" else wikidata(name))
        except ServiceError:
            continue
        for c in cands:
            s = max((similarity(name, n) for n in c.get("names") or [c["name"]]), default=0.0)
            if kind_hint and c["type"] == kind_hint:
                s += 0.02
            if s > best_s:
                best, best_s = c, s
        if best_s >= 0.97:
            break
    if best and best_s >= min_score:
        return {**best, "score": round(min(best_s, 1.0), 3)}
    return None


# ---------------------------------------------------------------- scene search (screenshots)

def trace_moe(image: bytes) -> dict | None:
    """Anime scene search. Returns {ext_key, name, names, episode, at_s, score} or None."""
    body, ctype = _multipart("image", "frame.jpg", image)
    _, j = http("POST", f"{TRACE}?anilistInfo&cutBorders", body, {"Content-Type": ctype}, timeout=60)
    if (j or {}).get("error"):
        if re.search(r"quota|limit|concurren", j["error"], re.I):
            raise QuotaExceeded("trace.moe: " + j["error"])
        raise ServiceError("trace.moe: " + j["error"])
    res = (j or {}).get("result") or []
    if not res:
        return None
    r = res[0]
    al = r.get("anilist") if isinstance(r.get("anilist"), dict) else {"id": r.get("anilist")}
    t = al.get("title") or {}
    return {"ext_key": f"anilist:{al.get('id')}", "anilist_id": al.get("id"),
            "name": t.get("english") or t.get("romaji") or t.get("native") or "",
            "names": [x for x in (t.get("english"), t.get("romaji"), t.get("native")) if x],
            "episode": r.get("episode"), "at_s": r.get("from"), "score": float(r.get("similarity") or 0)}


def saucenao(image: bytes) -> dict | None:
    """Manga / artwork search. Returns {name, part, score, source_url} or None."""
    params = {"output_type": 2, "numres": 5, "db": 999}
    key = os.environ.get("SAUCENAO_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    body, ctype = _multipart("file", "frame.jpg", image)
    _, j = http("POST", f"{SAUCE}?{urllib.parse.urlencode(params)}", body, {"Content-Type": ctype}, timeout=60)
    hdr = (j or {}).get("header") or {}
    if str(hdr.get("status", "0")) not in ("0",) and re.search(r"limit|exceed", str(hdr.get("message", "")), re.I):
        raise QuotaExceeded("saucenao: " + str(hdr.get("message"))[:120])
    best = None
    for r in (j or {}).get("results") or []:
        h, d = r.get("header") or {}, r.get("data") or {}
        name = d.get("source") or d.get("eng_name") or d.get("title") or d.get("jp_name") or ""
        if not name or name.startswith("http"):
            continue
        s = float(h.get("similarity") or 0) / 100.0
        if not best or s > best["score"]:
            best = {"name": name, "part": d.get("part") or "", "score": s, "source_url": (d.get("ext_urls") or [""])[0]}
    return best
