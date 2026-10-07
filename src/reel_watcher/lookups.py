"""Free online lookups. No payment; no account needed (two optional free keys raise limits).

Sources and their real free limits (from each service's documentation, October 2026):
- AniList (graphql.anilist.co): anime and manga. 90 requests/minute normally, 30/minute while degraded;
  going over gives a one-minute timeout. Paced here at 25/minute.
- Jikan (api.jikan.moe/v4): MyAnimeList data, used to cross-check AniList. 3/second, 60/minute.
- Wikidata (www.wikidata.org): movies, series, books, games: year, original language, genres, director, cast, IMDb id.
- Wikipedia REST summary (en.wikipedia.org): one-paragraph synopsis and image for movies and series.
- TVmaze (api.tvmaze.com): TV series status, network, seasons, rating, summary. 20 calls per 10 seconds.
- trace.moe (api.trace.moe): anime scene search for screenshots. Anonymous: 100 searches per MONTH, one at a time
  (HTTP 402 = monthly quota used up, 429 = another search still running).
- SauceNAO (saucenao.com): manga panels, and also movie/show frames (IMDb indexes). Anonymous: 4 searches per
  30 seconds; a free account key (SAUCENAO_API_KEY) allows about 200 a day.
- TMDB (optional, TMDB_API_KEY, free for personal use): posters and "where to watch" per country.
- Web search (no key): DuckDuckGo's HTML page, then Bing, then Wikipedia's own search. Result titles from
  Wikipedia, IMDb, MyAnimeList, AniList, Letterboxd, Rotten Tomatoes, TMDB and MyDramaList name the work, so new
  or regional titles that the databases do not have yet are still found. Paced to one search every few seconds.

Every network call goes through `http`, so tests fake it. QuotaExceeded = a free limit is used up for now
(the caller retries the item later); RateLimited = slow down and try again in a moment (handled here).
"""
from __future__ import annotations

import difflib
import html
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

UA = "ReelShelf/0.3 (personal use; https://github.com/Selva461/Reel-Watcher)"
ANILIST = "https://graphql.anilist.co"
JIKAN = "https://api.jikan.moe/v4"
WIKIDATA = "https://www.wikidata.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/api/rest_v1/page/summary/"
TVMAZE = "https://api.tvmaze.com"
TRACE = "https://api.trace.moe/search"
TRACE_ME = "https://api.trace.moe/me"
SAUCE = "https://saucenao.com/search.php"
TMDB = "https://api.themoviedb.org/3"

DAILY_LIMITS = {
    # trace.moe's budget is monthly; the worker spreads what is left over the remaining days (see trace_daily_cap)
    "trace": int(os.environ.get("REEL_SHELF_TRACE_DAILY", "0")),
    "sauce": int(os.environ.get("REEL_SHELF_SAUCE_DAILY", "190" if os.environ.get("SAUCENAO_API_KEY") else "60")),
}
# requests per window (seconds) per host, kept under each service's published limit
RATES = {"graphql.anilist.co": (25, 60), "api.jikan.moe": (50, 60), "api.tvmaze.com": (18, 10), "saucenao.com": (4, 31),
         "www.wikidata.org": (30, 10), "en.wikipedia.org": (30, 10), "api.trace.moe": (1, 3), "api.themoviedb.org": (30, 10),
         "html.duckduckgo.com": (1, 4), "www.bing.com": (1, 3)}


class QuotaExceeded(Exception):
    pass


class RateLimited(Exception):
    pass


class ServiceError(Exception):
    pass


