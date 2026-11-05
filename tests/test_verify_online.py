"""The watchlist's online check in the phone app (assets/local/verify.js), with the Java side faked.

The lookups themselves (TMDB, Wikidata, AniList, Jikan, MangaDex, fuzzy matching, the nightly job) are tested in
android/app-shell/app/src/test (JUnit). Here: answers are applied to the watchlist and titles take their official
names with nothing left for you to pick, old "pick one" titles are checked again, the TMDB key and nightly switch in
Settings. No network."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4a00000000049454e44ae426082")


def media(id_, title, **kw):
    m = {"id": id_, "title": title, "type": "movie", "year": None, "language": "", "aka": [], "genres": [], "ext": {},
         "status": "want", "verified": "unverified", "confidence": 0.6, "updated_at": 1, "added_at": 1,
         "sources": [{"kind": "screenshot", "ref": "content://shot/1", "method": "ocr", "text": title, "confidence": 0.6, "at": 1}]}
    m.update(kw)
    return m


def facts(title, year, lang, typ="movie", **kw):
    f = {"title": title, "year": year, "language": lang, "type": typ, "genres": ["Science fiction"],
         "poster": "https://image.tmdb.org/t/p/w342/x.jpg", "ext": {"tmdb": "movie/1"}}
    f.update(kw)
    return f


ANSWERS = {
    "m-inceptoin": {"verdict": "verified", "confidence": 0.97, "by": "tmdb+wikidata", "note": "Confirmed by tmdb and wikidata",
                    "facts": facts("Inception", 2010, "en"), "choices": []},
    "m-dune": {"verdict": "verified", "confidence": 0.98, "by": "tmdb+wikidata",
               "note": "Confirmed by tmdb and wikidata; picked over Dune (2021), which fewer sources agree on",
               "facts": facts("Dune", 1984, "en", ext={"tmdb": "movie/841"}), "choices": []},
    "m-zzq": {"verdict": "not_found", "confidence": 0.2, "by": "tmdb", "note": "Nothing online matched well enough", "checked_at": 5, "choices": []},
}


def start_db():
    return json.dumps({"reels": [], "inbox": [], "media": [media("m-inceptoin", "Inceptoin"), media("m-dune", "DUNE"),
                                                           media("m-zzq", "zzq vvx"), media("m-heat", "Heat", verified="verified")]})


def test_process_checks_titles_and_renames_them_with_nothing_for_you_to_pick(phone):
    phone.route("https://image.tmdb.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    phone.open_with({"db": start_db(), "verifyAnswers": ANSWERS})
    phone.goto(phone.url.split("#")[0] + "#/inbox")
    phone.get_by_role("link", name="Look up online").click()
    phone.get_by_role("button", name="Process: check 3 titles online").click()
    phone.get_by_text("2 verified and renamed, 1 not found").wait_for()
    assert ["verifyNow"] in phone.rn()["calls"]
    d = {m["id"]: m for m in db_of(phone)["media"]}
    inc = d["m-inceptoin"]
    assert inc["verified"] == "verified" and inc["title"] == "Inception" and inc["year"] == 2010 and inc["language"] == "en"
    assert "Inceptoin" in inc["aka"] and inc["poster"].startswith("https://image.tmdb.org/")
    dune = d["m-dune"]  # the official name, picked by the phone, not "DUNE" from the screenshot
    assert dune["verified"] == "verified" and dune["title"] == "Dune" and dune["year"] == 1984 and dune["ext"]["tmdb"] == "movie/841"
    assert "picked over Dune (2021)" in dune["check"]["note"]
    assert d["m-zzq"]["verified"] == "unverified" and d["m-zzq"]["checked_at"] == 5  # not retried every time
    assert d["m-heat"]["verified"] == "verified"
    # nothing waits for you
    assert phone.locator("[data-pick], [data-keep], [data-retitle]").count() == 0
    assert phone.get_by_text("Need you").count() == 0


def test_titles_left_to_pick_before_the_update_are_checked_again(phone):
    old = json.dumps({"reels": [], "inbox": [], "media": [
        media("m-dune", "DUNE", verified="conflict", review={"choices": [], "note": "pick"}),
        media("m-zzq", "zzq vvx", checked_at=5), media("m-heat", "Heat", verified="verified")]})
    phone.open_with({"db": old}, "#/check")
    phone.get_by_role("button", name="Process: check 2 titles online").wait_for()
    d = {m["id"]: m for m in db_of(phone)["media"]}
    assert d["m-dune"]["verified"] == "unverified" and "review" not in d["m-dune"]
    assert "checked_at" not in d["m-zzq"] and d["m-heat"]["verified"] == "verified"
    assert db_of(phone)["verify_rules"] == 3


def test_answers_from_the_night_are_applied_when_the_app_opens(phone):
    phone.open_with({"db": start_db(), "verifyPending": {"m-inceptoin": ANSWERS["m-inceptoin"]}})
    phone.get_by_text("Titles checked online: 1 verified").wait_for()
    assert {m["id"]: m for m in db_of(phone)["media"]}["m-inceptoin"]["title"] == "Inception"


def test_tmdb_key_and_nightly_switch_in_settings(phone):
    phone.open_with({"db": start_db()}, "#/settings")
    phone.locator("#tmdbkey").fill("my-own-key")
    phone.get_by_role("button", name="Save key").click()
    assert json.loads(phone.rn()["settings"])["tmdbKey"] == "my-own-key"
    sw = phone.get_by_role("switch", name="Check new titles every night")
    assert sw.get_attribute("aria-checked") == "false"  # off by default
    sw.click()
    assert phone.rn()["nightly"] is True
    phone.get_by_role("switch", name="Check new titles every night").wait_for()
    assert phone.get_by_role("switch", name="Check new titles every night").get_attribute("aria-checked") == "true"
    # the key never goes into the exports
    phone.get_by_role("button", name="Save JSON").click()
    phone.wait_for_function("window.__rn.saved.length > 0")
    assert "my-own-key" not in json.dumps(phone.rn()["saved"])


def test_hostile_titles_are_shown_as_text(phone):
    bad = '<img src=x onerror="window.__pwned=1">'
    ans = {"m-dune": {**ANSWERS["m-dune"], "facts": facts(bad, 1984, "en", poster="")}}
    phone.open_with({"db": start_db(), "verifyPending": ans}, "#/")
    phone.get_by_text(bad).first.wait_for()
    assert phone.evaluate("window.__pwned") is None


ZZQ_CHOICES = [{"source": "anilist", "title": "Dai to Dai", "year": 1991, "type": "manga", "language": "ja", "score": 0.5,
                "facts": facts("Dai to Dai", 1991, "ja", "manga", ext={"anilist": "1"})},
               {"source": "mangadex", "title": "Daio", "year": 2020, "type": "manga", "language": "ja", "score": 0.45,
                "facts": facts("Daio", 2020, "ja", "manga", ext={"mangadex": "x"})}]


def test_the_phone_ai_picks_when_no_database_was_sure(phone):
    ans = {"m-zzq": {"verdict": "not_found", "confidence": 0.5, "by": "anilist", "note": "Closest online: Dai to Dai", "checked_at": 5,
                     "choices": ZZQ_CHOICES}}
    phone.open_with({"db": start_db(), "verifyAnswers": ans, "model": {"ready": True}, "answers": ["2"],
                     "web": [{"title": "Daio", "url": "https://en.wikipedia.org/wiki/Daio", "text": "Daio is a manga.", "source": "Wikipedia"}]}, "#/check")
    phone.get_by_role("button", name="Process: check 3 titles online").click()
    phone.get_by_text("1 picked by the phone AI").wait_for()
    st = phone.rn()
    gen = [c for c in st["calls"] if c[0] == "generate"]
    assert len(gen) == 1 and "1. Dai to Dai" in gen[0][1] and "2. Daio" in gen[0][1] and "Daio is a manga." in gen[0][1]
    assert ["webSearch", "zzq vvx Movie"] in st["calls"]  # only the name goes online
    z = {m["id"]: m for m in db_of(phone)["media"]}["m-zzq"]
    assert z["title"] == "Daio" and z["verified"] == "verified" and z["verified_by"] == "phone AI"
    assert st["stopped"] >= 1  # the model is let go afterwards


def test_the_phone_ai_can_say_none_and_nothing_is_renamed(phone):
    ans = {"m-zzq": {"verdict": "not_found", "confidence": 0.5, "by": "anilist", "note": "", "checked_at": 5, "choices": ZZQ_CHOICES}}
    phone.open_with({"db": start_db(), "verifyPending": ans, "model": {"ready": True}, "answers": ["0"]}, "#/check")
    phone.get_by_role("button", name="Process: check 3 titles online").click()  # 3: the old "not found" date is past 30 days
    phone.wait_for_function("() => window.__rn.calls.some((c) => c[0] === 'generate')")
    phone.get_by_text("Done").wait_for()
    z = {m["id"]: m for m in db_of(phone)["media"]}["m-zzq"]
    assert z["title"] == "zzq vvx" and z["verified"] == "unverified" and z["ai_at"] > 0  # not asked again every time
    phone.goto(phone.url.split("#")[0] + "#/m/m-zzq")
    phone.get_by_text("Not found online yet").wait_for()  # marked quietly, tried again later


def test_comment_lines_saved_as_titles_are_deleted(phone):
    db = json.dumps({"reels": [], "inbox": [], "verify_rules": 2, "media": [
        media("m-v", "View 4 replies"), media("m-l", "12 likes Reply"), media("m-u", "ezequiel_266"),
        media("m-ok", "Interstellar"), media("m-kgf", "K.G.F")]})
    phone.open_with({"db": db}, "#/")
    phone.wait_for_function("() => JSON.parse(window.__rn.db).verify_rules === 3")
    assert {m["title"] for m in db_of(phone)["media"]} == {"Interstellar", "K.G.F"}


def test_a_title_shows_its_rating_and_seasons_like_a_movie_app(phone):
    seasons = [{"n": 1, "episodes": 25, "year": 2016, "title": "Re:ZERO -Starting Life in Another World-"},
               {"n": 2, "episodes": 25, "year": 2020, "title": "Re:ZERO Season 2"}, {"n": 3, "episodes": 16, "year": 2024, "title": "Re:ZERO Season 3"}]
    db = json.dumps({"reels": [], "inbox": [], "media": [media("m-rz", "Re:ZERO -Starting Life in Another World-", type="anime", verified="verified",
                                                               ext={"anilist": "21355", "mal": "31240"})]})
    ans = {"m-rz": {"verdict": "details", "runtime": 25, "episodes": 25, "checked_at": 9, "seasons": seasons,
                    "rating": {"score": 8.23, "by": "MyAnimeList", "votes": 1234567}}}
    phone.open_with({"db": db, "verifyPending": ans}, "#/")
    phone.locator("#results").get_by_text("★ 8.2 MyAnimeList", exact=False).wait_for()
    phone.locator("#results").get_by_text("3 seasons · 66 eps", exact=False).wait_for()
    phone.locator("#results a.list-item").first.click()
    phone.get_by_role("heading", name="3 seasons").wait_for()
    phone.get_by_text("16 eps · 2024").wait_for()
    phone.get_by_text("1,234,567 votes", exact=False).wait_for()
    m = db_of(phone)["media"][0]
    assert m["rating"] == {"score": 8.2, "by": "MyAnimeList", "votes": 1234567} and m["details_at"] == 9 and len(m["seasons"]) == 3


def test_omdb_key_in_settings(phone):
    phone.open_with({"db": start_db()}, "#/settings")
    phone.locator("#omdbkey").fill("omdb-key")
    phone.locator("#omdbsave").click()
    assert json.loads(phone.rn()["settings"])["omdbKey"] == "omdb-key"
