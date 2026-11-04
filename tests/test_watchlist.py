"""The watchlist (catalog.js + watch.js): categories, dedupe across screenshots and reels, filters, verify, screens.
Driven in Chromium with the fake bridge from test_phone_app. No network, no model."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)

TWENTY = """(() => {
  const db = { media: [] };
  const names = ["Inception", "Interstellar", "The Matrix", "Heat", "Alien", "Jaws", "Up", "Her", "Drive", "Gravity"];
  for (const n of names) Catalog.add(db, { title: n, type: "film", language: "english", source: { kind: "screenshot", ref: "shot-" + n } });
  for (const n of names) Catalog.add(db, { title: n + " Two", type: "movie", language: "en", source: { kind: "reel", ref: "reel-" + n } });
  for (const n of names.slice(0, 3)) Catalog.add(db, { title: n.toUpperCase() + "!", type: "Movie", language: "English", source: { kind: "reel", ref: "dup-" + n } });
  Catalog.add(db, { title: "Parasite", type: "movie", language: "korean", year: 2019 });
  Catalog.add(db, { title: "Solo Leveling", type: "manhwa", language: "ko" });
  Catalog.add(db, { title: "Solo Leveling", type: "anime", language: "ja" });
  return db;
})()"""


def test_ten_plus_ten_english_movies_make_twenty_and_repeats_merge(phone):
    phone.open_with()
    got = phone.evaluate(f"""(() => {{ const db = {TWENTY};
      return {{ total: db.media.length, en: Catalog.filter(db, {{ language: "en", type: "movie" }}).length,
               inception: Catalog.filter(db, {{ q: "inception" }})[0].sources.length,
               watch: Catalog.filter(db, {{ group: "watch" }}).length, read: Catalog.filter(db, {{ group: "read" }}).length,
               ko: Catalog.filter(db, {{ language: "ko" }}).map(m => m.title) }}; }})()""")
    assert got["en"] == 20  # 10 from screenshots + 10 from reels; the 3 repeats were merged, not added
    assert got["inception"] == 2 and got["total"] == 23
    assert got["read"] == 1 and got["watch"] == 22  # an anime and its manhwa stay two entries
    assert sorted(got["ko"]) == ["Parasite", "Solo Leveling"]


def test_categories_are_open_and_free_words_map(phone):
    phone.open_with()
    got = phone.evaluate("""(() => { const db = {};
      const ids = ["Netflix series", "K drama", "cartoon", "donghua", "web novel", "Docuseries", "c-drama", "film", "Webtoon", "Podcast"]
        .map(w => Catalog.typeId(db, w));
      const nid = Catalog.addType(db, "Thai BL", "watch");
      return { ids, nid, info: Catalog.typeInfo(db, nid), unknown: Catalog.typeInfo(db, "podcast").label,
               langs: ["english", "Tamil", "ko-KR", "bollywood", "ja"].map(Catalog.langCode),
               dune: Catalog.add(db, { title: "Dune (2021)" }).entry }; })()""")
    assert got["ids"] == ["series", "kdrama", "animation", "animation", "light_novel", "documentary", "drama", "movie", "webtoon", "podcast"]
    assert got["nid"] == "thai_bl" and got["info"]["group"] == "watch" and got["unknown"] == "Podcast"
    assert got["langs"] == ["en", "ta", "ko", "hi", "ja"]
    assert got["dune"]["title"] == "Dune" and got["dune"]["year"] == 2021


def test_dedupe_rules_and_verify_merges_twins(phone):
    phone.open_with()
    got = phone.evaluate("""(() => { const db = {};
      const a = Catalog.add(db, { title: "The Lord of the Rings: The Two Towers", year: 2002, source: { kind: "screenshot", ref: "s1" } });
      const b = Catalog.add(db, { title: "lord of the rings the two towers", year: 2003, source: { kind: "screenshot", ref: "s1" } });
      const remake = Catalog.add(db, { title: "Dune", year: 1984 }); const dune = Catalog.add(db, { title: "Dune", year: 2021 });
      const tamil = Catalog.add(db, { title: "Drishyam", language: "ml" }); const hindi = Catalog.add(db, { title: "Drishyam", language: "hi" });
      // a misread title: the online check corrects it, and it folds into the entry that was already right
      const right = Catalog.add(db, { title: "Oldboy", year: 2003, language: "ko", source: { kind: "reel", ref: "r1" } });
      const typo = Catalog.add(db, { title: "0ldboy", source: { kind: "screenshot", ref: "s9" } });
      const kept = Catalog.verify(db, typo.entry.id, { title: "Oldboy", year: 2003, language: "korean", genres: ["thriller"], ext: { tmdb: "670" } }, "verified", "tmdb");
      const later = Catalog.add(db, { title: "Oldboy", year: 2013, language: "en" });
      return { merged: b.merged, sources: a.entry.sources.length, remakeSplit: remake.entry !== dune.entry, langSplit: tamil.entry !== hindi.entry,
               keptId: kept.id, rightId: right.entry.id, keptSources: kept.sources.length, verified: kept.verified, genres: kept.genres,
               oldboys: db.media.filter(m => m.title === "Oldboy").length, todo: Catalog.toVerify(db).length, total: db.media.length,
               laterNew: later.created }; })()""")
    assert got["merged"] and got["sources"] == 1  # same screenshot twice is one source
    assert got["remakeSplit"] and got["langSplit"]
    assert got["keptSources"] == 2  # the two Oldboy 2003 entries became one, with both sources and got["verified"] == "verified"
    assert got["genres"] == ["Thriller"] and got["laterNew"]  # the 2013 English remake is a separate title
    assert got["oldboys"] == 2


def test_watchlist_screen_filters_and_detail(phone):
    phone.open_with()
    db = phone.evaluate(TWENTY)
    db["reels"] = [{"code": "reel-Heat", "url": "https://www.instagram.com/reel/reel-Heat/", "status": "new", "added_at": 1}]
    phone.open_with({"db": json.dumps(db)}, "#/watch")
    phone.get_by_role("heading", name="Watchlist").wait_for()
    phone.get_by_text("23 titles").wait_for()
    phone.locator('[data-wf="language"]').select_option("en")
    phone.get_by_text("20 titles of 23").wait_for()
    phone.get_by_role("button", name="To read 0").wait_for()  # counts follow the other filters
    phone.locator('[data-wf="source"]').select_option("reel")
    phone.get_by_text("13 titles of 23").wait_for()  # 3 screenshot titles were also in reels
    phone.get_by_role("button", name="Clear filters").click()
    phone.get_by_role("button", name="Manhwa 1").click()
    phone.get_by_text("1 title of 23").wait_for()
    phone.get_by_role("button", name="Clear filters").click()
    phone.locator("#wq").fill("intersteller")  # one typo is fine
    phone.locator("#wlist").get_by_text("Interstellar", exact=True).wait_for()
    phone.locator("#wq").fill("heat two")
    phone.locator("#wlist a").first.click()
    phone.get_by_role("heading", name="Heat Two").wait_for()
    phone.get_by_role("button", name="Finished").click()
    phone.get_by_role("button", name="It is right").click()
    m = [x for x in db_of(phone)["media"] if x["title"] == "Heat Two"][0]
    assert m["status"] == "done" and m["verified"] == "verified" and m["verified_by"] == "you"
    phone.get_by_role("link", name="Reel").first.click()  # the source reel opens
    phone.get_by_role("heading", name="Titles in this reel").wait_for()


def test_add_title_by_hand_from_a_reel_and_export(phone):
    reels = [{"code": "R1", "url": "https://www.instagram.com/reel/R1/", "status": "new", "added_at": 1}]
    phone.open_with({"db": json.dumps({"reels": reels, "inbox": []})}, "#/r/R1")
    phone.get_by_role("button", name="Add title").click()
    phone.locator("#tt").fill("Crash Landing on You")
    phone.locator("#tk").select_option("kdrama")
    phone.locator("#ty").fill("2019")
    phone.locator("#tl").select_option("ko")
    phone.locator("#tok").click()
    phone.get_by_role("heading", name="Titles in this reel").wait_for()
    phone.locator(".list-item", has_text="Crash Landing on You").wait_for()
    m = db_of(phone)["media"][0]
    assert m["type"] == "kdrama" and m["year"] == 2019 and m["language"] == "ko" and m["sources"][0] == {**m["sources"][0], "kind": "reel", "ref": "R1"}
    assert db_of(phone)["reels"][0]["code"] == "R1"  # the reels are untouched
    phone.goto(phone.url.split("#")[0] + "#/settings")
    phone.get_by_role("button", name="Save watchlist (1 title, CSV)").click()
    phone.get_by_text("Saved to Downloads/ReelShelf/").wait_for()
    csv = phone.rn()["saved"][-1]["text"]
    assert csv.splitlines()[1].startswith("Crash Landing on You,K-drama,2019,Korean")


def test_watch_addcandidate_for_the_extraction_step(phone):
    phone.open_with(None, "#/watch")
    phone.get_by_text("No titles yet").wait_for()
    phone.evaluate("""Watch.addCandidate({ title: "Spirited Away", type: "anime movie", year: 2001, language: "japanese", confidence: 0.7,
                       source: { kind: "screenshot", ref: "content://shot/1", method: "hashtag", text: "#spiritedaway" } })""")
    phone.get_by_text("Spirited Away").wait_for()  # the open list refreshes
    m = db_of(phone)["media"][0]
    assert m["type"] == "anime_movie" and m["language"] == "ja" and m["verified"] == "unverified" and m["confidence"] == 0.7