class _Pacer:
    """Sliding-window limiter per host, shared by all threads."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.calls: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.clock, self.sleep = clock, sleep

    def wait(self, host: str) -> None:
        n, window = RATES.get(host, (20, 10))
        while True:
            with self.lock:
                now = self.clock()
                q = [t for t in self.calls.get(host, []) if now - t < window]
                if len(q) < n:
                    q.append(now)
                    self.calls[host] = q
                    return
                delay = window - (now - q[0]) + 0.05
                self.calls[host] = q
            self.sleep(delay)


PACER = _Pacer()


def _raw_http(method, url, body, headers, timeout):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(raw) if raw.strip() else None), {}
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8", errors="replace") or "null")
        except ValueError:
            payload = None
        return e.code, payload, dict(e.headers or {})


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 30):
    """Paced request with polite retries. Returns (status, parsed JSON or None) for 2xx and 404.
    Raises QuotaExceeded (free quota used up), ServiceError (other failures)."""
    host = urllib.parse.urlparse(url).hostname or ""
    for attempt in range(3):
        PACER.wait(host)
        try:
            status, data, hdrs = _raw_http(method, url, body, headers, timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt == 2:
                raise ServiceError(f"{host}: {e}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if status < 300 or status == 404:
            return status, data
        if host == "api.trace.moe" and status == 402:
            raise QuotaExceeded("trace.moe: monthly free searches used up")
        if status == 429 or status == 503:
            wait = float(hdrs.get("Retry-After") or hdrs.get("retry-after") or (61 if host == "graphql.anilist.co" else 5))
            if attempt < 2:
                time.sleep(min(wait, 65))
                continue
            raise RateLimited(f"{host}: HTTP {status}")
        raise ServiceError(f"{host}: HTTP {status}")
    raise ServiceError(f"{host}: no answer")


def _multipart(field: str, filename: str, data: bytes, ctype: str = "image/jpeg") -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def norm(s: str) -> str:
    s = (s or "").lower().replace("&", "and")
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return re.sub(r"[^a-z0-9\u0080-￿]+", "", s)


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


def clean_html(s: str | None, limit: int = 1200) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    s = re.sub(r"\(Source: [^)]*\)\s*$", "", s).strip()
    return s[:limit]


# ---------------------------------------------------------------- AniList

COUNTRY_LANG = {"JP": "Japanese", "KR": "Korean", "CN": "Chinese", "TW": "Chinese"}
ANILIST_Q = """query ($s: String, $id: Int, $t: MediaType) { Page(perPage: 6) { media(search: $s, id: $id, type: $t, sort: SEARCH_MATCH) {
  id idMal type format isAdult popularity title { romaji english native } synonyms startDate { year } episodes chapters genres
  countryOfOrigin coverImage { large medium } siteUrl } } }"""
ANILIST_DETAIL_Q = """query ($id: Int) { Media(id: $id) {
  id idMal type format status description(asHtml: false) source season seasonYear episodes duration chapters volumes averageScore
  popularity genres isAdult countryOfOrigin title { romaji english native } synonyms startDate { year month day } endDate { year }
  coverImage { large } bannerImage siteUrl nextAiringEpisode { episode airingAt }
  studios(isMain: true) { nodes { name } }
  staff(perPage: 6, sort: RELEVANCE) { edges { role node { name { full } } } }
  externalLinks { site url type language }
  relations { edges { relationType(version: 2) node { id type format title { english romaji } startDate { year } } } } } }"""


def _anilist_media(m: dict) -> dict:
    t = m.get("title") or {}
    fmt = m.get("format") or ""
    kind = "book" if fmt == "NOVEL" else "manga" if m.get("type") == "MANGA" else "anime"
    return {
        "ext_key": f"anilist:{m['id']}", "name": t.get("english") or t.get("romaji") or t.get("native") or "",
        "names": [x for x in (t.get("english"), t.get("romaji"), t.get("native"), *(m.get("synonyms") or [])) if x],
        "type": kind, "year": (m.get("startDate") or {}).get("year"),
        "language": COUNTRY_LANG.get(m.get("countryOfOrigin") or "", ""), "genres": m.get("genres") or [],
        "cover": (m.get("coverImage") or {}).get("large") or (m.get("coverImage") or {}).get("medium") or "",
        "popularity": m.get("popularity") or 0, "adult": bool(m.get("isAdult")),
        "extra": {k: v for k, v in (("format", fmt), ("episodes", m.get("episodes")), ("chapters", m.get("chapters")),
                                     ("url", m.get("siteUrl")), ("mal_id", m.get("idMal"))) if v},
    }


def anilist(search: str | None = None, id_: int | None = None, media_type: str | None = None) -> list[dict]:
    variables = {k: v for k, v in (("s", search), ("id", id_), ("t", media_type)) if v is not None}
    _, j = http("POST", ANILIST, json.dumps({"query": ANILIST_Q, "variables": variables}).encode(), {"Content-Type": "application/json"})
    media = (((j or {}).get("data") or {}).get("Page") or {}).get("media") or []
    return [_anilist_media(m) for m in media if not m.get("isAdult")]


STREAM_SITES = {"Crunchyroll", "Netflix", "Amazon Prime Video", "Hulu", "HIDIVE", "Disney Plus", "Bilibili TV", "YouTube",
                "Muse Asia", "Ani-One Asia", "MANGA Plus", "VIZ", "Comikey", "K MANGA", "Webtoon", "Tapas", "Manta"}


def anilist_details(anilist_id: int) -> dict:
    """Everything worth showing for one anime/manga: synopsis, status, studio or author, episodes/chapters,
    score, official streaming/reading links, related works (sequels, the manga of an anime, ...)."""
    _, j = http("POST", ANILIST, json.dumps({"query": ANILIST_DETAIL_Q, "variables": {"id": int(anilist_id)}}).encode(),
                {"Content-Type": "application/json"})
    m = ((j or {}).get("data") or {}).get("Media") or {}
    if not m:
        return {}
    staff = [{"name": ((e.get("node") or {}).get("name") or {}).get("full"), "role": e.get("role")} for e in ((m.get("staff") or {}).get("edges") or [])]
    authors = [s["name"] for s in staff if s["name"] and re.search(r"story|original creator|art", s["role"] or "", re.I)]
    rel = []
    for e in ((m.get("relations") or {}).get("edges") or []):
        n = e.get("node") or {}
        if e.get("relationType") in ("ADAPTATION", "SOURCE", "SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE", "SPIN_OFF"):
            t = n.get("title") or {}
            rel.append({"relation": e["relationType"].replace("_", " ").title(), "name": t.get("english") or t.get("romaji"),
                        "type": "anime" if n.get("type") == "ANIME" else "manga", "format": n.get("format"),
                        "year": (n.get("startDate") or {}).get("year"), "ext_key": f"anilist:{n.get('id')}"})
    links = [{"site": x.get("site"), "url": x.get("url"), "language": x.get("language")} for x in m.get("externalLinks") or []
             if x.get("url") and (x.get("type") == "STREAMING" or x.get("site") in STREAM_SITES)]
    nxt = m.get("nextAiringEpisode") or {}
    return {k: v for k, v in {
        "synopsis": clean_html(m.get("description")), "status": (m.get("status") or "").replace("_", " ").title(),
        "format": m.get("format"), "source": (m.get("source") or "").replace("_", " ").title(),
        "season": f"{(m.get('season') or '').title()} {m.get('seasonYear') or ''}".strip(),
        "episodes": m.get("episodes"), "duration_min": m.get("duration"), "chapters": m.get("chapters"), "volumes": m.get("volumes"),
        "score": m.get("averageScore"), "studios": [n.get("name") for n in ((m.get("studios") or {}).get("nodes") or []) if n.get("name")],
        "authors": authors[:3], "where_to_watch": links[:8], "related": rel[:10],
        "next_episode": {"episode": nxt.get("episode"), "at": nxt.get("airingAt")} if nxt else None,
        "end_year": (m.get("endDate") or {}).get("year"), "mal_id": m.get("idMal"), "url": m.get("siteUrl"),
        "banner": m.get("bannerImage"), "native_title": (m.get("title") or {}).get("native"),
    }.items() if v not in (None, "", [], {})}


def jikan_check(mal_id: int, media_type: str = "anime") -> dict:
    """MyAnimeList cross-check (score, rank, members, official English title)."""
    st, j = http("GET", f"{JIKAN}/{'manga' if media_type == 'manga' else 'anime'}/{int(mal_id)}")
    d = (j or {}).get("data") or {}
    if st == 404 or not d:
        return {}
    return {k: v for k, v in {"mal_score": d.get("score"), "mal_rank": d.get("rank"), "mal_members": d.get("members"),
                              "mal_title": d.get("title_english") or d.get("title"), "mal_url": d.get("url")}.items() if v}


# ---------------------------------------------------------------- Wikidata / Wikipedia / TVmaze / TMDB

WD_TYPES = {
    "Q11424": "movie", "Q202866": "movie", "Q24869": "movie", "Q506240": "movie", "Q29168811": "movie", "Q229390": "movie",
    "Q5398426": "series", "Q1259759": "series", "Q526877": "series", "Q117467246": "series", "Q21191270": "series", "Q3464665": "series",
    "Q63952888": "anime", "Q1107": "anime", "Q20650540": "anime",
    "Q21198342": "manga", "Q8274": "manga", "Q74262765": "manga",
    "Q7725634": "book", "Q571": "book", "Q8261": "book", "Q47461344": "book", "Q1667921": "book",
    "Q7889": "game",
}


def _claims(ent: dict, prop: str) -> list:
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if v is not None:
            out.append(v)
    return out


def _claim_ids(ent: dict, prop: str) -> list[str]:
    return [v["id"] for v in _claims(ent, prop) if isinstance(v, dict) and v.get("id")]


def _claim_year(ent: dict, *props: str) -> int | None:
    years = []
    for p in props:
        for v in _claims(ent, p):
            if isinstance(v, dict) and isinstance(v.get("time"), str):
                m = re.match(r"[+-](\d{4})", v["time"])
                if m:
                    years.append(int(m.group(1)))
    return min(years) if years else None


def _labels(ids: set[str]) -> dict[str, str]:
    out = {}
    ids = sorted(i for i in ids if i)
    for k in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids[k:k + 50]), "props": "labels",
                                    "languages": "en", "format": "json"})
        _, lab = http("GET", f"{WIKIDATA}?{q}")
        for qid, v in ((lab or {}).get("entities") or {}).items():
            out[qid] = ((v.get("labels") or {}).get("en") or {}).get("value", "")
    return out


def wikidata(search: str, limit: int = 7, language: str = "en") -> list[dict]:
    """Search movies/series/books/games (also in the reel's language, e.g. 'ta' for Tamil titles)."""
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": search, "language": language, "uselang": "en",
                                "type": "item", "limit": limit, "format": "json"})
    _, j = http("GET", f"{WIKIDATA}?{q}")
    ids = [r["id"] for r in (j or {}).get("search", []) if r.get("id")]
    if not ids:
        return []
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|aliases|sitelinks",
                                "languages": "en|" + language if language != "en" else "en", "format": "json"})
    _, ents = http("GET", f"{WIKIDATA}?{q}")
    ents = (ents or {}).get("entities", {})
    out, need = [], set()
    for qid in ids:
        e = ents.get(qid) or {}
        kinds = [WD_TYPES[t] for t in _claim_ids(e, "P31") if t in WD_TYPES]
        if not kinds:
            continue
        refs = {"lang": _claim_ids(e, "P364")[:1], "genres": _claim_ids(e, "P136")[:4], "director": _claim_ids(e, "P57")[:2],
                "cast": _claim_ids(e, "P161")[:5], "country": _claim_ids(e, "P495")[:1], "author": _claim_ids(e, "P50")[:2]}
        for v in refs.values():
            need.update(v)
        labels = e.get("labels") or {}
        label = (labels.get("en") or labels.get(language) or {}).get("value") or qid
        aliases = [a.get("value") for lang in ("en", language) for a in (e.get("aliases") or {}).get(lang, []) if a.get("value")]
        native = (labels.get(language) or {}).get("value")
        sitelinks = e.get("sitelinks") or {}
        imdb = next((v for v in _claims(e, "P345") if isinstance(v, str)), None)
        dur = next((v.get("amount") for v in _claims(e, "P2047") if isinstance(v, dict)), None)
        extra = {"url": f"https://www.wikidata.org/wiki/{qid}", "imdb": f"https://www.imdb.com/title/{imdb}/" if imdb else None,
                 "wikipedia_title": (sitelinks.get("enwiki") or {}).get("title"),
                 "episodes": next((int(float(v["amount"])) for v in _claims(e, "P1113") if isinstance(v, dict)), None),
                 "seasons": next((int(float(v["amount"])) for v in _claims(e, "P2437") if isinstance(v, dict)), None),
                 "duration_min": int(float(dur)) if dur else None}
        out.append({"ext_key": f"wikidata:{qid}", "name": label, "names": [label, *aliases] + ([native] if native else []),
                    "type": kinds[0], "year": _claim_year(e, "P577", "P580"), "_refs": refs, "language": "", "genres": [], "cover": "",
                    "popularity": len(sitelinks), "adult": False, "extra": {k: v for k, v in extra.items() if v}})
    names = _labels(need) if need else {}
    for o in out:
        r = o.pop("_refs")
        o["language"] = next((names.get(x, "").replace(" language", "").capitalize() for x in r["lang"] if names.get(x)), "")
        o["genres"] = [re.sub(r" (film|television series|series|anime|manga)$", "", names[g]).capitalize() for g in r["genres"] if names.get(g)]
        for key in ("director", "cast", "country", "author"):
            vals = [names[x] for x in r[key] if names.get(x)]
            if vals:
                o["extra"][key] = vals
    return out


