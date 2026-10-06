"""Part 2: name identification and free lookups (network faked with each service's documented response shape)."""
import json

import pytest

from reel_watcher import identify, lookups


def anilist_page(*media):
    return {"data": {"Page": {"media": list(media)}}}


VINLAND = {"id": 101348, "type": "ANIME", "format": "TV", "title": {"romaji": "Vinland Saga", "english": "Vinland Saga", "native": "ヴィンランド・サガ"},
           "synonyms": [], "startDate": {"year": 2019}, "episodes": 24, "chapters": None, "genres": ["Action", "Drama"],
           "countryOfOrigin": "JP", "coverImage": {"medium": "https://img/x.jpg"}, "siteUrl": "https://anilist.co/anime/101348"}
FRIEREN = {"id": 154587, "type": "ANIME", "format": "TV", "title": {"romaji": "Sousou no Frieren", "english": "Frieren: Beyond Journey's End", "native": "葬送のフリーレン"},
           "synonyms": ["Frieren"], "startDate": {"year": 2023}, "episodes": 28, "genres": ["Adventure", "Fantasy"], "countryOfOrigin": "JP",
           "coverImage": {"medium": ""}, "siteUrl": ""}


def fake_http(routes):
    calls = []

    def f(method, url, body=None, headers=None, timeout=30):
        calls.append((method, url, body))
        for key, resp in routes:
            if key(method, url, body):
                if isinstance(resp, Exception):
                    raise resp
                return 200, resp(method, url, body) if callable(resp) else resp
        raise AssertionError(f"unexpected call {method} {url}")
    f.calls = calls
    return f


def test_collection_kind():
    assert [identify.collection_kind(n) for n in ("My Anime", "Motivation", "K-drama list", "Bollywood", "Recipes", "Manhwa", "Books to read")] == \
        ["anime", "quote", "series", "movie", "generic", "manga", "book"]


def test_extract_candidates_reel_clues():
    srcs = [("speech", "Number one has to be Frieren, honestly"),
            ("text", "TOP 5 ANIME YOU CAN FINISH IN A WEEKEND"),
            ("text", "1. Pluto 2. Ping Pong the Animation 3. Mushishi"),
            ("caption", "Which one? #vinlandsaga #anime #fyp anime name: Vinland Saga (2019)"),
            ("comment", "name pls??"), ("comment", "Vinland Saga"), ("comment", "its vinland saga bro"),
            ("creator_comment", "Anime: Vinland Saga"), ("comment", "this is so good"), ("text", "10:42 PM Delivered")]
    c = identify.extract_candidates(srcs)
    names = [x["name"] for x in c]
    assert names[0] == "Vinland Saga" and set(c[0]["sources"]) >= {"caption", "comment", "creator_comment"}
    assert {"Pluto", "Ping Pong the Animation", "Mushishi", "Frieren"} <= set(names)
    assert not any("WEEKEND" in n or "Delivered" in n or "bro" in n or n.lower() == "name pls" for n in names)


def test_comment_sources_marks_creator():
    s = identify.comment_sources([{"author": "Creator_A", "text": "Anime: Pluto"}, {"author": "x", "text": " "}, {"author": "y", "text": "Pluto"}], "creator_a")
    assert s == [("creator_comment", "Anime: Pluto"), ("comment", "Pluto")]


def test_anilist_and_resolve(monkeypatch):
    def route(m, u, b):
        q = json.loads(b)["variables"]
        if q.get("t") == "ANIME" and "frieren" in q.get("s", "").lower():
            return anilist_page(FRIEREN)
        if q.get("t") == "ANIME" and "vinland" in q.get("s", "").lower():
            return anilist_page(VINLAND)
        return anilist_page()
    monkeypatch.setattr(lookups, "http", fake_http([(lambda m, u, b: u == lookups.ANILIST, route),
                                                    (lambda m, u, b: "wikidata" in u, {"search": []})]))
    hit = lookups.resolve_name("Frieren", "anime")
    assert hit["ext_key"] == "anilist:154587" and hit["name"] == "Frieren: Beyond Journey's End" and hit["language"] == "Japanese"
    assert hit["year"] == 2023 and hit["extra"]["episodes"] == 28 and hit["score"] >= 0.9
    assert lookups.resolve_name("Totally Unknown Thing", "anime") is None
    out = identify.resolve_candidates(identify.extract_candidates([("caption", "anime name: Vinland Saga"), ("comment", "Vinland Saga"),
                                                                   ("comment", "its Frieren")]), "anime")
    assert [t["name"] for t in out] == ["Vinland Saga", "Frieren: Beyond Journey's End"]
    assert out[0]["confidence"] == "confirmed" and out[0]["source"] == "caption"


