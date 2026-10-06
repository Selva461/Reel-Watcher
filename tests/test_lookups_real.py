"""Real-world behaviour of the free services, using the response shapes and status codes from their documentation."""
import json

import pytest

from reel_watcher import details, identify, lookups


class FakeClock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 2))
        self.t += s


def test_pacer_keeps_anilist_under_its_limit():
    fc = FakeClock()
    p = lookups._Pacer(fc.clock, fc.sleep)
    for _ in range(26):
        p.wait("graphql.anilist.co")  # 25 per minute allowed
    assert fc.slept and 59 <= fc.slept[0] <= 61
    fc2 = FakeClock()
    p2 = lookups._Pacer(fc2.clock, fc2.sleep)
    for _ in range(5):
        p2.wait("saucenao.com")  # 4 per 30 s for anonymous users
    assert fc2.slept and fc2.slept[0] >= 30


def test_http_status_handling(monkeypatch):
    monkeypatch.setattr(lookups.PACER, "wait", lambda host: None)
    monkeypatch.setattr(lookups.time, "sleep", lambda s: None)
    seq = []

    def raw(responses):
        it = iter(responses)

        def f(method, url, body, headers, timeout):
            seq.append(url)
            return next(it)
        return f
    monkeypatch.setattr(lookups, "_raw_http", raw([(402, {"error": "quota"}, {})]))
    with pytest.raises(lookups.QuotaExceeded):  # trace.moe 402: month used up
        lookups.http("POST", lookups.TRACE)
    monkeypatch.setattr(lookups, "_raw_http", raw([(429, None, {"Retry-After": "2"}), (200, {"ok": 1}, {})]))
    assert lookups.http("POST", lookups.TRACE) == (200, {"ok": 1})  # trace.moe 429: busy, retried
    monkeypatch.setattr(lookups, "_raw_http", raw([(429, None, {})] * 3))
    with pytest.raises(lookups.RateLimited):
        lookups.http("POST", lookups.ANILIST)
    monkeypatch.setattr(lookups, "_raw_http", raw([(404, None, {})]))
    assert lookups.http("GET", lookups.TVMAZE + "/singlesearch/shows?q=x") == (404, None)
    monkeypatch.setattr(lookups, "_raw_http", raw([(500, None, {})]))
    with pytest.raises(lookups.ServiceError):
        lookups.http("GET", lookups.WIKIPEDIA + "x")


def media(id_, english, romaji, year, pop, kind="ANIME", fmt="TV", adult=False):
    return {"id": id_, "idMal": id_ + 1, "type": kind, "format": fmt, "isAdult": adult, "popularity": pop,
            "title": {"english": english, "romaji": romaji, "native": None}, "synonyms": [], "startDate": {"year": year},
            "episodes": 12, "chapters": None, "genres": ["Drama"], "countryOfOrigin": "JP", "coverImage": {"large": "L", "medium": "M"}, "siteUrl": "u"}


def route_anilist(page):
    return lambda m, u, b: {"data": {"Page": {"media": page(json.loads(b)["variables"])}}}


def fake(routes):
    def f(method, url, body=None, headers=None, timeout=30):
        for key, resp in routes:
            if key(method, url, body):
                return 200, resp(method, url, body) if callable(resp) else resp
        raise AssertionError(url)
    return f


def test_resolve_prefers_popular_and_year_and_flags_ambiguity(monkeypatch):
    def page(v):
        if v.get("s") == "Monster":
            return [media(1, "Monster", "Monster", 2004, 300000), media(2, "Monster", "Monster", 2023, 9000)]
        if v.get("s") == "Hentai bait":
            return [media(9, "Hentai bait", "Hentai bait", 2000, 1, adult=True)]
        return []
    monkeypatch.setattr(lookups, "http", fake([(lambda m, u, b: u == lookups.ANILIST, route_anilist(page)),
                                               (lambda m, u, b: "wikidata" in u, {"search": []})]))
    hit = lookups.resolve_name("Monster", "anime")
    assert hit["ext_key"] == "anilist:1" and hit["alternatives"][0]["ext_key"] == "anilist:2"
    assert lookups.resolve_name("Monster", "anime", year=2023)["ext_key"] == "anilist:2"  # the year in the reel decides
    assert hit["cover"] == "L" and hit["extra"]["mal_id"] == 2
    assert lookups.resolve_name("Hentai bait", "anime") is None  # adult entries are never returned