def wikipedia_summary(title: str) -> dict:
    st, j = http("GET", WIKIPEDIA + urllib.parse.quote(title.replace(" ", "_"), safe=""))
    if st == 404 or not j or j.get("type") == "disambiguation":
        return {}
    return {k: v for k, v in {"synopsis": (j.get("extract") or "")[:1200], "image": ((j.get("originalimage") or j.get("thumbnail") or {}).get("source")),
                              "wikipedia": ((j.get("content_urls") or {}).get("desktop") or {}).get("page")}.items() if v}


def tvmaze(name: str, year: int | None = None) -> dict:
    """Series details from TVmaze; only accepted when the premiere year matches (when known)."""
    st, s = http("GET", f"{TVMAZE}/singlesearch/shows?" + urllib.parse.urlencode({"q": name}))
    if st == 404 or not s:
        return {}
    prem = int(str(s.get("premiered") or "0")[:4] or 0)
    if year and prem and abs(prem - year) > 1:
        return {}
    if similarity(name, s.get("name") or "") < 0.8:
        return {}
    net = (s.get("network") or s.get("webChannel") or {})
    return {k: v for k, v in {"status": s.get("status"), "network": net.get("name"), "premiered": s.get("premiered"),
                              "ended": s.get("ended"), "tvmaze_rating": (s.get("rating") or {}).get("average"),
                              "tv_synopsis": clean_html(s.get("summary")), "official_site": s.get("officialSite"),
                              "tvmaze": s.get("url"), "image": (s.get("image") or {}).get("original"),
                              "runtime_min": s.get("runtime") or s.get("averageRuntime")}.items() if v}


