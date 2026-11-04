"""The watchlist's online check in the phone app (assets/local/verify.js), with the Java side faked.

The lookups themselves (TMDB, Wikidata, AniList, Jikan, MangaDex, fuzzy matching, the nightly job) are tested in
android/app-shell/app/src/test (JUnit). Here: answers are applied to the watchlist, unsure titles are shown for you to
pick, the TMDB key and nightly switch in Settings. No network."""
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
    "m-dune": {"verdict": "conflict", "confidence": 0.9, "by": "tmdb", "note": "More than one title fits: pick the right one",
               "choices": [{"source": "tmdb", "title": "Dune", "year": 2021, "type": "movie", "language": "en", "score": 0.95,
                            "poster": "https://image.tmdb.org/t/p/w342/d21.jpg", "facts": facts("Dune", 2021, "en", ext={"tmdb": "movie/438631"})},
                           {"source": "tmdb", "title": "Dune", "year": 1984, "type": "movie", "language": "en", "score": 0.94,
                            "poster": "https://image.tmdb.org/t/p/w342/d84.jpg", "facts": facts("Dune", 1984, "en", ext={"tmdb": "movie/841"})}]},
    "m-zzq": {"verdict": "not_found", "confidence": 0.2, "by": "tmdb", "note": "Nothing online matched well enough", "checked_at": 5, "choices": []},
}


def start_db():
    return json.dumps({"reels": [], "inbox": [], "media": [media("m-inceptoin", "Inceptoin"), media("m-dune", "DUNE"),
                                                           media("m-zzq", "zzq vvx"), media("m-heat", "Heat", verified="verified")]})


def test_process_checks_titles_and_unsure_ones_are_yours_to_pick(phone):
    phone.route("https://image.tmdb.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    phone.open_with({"db": start_db(), "verifyAnswers": ANSWERS})
    phone.goto(phone.url.split("#")[0] + "#/watch")
    phone.get_by_role("link", name="Look up online").click()
    phone.get_by_role("button", name="Process: check 3 titles online").click()
    phone.get_by_text("1 verified, 1 to pick, 1 not found").wait_for()
    assert ["verifyNow"] in phone.rn()["calls"]
    d = {m["id"]: m for m in db_of(phone)["media"]}
    inc = d["m-inceptoin"]
    assert inc["verified"] == "verified" and inc["title"] == "Inception" and inc["year"] == 2010 and inc["language"] == "en"
    assert "Inceptoin" in inc["aka"] and inc["poster"].startswith("https://image.tmdb.org/")
    assert d["m-dune"]["verified"] == "conflict" and d["m-dune"]["title"] == "DUNE"  # nothing guessed
    assert d["m-zzq"]["verified"] == "unverified" and d["m-zzq"]["checked_at"] == 5  # not retried every time
    assert d["m-heat"]["verified"] == "verified"

    # pick the 1984 film
    phone.locator("[data-pick='m-dune'][data-i='1']").click()
    dune = {m["id"]: m for m in db_of(phone)["media"]}["m-dune"]
    assert dune["verified"] == "verified" and dune["year"] == 1984 and dune["verified_by"] == "you" and dune["ext"]["tmdb"] == "movie/841"

    # the one not found: type the right name and it goes back in the queue
    phone.locator("[data-retitle='m-zzq'] input").fill("Zodiac")
    phone.locator("[data-retitle='m-zzq'] button").click()
    z = {m["id"]: m for m in db_of(phone)["media"]}["m-zzq"]
    assert z["title"] == "Zodiac" and z["verified"] == "unverified" and "checked_at" not in z
    phone.get_by_role("button", name="Process: check 1 title online").wait_for()


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
    ans = {"m-dune": {**ANSWERS["m-dune"], "choices": [{**ANSWERS["m-dune"]["choices"][0], "title": bad, "poster": ""}]}}
    phone.open_with({"db": start_db(), "verifyPending": ans}, "#/check")
    phone.get_by_text(bad).first.wait_for()
    assert phone.evaluate("window.__pwned") is None