def test_single_common_word_needs_strong_clue():
    def resolver(name, hint, **kw):
        return {"ext_key": "wikidata:Q1", "name": "Dark", "type": "series", "ambiguous": False}
    weak = identify.resolve_candidates([{"name": "Dark", "score": 1.0, "sources": ["text"], "evidence": "DARK"}], "series", resolver)
    strong = identify.resolve_candidates([{"name": "Dark", "score": 4.0, "sources": ["caption", "comment"], "evidence": "series: Dark"}], "series", resolver)
    assert weak[0]["confidence"] == "check" and strong[0]["confidence"] == "confirmed"


def test_candidate_year_and_language_reach_the_resolver():
    seen = {}

    def resolver(name, hint, **kw):
        seen.update(kw, name=name)
        return None
    cands = identify.extract_candidates([("caption", "movie name: Vikram Vedha (2017)")])
    assert cands[0]["year"] == 2017
    identify.resolve_candidates(cands, "movie", resolver, language="ta")
    assert seen == {"name": "Vikram Vedha", "year": 2017, "language": "ta"}


ANILIST_DETAIL = {"data": {"Media": {
    "id": 154587, "idMal": 52991, "type": "ANIME", "format": "TV", "status": "FINISHED", "source": "MANGA", "season": "FALL", "seasonYear": 2023,
    "description": "During their decade-long quest...<br><br>(Source: Crunchyroll)", "episodes": 28, "duration": 24, "chapters": None,
    "volumes": None, "averageScore": 90, "popularity": 400000, "genres": ["Adventure"], "isAdult": False, "countryOfOrigin": "JP",
    "title": {"english": "Frieren: Beyond Journey's End", "romaji": "Sousou no Frieren", "native": "葬送のフリーレン"}, "synonyms": [],
    "startDate": {"year": 2023}, "endDate": {"year": 2024}, "coverImage": {"large": "L"}, "bannerImage": "B", "siteUrl": "https://anilist.co/anime/154587",
    "nextAiringEpisode": None, "studios": {"nodes": [{"name": "Madhouse"}]},
    "staff": {"edges": [{"role": "Original Creator", "node": {"name": {"full": "Kanehito Yamada"}}}, {"role": "Director", "node": {"name": {"full": "X"}}}]},
    "externalLinks": [{"site": "Crunchyroll", "url": "https://www.crunchyroll.com/series/x", "type": "STREAMING", "language": None},
                      {"site": "Twitter", "url": "https://x.com/y", "type": "SOCIAL"}],
    "relations": {"edges": [{"relationType": "SOURCE", "node": {"id": 118586, "type": "MANGA", "format": "MANGA", "title": {"english": "Frieren", "romaji": "Sousou no Frieren"}, "startDate": {"year": 2020}}},
                            {"relationType": "CHARACTER", "node": {"id": 1, "type": "ANIME", "title": {}, "startDate": {}}}]}}}}


def test_details_anime_with_mal_cross_check(monkeypatch):
    monkeypatch.setattr(lookups, "http", fake([
        (lambda m, u, b: u == lookups.ANILIST, ANILIST_DETAIL),
        (lambda m, u, b: u.startswith(lookups.JIKAN), {"data": {"score": 9.3, "rank": 1, "members": 900000, "title_english": "Frieren: Beyond Journey's End", "url": "https://myanimelist.net/anime/52991"}})]))
    d = details.enrich({"ext_key": "anilist:154587", "name": "Frieren: Beyond Journey's End", "type": "anime", "year": 2023, "extra": {}})
    assert d["synopsis"] == "During their decade-long quest..." and d["status"] == "Finished" and d["studios"] == ["Madhouse"]
    assert d["authors"] == ["Kanehito Yamada"] and d["where_to_watch"] == [{"site": "Crunchyroll", "url": "https://www.crunchyroll.com/series/x", "language": None}]
    assert d["related"] == [{"relation": "Source", "name": "Frieren", "type": "manga", "format": "MANGA", "year": 2020, "ext_key": "anilist:118586"}]
    assert d["mal_score"] == 9.3 and d["sources"] == ["AniList", "MyAnimeList"] and "cross_check" not in d and d["season"] == "Fall 2023"