def tmdb_watch(name: str, kind: str, year: int | None, region: str) -> dict:
    """Optional (free TMDB key): poster and streaming services for your country."""
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        return {}
    path = "movie" if kind == "movie" else "tv"
    q = {"api_key": key, "query": name}
    if year:
        q["year" if path == "movie" else "first_air_date_year"] = year
    _, s = http("GET", f"{TMDB}/search/{path}?{urllib.parse.urlencode(q)}")
    res = (s or {}).get("results") or []
    if not res:
        return {}
    r = res[0]
    _, w = http("GET", f"{TMDB}/{path}/{r['id']}/watch/providers?api_key={key}")
    reg = ((w or {}).get("results") or {}).get(region.upper()) or {}
    providers = [p.get("provider_name") for p in (reg.get("flatrate") or []) + (reg.get("free") or []) + (reg.get("ads") or []) if p.get("provider_name")]
    return {k: v for k, v in {"poster": f"https://image.tmdb.org/t/p/w342{r['poster_path']}" if r.get("poster_path") else None,
                              "tmdb_score": r.get("vote_average"), "streaming_in_region": providers[:8], "watch_page": reg.get("link"),
                              "region": region.upper()}.items() if v}


# ---------------------------------------------------------------- name -> best database entry

KIND_SOURCES = {
    "anime": ("anilist_anime",), "manga": ("anilist_manga",), "book": ("wikidata", "anilist_manga"),
    "movie": ("wikidata",), "series": ("wikidata",), "game": ("wikidata",),
}