def test_wikidata_movie(monkeypatch):
    def route(m, u, b):
        if "wbsearchentities" in u:
            return {"search": [{"id": "Q61448040"}, {"id": "Q1"}]}
        if "props=claims" in u:
            return {"entities": {
                "Q61448040": {"labels": {"en": {"value": "Parasite"}}, "aliases": {"en": [{"value": "Gisaengchung"}]},
                              "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q11424"}}}}],
                                         "P364": [{"mainsnak": {"datavalue": {"value": {"id": "Q9176"}}}}],
                                         "P136": [{"mainsnak": {"datavalue": {"value": {"id": "Q2484376"}}}}],
                                         "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+2019-05-21T00:00:00Z"}}}}]}},
                "Q1": {"labels": {"en": {"value": "Universe"}}, "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q36906466"}}}}]}}}}
        return {"entities": {"Q9176": {"labels": {"en": {"value": "Korean language"}}}, "Q2484376": {"labels": {"en": {"value": "thriller film"}}}}}
    monkeypatch.setattr(lookups, "http", fake_http([(lambda m, u, b: "wikidata" in u, route)]))
    hit = lookups.resolve_name("Parasite", "movie")
    assert hit["ext_key"] == "wikidata:Q61448040" and hit["type"] == "movie" and hit["year"] == 2019
    assert hit["language"] == "Korean" and hit["genres"] == ["thriller film"]


def test_trace_moe_and_saucenao(monkeypatch):
    monkeypatch.setattr(lookups, "http", fake_http([
        (lambda m, u, b: u.startswith(lookups.TRACE), {"result": [{"anilist": {"id": 101348, "title": {"romaji": "Vinland Saga", "english": "Vinland Saga"}},
                                                                    "episode": 12, "from": 521.4, "similarity": 0.96}]}),
        (lambda m, u, b: u.startswith(lookups.SAUCE), {"header": {"status": 0}, "results": [
            {"header": {"similarity": "71.2"}, "data": {"source": "Vagabond", "part": "210"}},
            {"header": {"similarity": "40"}, "data": {"source": "https://x"}}]})]))
    t = lookups.trace_moe(b"jpg")
    assert t == {"ext_key": "anilist:101348", "anilist_id": 101348, "name": "Vinland Saga", "names": ["Vinland Saga", "Vinland Saga"],
                 "episode": 12, "at_s": 521.4, "score": 0.96}
    assert b"filename=\"frame.jpg\"" in lookups.http.calls[0][2]
    assert lookups.saucenao(b"jpg") == {"name": "Vagabond", "part": "210", "score": pytest.approx(0.712), "source_url": ""}


def test_quota_errors(monkeypatch):
    monkeypatch.setattr(lookups, "http", fake_http([(lambda m, u, b: True, lookups.QuotaExceeded("api.trace.moe: HTTP 402"))]))
    with pytest.raises(lookups.QuotaExceeded):
        lookups.trace_moe(b"x")
    monkeypatch.setattr(lookups, "http", fake_http([(lambda m, u, b: True, {"error": "Search quota depleted"})]))
    with pytest.raises(lookups.QuotaExceeded):
        lookups.trace_moe(b"x")
    monkeypatch.setattr(lookups, "http", fake_http([(lambda m, u, b: True, {"header": {"status": -2, "message": "Daily Search Limit Exceeded."}})]))
    with pytest.raises(lookups.QuotaExceeded):
        lookups.saucenao(b"x")


def test_resolve_candidates_survives_errors():
    def resolver(name, hint):
        if name == "Bad":
            raise RuntimeError("boom")
        return {"ext_key": "anilist:1", "name": "Pluto", "type": "anime"} if name == "Pluto" else None
    out = identify.resolve_candidates([{"name": "Bad", "score": 3, "sources": ["text"], "evidence": ""},
                                       {"name": "Pluto", "score": 2, "sources": ["comment"], "evidence": "Pluto!"}], "anime", resolver)
    assert len(out) == 1 and out[0]["source"] == "comment"


def test_other_and_ai_guess():
    assert identify.looks_like_other("Mom 10:42 PM Delivered Seen 10:43 typing")
    assert identify.looks_like_other("Order ID 123 Total ₹499 paid via UPI")
    assert not identify.looks_like_other("VINLAND SAGA")

    class V:
        def __init__(self, out):
            self.out, self.prompt = out, None

        def ask(self, prompt, image, max_tokens=0):
            self.prompt = prompt
            return self.out
    v = V({"is_media": True, "guesses": [{"name": "Dark", "type": "series"}, {"name": ""}, "junk"]})
    assert identify.ai_image_guesses(v, "a.jpg", "WINDEN") == (True, [{"name": "Dark", "type": "series"}])
    assert "WINDEN" in v.prompt
    assert identify.ai_image_guesses(V({"is_media": False, "guesses": []}), "a.jpg") == (False, [])
    assert identify.ai_image_guesses(V({"parse_error": True}), "a.jpg") == (True, [])
    assert identify.ai_image_guesses(None, "a.jpg") == (True, [])