def test_details_series_tvmaze_year_must_match(monkeypatch):
    show = {"name": "Dark", "premiered": "2017-12-01", "ended": "2020-06-27", "status": "Ended", "network": None,
            "webChannel": {"name": "Netflix"}, "rating": {"average": 8.7}, "summary": "<p>A family saga with a supernatural twist.</p>",
            "officialSite": "https://www.netflix.com/title/80100172", "url": "https://www.tvmaze.com/shows/17861/dark", "image": {"original": "I"}, "runtime": 60}
    monkeypatch.setattr(lookups, "http", fake([
        (lambda m, u, b: u.startswith(lookups.WIKIPEDIA), {"type": "standard", "extract": "Dark is a German science fiction thriller...",
                                                            "thumbnail": {"source": "T"}, "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Dark_(TV_series)"}}}),
        (lambda m, u, b: u.startswith(lookups.TVMAZE), show)]))
    d = details.enrich({"ext_key": "wikidata:Q1", "name": "Dark", "type": "series", "year": 2017, "extra": {"wikipedia_title": "Dark (TV series)"}})
    assert d["network"] == "Netflix" and d["status"] == "Ended" and d["synopsis"].startswith("Dark is a German") and d["sources"] == ["Wikipedia", "TVmaze"]
    assert lookups.tvmaze("Dark", 1990) == {}  # a different show with the same name is rejected


def test_details_survive_a_failing_source(monkeypatch):
    def boom(*a, **k):
        raise lookups.RateLimited("graphql.anilist.co: HTTP 429")
    monkeypatch.setattr(lookups, "http", boom)
    assert details.enrich({"ext_key": "anilist:1", "name": "X", "type": "anime", "extra": {"mal_id": 5}}) == {"checked_at": pytest.approx(0, abs=10**10)}


def test_trace_me_and_tmdb_optional(monkeypatch):
    monkeypatch.setattr(lookups, "http", fake([(lambda m, u, b: u == lookups.TRACE_ME, {"id": "1.2.3.4", "priority": 0, "concurrency": 1, "quota": 100, "quotaUsed": 43})]))
    assert lookups.trace_me() == {"quota": 100, "used": 43, "left": 57}
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    assert lookups.tmdb_watch("Parasite", "movie", 2019, "IN") == {}


def test_selftest_and_lookup_report_without_crashing(monkeypatch, capsys):
    from reel_watcher import cli, verify

    def boom(*a, **k):
        raise lookups.ServiceError("graphql.anilist.co: blocked")
    monkeypatch.setattr(lookups, "http", boom)
    rows = verify.selftest()
    assert rows and not any(r["ok"] for r in rows[:1]) and "blocked" in rows[0]["error"]
    monkeypatch.setattr("sys.argv", ["reel-watcher", "selftest"])
    assert cli.main() == 1 and "Problems with" in capsys.readouterr().out
    monkeypatch.setattr(lookups, "resolve_name", lambda *a, **k: {"ext_key": "anilist:1", "name": "Pluto", "type": "anime", "year": 2023,
                                                                  "score": 1.0, "ambiguous": False, "alternatives": [], "extra": {}})
    monkeypatch.setattr(verify.details, "enrich", lambda t, region="IN": {"status": "Finished"})
    res = verify.lookup("pluto", "anime")
    assert res["match"]["name"] == "Pluto" and res["details"] == {"status": "Finished"}