def _score(name: str, c: dict, kind_hint: str, year: int | None) -> float:
    s = max((similarity(name, n) for n in c.get("names") or [c["name"]]), default=0.0)
    if kind_hint and c["type"] == kind_hint:
        s += 0.03
    elif kind_hint and c["type"] != kind_hint:
        s -= 0.05
    if year and c.get("year"):
        s += 0.06 if abs(c["year"] - year) <= 1 else -0.08
    pop = c.get("popularity") or 0
    scale = 400000 if c["ext_key"].startswith("anilist") else 120
    s += 0.05 * min(1.0, math.log1p(pop) / math.log1p(scale))  # well-known works win ties
    return s


def resolve_name(name: str, kind_hint: str = "", min_score: float = 0.82, year: int | None = None,
                 language: str | None = None) -> dict | None:
    """Best database entry for a name, with up to 3 alternatives. `ambiguous` is True when another work scores
    almost the same (the app then asks the user to pick). year / language (the reel's spoken language code,
    e.g. 'ta') help with titles that exist several times (Parasite 2019 vs others, Vikram Vedha 2017 vs 2022)."""
    order = KIND_SOURCES.get(kind_hint, ("anilist_anime", "wikidata", "anilist_manga"))
    cands: list[dict] = []
    for src in order:
        try:
            if src == "anilist_anime":
                cands += anilist(name, media_type="ANIME")
            elif src == "anilist_manga":
                cands += anilist(name, media_type="MANGA")
            else:
                cands += wikidata(name)
                if language and language not in ("en", None):
                    seen = {c["ext_key"] for c in cands}
                    cands += [c for c in wikidata(name, language=language) if c["ext_key"] not in seen]
        except (ServiceError, RateLimited):
            continue
        if any(_score(name, c, kind_hint, year) >= 1.02 for c in cands):
            break
    ranked = sorted(((_score(name, c, kind_hint, year), c) for c in cands), key=lambda x: -x[0])
    if not ranked or ranked[0][0] < min_score:
        return None
    best_s, best = ranked[0]
    alts = [{"ext_key": c["ext_key"], "name": c["name"], "type": c["type"], "year": c.get("year"), "language": c.get("language"),
             "score": round(s, 3)} for s, c in ranked[1:4] if s >= min_score - 0.1]
    ambiguous = bool(alts) and ranked[1][0] >= best_s - 0.03 and lookup_key(ranked[1][1]) != lookup_key(best)
    return {**best, "score": round(min(best_s, 1.0), 3), "alternatives": alts, "ambiguous": ambiguous}


def lookup_key(c: dict) -> str:
    return f"{norm(c['name'])}:{c.get('year')}:{c['type']}"


# ---------------------------------------------------------------- web search (no key)

BROWSER_UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
DDG = "https://html.duckduckgo.com/html/"
BING = "https://www.bing.com/search"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"


def fetch_html(url: str, data: dict | None = None, timeout: float = 20) -> str:
    """A web page as text (search engines). Raises ServiceError on any failure, RateLimited when told to slow down."""
    host = urllib.parse.urlparse(url).hostname or ""
    PACER.wait(host)
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                 headers={"User-Agent": BROWSER_UA, "Accept": "text/html", "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (429, 202, 403):
            raise RateLimited(f"{host}: HTTP {e.code}") from e
        raise ServiceError(f"{host}: HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ServiceError(f"{host}: {e}") from e


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag) or re.search(rf"\b{name}\s*=\s*'([^']*)'", tag)
    return html.unescape(m.group(1)) if m else ""


def _real_url(href: str) -> str:
    """Undo search-engine redirect links (DuckDuckGo uddg=, Bing u=a1<base64>)."""
    if href.startswith("//"):
        href = "https:" + href
    u = urllib.parse.urlparse(href)
    q = urllib.parse.parse_qs(u.query)
    if "uddg" in q:
        return q["uddg"][0]
    if (u.hostname or "").endswith("bing.com") and q.get("u", [""])[0].startswith("a1"):
        import base64
        raw = q["u"][0][2:]
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")
        except ValueError:
            return href
    return href


def parse_search_results(page: str) -> list[dict]:
    """[{title, url, snippet}] from a DuckDuckGo or Bing result page. Tolerant: any result-looking link is used."""
    out, seen = [], set()
    blocks = re.split(r'<div[^>]+class="[^"]*\bresult\b|<li[^>]+class="[^"]*\bb_algo\b', page)
    for b in blocks[1:]:
        m = re.search(r'(<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*>)(.*?)</a>', b, re.S) \
            or re.search(r"<h2[^>]*>\s*(<a\b[^>]*>)(.*?)</a>", b, re.S)
        if not m:
            continue
        url = _real_url(_attr(m.group(1), "href"))
        title = clean_html(m.group(2), 300)
        if not url.startswith("http") or not title or url in seen:
            continue
        seen.add(url)
        sm = re.search(r'class="[^"]*(?:result__snippet|b_caption)[^"]*"[^>]*>(.*?)</(?:a|div|p)>', b, re.S) or re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        out.append({"title": title, "url": url, "snippet": clean_html(sm.group(1), 400) if sm else ""})
    return out


def wikipedia_search(query: str, limit: int = 6) -> list[dict]:
    _, j = http("GET", WIKI_SEARCH + "?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json", "utf8": 1}))
    rows = ((j or {}).get("query") or {}).get("search") or []
    return [{"title": r["title"] + " - Wikipedia", "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(r["title"].replace(" ", "_")),
             "snippet": clean_html(r.get("snippet"), 300)} for r in rows if r.get("title")]


def web_search(query: str) -> tuple[list[dict], list[str]]:
    """Results from the first engine that answers, and a note per engine tried (shown when nothing works)."""
    notes = []
    for name, fn in (("DuckDuckGo", lambda: parse_search_results(fetch_html(DDG, {"q": query, "kl": "wt-wt"}))),
                     ("Bing", lambda: parse_search_results(fetch_html(BING + "?" + urllib.parse.urlencode({"q": query, "setlang": "en"})))),
                     ("Wikipedia", lambda: wikipedia_search(query))):
        try:
            res = fn()
        except (ServiceError, RateLimited) as e:
            notes.append(f"{name}: {e}")
            continue
        if res:
            return res, notes + [f"{name}: {len(res)} results"]
        notes.append(f"{name}: no results")
    return [], notes


TYPE_WORDS = [("series", r"tv series|tv mini.?series|mini.?series|web series|television series|tv show|series|serial|k-?drama|drama"),
              ("anime", r"anime|ona|ova"), ("manga", r"manga|manhwa|manhua|webtoon|comic"), ("game", r"video game|game"),
              ("book", r"novel|book"), ("movie", r"film|movie")]
SITES = [  # (site, url pattern, title suffix, weight)
    ("Wikipedia", r"^https?://[a-z]+\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)", r"\s+[-–\u2014]\s+Wikipedia$", 1.0),
    ("IMDb", r"imdb\.com/title/(tt\d+)", r"\s+[-–\u2014|]\s+IMDb.*$", 1.0),
    ("MyAnimeList", r"myanimelist\.net/(anime|manga)/(\d+)", r"\s+[-–\u2014|]\s+MyAnimeList(?:\.net)?$", 1.0),
    ("AniList", r"anilist\.co/(anime|manga)/(\d+)", r"\s+[-–\u2014·|]\s+AniList$", 1.0),
    ("Letterboxd", r"letterboxd\.com/film/([^/]+)", r"\s+[-–\u2014•|]\s+Letterboxd$|\s+directed by .*$", 0.85),
    ("Rotten Tomatoes", r"rottentomatoes\.com/(m|tv)/([^/?#]+)", r"\s+[-–\u2014|]\s+Rotten Tomatoes$", 0.85),
    ("TMDB", r"themoviedb\.org/(movie|tv)/(\d+)", r"\s+[-–\u2014|]\s+The Movie Database.*$", 0.85),
    ("MyDramaList", r"mydramalist\.com/(\d+)", r"\s+[-–\u2014|]\s+MyDramaList$", 0.85),
]
NOT_A_WORK = re.compile(r"^(?:list of|category:|template:|portal:|talk:|file:|user:|help:|wikipedia:)|\(disambiguation\)|"
                        r"\((?:actor|actress|singer|band|song|album|director|composer|politician|cricketer|footballer|character)\)", re.I)


def _kind_of(text: str) -> str:
    low = (text or "").lower()
    for kind, rx in TYPE_WORDS:
        if re.search(rf"\b(?:{rx})\b", low):
            return kind
    return ""


def split_title(t: str) -> tuple[str, int | None, str]:
    """'Scene (2026 film)' -> ('Scene', 2026, 'movie'); 'Dark (TV Series 2017–2020)' -> ('Dark', 2017, 'series')."""
    t = re.sub(r"\s+", " ", t or "").strip()
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", t)
    if not m:
        return t, None, ""
    inner = m.group(2)
    y = re.search(r"\b(19[0-9]\d|20[0-4]\d)\b", inner)
    kind = _kind_of(inner)
    if not y and not kind:
        return t, None, ""
    return m.group(1).strip(), int(y.group(1)) if y else None, kind


def result_work(r: dict) -> dict | None:
    """The work a search result is about, when the result is a title page on a known site."""
    for site, url_rx, suffix, weight in SITES:
        m = re.search(url_rx, r.get("url") or "")
        if not m:
            continue
        if site == "Wikipedia":
            page = urllib.parse.unquote(m.group(1)).replace("_", " ")
            if NOT_A_WORK.search(page):
                return None
            name, year, kind = split_title(page)
            wiki = page
        else:
            name, year, kind = split_title(re.sub(suffix, "", r.get("title") or "", flags=re.I).strip())
            wiki = None
            if site in ("MyAnimeList", "AniList"):
                kind = m.group(1)
            elif site == "IMDb" and year and not kind:
                kind = "movie"  # IMDb writes "(TV Series 2017-2020)" for shows and just "(2019)" for films
            elif site in ("Rotten Tomatoes", "TMDB"):
                kind = kind or ("series" if m.group(1) == "tv" else "movie")
        snippet_kind = _kind_of(r.get("snippet") or "")
        name = re.sub(r"\s+[-–\u2014|:]\s*$", "", name).strip()
        if not name or len(name) > 90:
            return None
        if not year:
            ys = re.search(r"\b(19[0-9]\d|20[0-4]\d)\b", r.get("snippet") or "")
            year = int(ys.group(1)) if ys and snippet_kind else None
        return {"name": name, "year": year, "type": kind or snippet_kind, "site": site, "url": r["url"], "weight": weight,
                "wikipedia_title": wiki, "evidence": r.get("title") or name}
    return None


def web_identify(query: str, name_hint: str = "", kind_hint: str = "", year: int | None = None) -> tuple[dict | None, list[str]]:
    """Search the web and pick the work most results agree on. Returns (work or None, notes).
    work: {name, year, type, site, url, wikipedia_title, evidence, agree, sure}."""
    results, notes = web_search(query)
    works = [w for w in (result_work(r) for r in results[:10]) if w]
    if not works:
        return None, notes + (["no title pages among the results"] if results else [])
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, w in enumerate(works):
        groups.setdefault(norm(w["name"]), []).append((i, w))

    def score(items):
        i0, w0 = items[0]
        s = w0["weight"] + 0.6 * (len({w["site"] for _, w in items}) - 1) - 0.06 * i0
        yrs = {w["year"] for _, w in items if w["year"]}
        kinds = {w["type"] for _, w in items if w["type"]}
        if name_hint and similarity(name_hint, w0["name"]) >= 0.85:
            s += 1.0
        if year and yrs:
            s += 0.5 if any(abs(y - year) <= 1 for y in yrs) else -0.7
        if kind_hint and kinds:
            s += 0.3 if kind_hint in kinds or (kind_hint == "anime" and "series" in kinds) else -0.4
        if not kinds:
            s -= 0.3
        return s
    best_items = max(groups.values(), key=score)
    best = dict(best_items[0][1])
    for _, w in best_items:  # fill gaps from the other results about the same work
        for k in ("year", "type", "wikipedia_title"):
            best[k] = best.get(k) or w.get(k)
    best["agree"] = len({w["site"] for _, w in best_items})
    hint_ok = bool(name_hint) and similarity(name_hint, best["name"]) >= 0.85 and (not year or not best["year"] or abs(best["year"] - year) <= 1)
    best["sure"] = hint_ok or best["agree"] >= 2
    return best, notes + [f"best: {best['evidence']} ({best['site']})"]


# ---------------------------------------------------------------- scene search (screenshots)

def trace_me() -> dict:
    """Free check of the monthly trace.moe budget: {quota, used, left}."""
    _, j = http("GET", TRACE_ME)
    j = j or {}
    quota = int(j.get("quota") or 0)
    used = int(j.get("quotaUsed") if j.get("quotaUsed") is not None else j.get("quota_used") or 0)
    return {"quota": quota, "used": used, "left": max(0, quota - used)}


def trace_moe(image: bytes) -> dict | None:
    """Anime scene search. Returns {ext_key, name, names, episode, at_s, score} or None."""
    body, ctype = _multipart("image", "frame.jpg", image)
    _, j = http("POST", f"{TRACE}?anilistInfo&cutBorders", body, {"Content-Type": ctype}, timeout=60)
    if (j or {}).get("error"):
        if re.search(r"quota|limit", j["error"], re.I):
            raise QuotaExceeded("trace.moe: " + j["error"])
        raise ServiceError("trace.moe: " + j["error"])
    res = (j or {}).get("result") or []
    if not res:
        return None
    r = res[0]
    al = r.get("anilist") if isinstance(r.get("anilist"), dict) else {"id": r.get("anilist")}
    if al.get("isAdult"):
        return None
    t = al.get("title") or {}
    return {"ext_key": f"anilist:{al.get('id')}", "anilist_id": al.get("id"),
            "name": t.get("english") or t.get("romaji") or t.get("native") or "",
            "names": [x for x in (t.get("english"), t.get("romaji"), t.get("native")) if x],
            "episode": r.get("episode"), "at_s": r.get("from"), "score": float(r.get("similarity") or 0)}


SAUCE_INDEXES = {21: "anime", 23: "movie", 24: "series", 37: "manga", 371: "manga"}  # adult indexes are never used


def saucenao(image: bytes) -> dict | None:
    """Manga panels and movie/show frames. Returns {name, kind, part, year, imdb, score} or None."""
    params = {"output_type": 2, "numres": 8, "db": 999}
    key = os.environ.get("SAUCENAO_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    body, ctype = _multipart("file", "frame.jpg", image)
    st, j = http("POST", f"{SAUCE}?{urllib.parse.urlencode(params)}", body, {"Content-Type": ctype}, timeout=60)
    hdr = (j or {}).get("header") or {}
    msg = str(hdr.get("message", ""))
    if str(hdr.get("status", "0")) != "0":
        if re.search(r"daily|24 hours|long limit", msg, re.I):
            raise QuotaExceeded("saucenao: " + msg[:120])
        if re.search(r"limit|exceed|30 seconds|short", msg, re.I):
            raise RateLimited("saucenao: " + msg[:120])
    best = None
    for r in (j or {}).get("results") or []:
        h, d = r.get("header") or {}, r.get("data") or {}
        kind = SAUCE_INDEXES.get(int(h.get("index_id") or -1))
        if not kind:
            continue
        name = d.get("source") or d.get("eng_name") or d.get("title") or d.get("jp_name") or ""
        if not name or name.startswith("http"):
            continue
        s = float(h.get("similarity") or 0) / 100.0
        if not best or s > best["score"]:
            yr = re.match(r"(\d{4})", str(d.get("year") or ""))
            best = {"name": name, "kind": kind, "part": str(d.get("part") or ""), "year": int(yr.group(1)) if yr else None,
                    "imdb": d.get("imdb_id"), "score": s, "source_url": (d.get("ext_urls") or [""])[0]}
    return best
