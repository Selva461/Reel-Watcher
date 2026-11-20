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
    phone.open_with({"db": json.dumps(db)}, "#/")
    rows = lambda n: phone.wait_for_function(f"() => document.querySelectorAll('#results a.list-item').length === {n}")
    phone.locator('[data-kind="movies"]').click()
    rows(21)  # 20 English movies and Parasite; the anime and the manhwa have their own chips
    phone.locator("#filt").click()
    phone.locator('[data-f="language"]').select_option("en")
    rows(20)
    phone.locator('[data-f="source"]').select_option("reel")
    rows(13)  # 3 screenshot titles were also in reels
    assert phone.evaluate("!document.getElementById('fdot').hidden")  # the filter icon shows a dot while filters are on
    phone.locator("#fclear").click()
    rows(21)
    phone.locator('[data-kind="manga"]').click()
    rows(1)
    phone.locator('[data-kind="all"]').click()
    phone.locator("#tq").fill("intersteller")  # one typo is fine
    phone.locator("#results").get_by_text("Interstellar", exact=True).wait_for()
    phone.locator("#tq").fill("heat two")
    phone.wait_for_function("() => (document.querySelector('#results a.list-item .title') || {}).textContent === 'Heat Two'")
    phone.locator("#results a.list-item").first.click()
    phone.get_by_role("heading", name="Heat Two").wait_for()
    phone.get_by_role("button", name="Finished").click()
    assert phone.get_by_role("button", name="It is right").count() == 0  # checking is the app's job, not yours
    assert phone.get_by_role("button", name="Not a real title").count() == 0
    m = [x for x in db_of(phone)["media"] if x["title"] == "Heat Two"][0]
    assert m["status"] == "done"
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
    phone.open_with(None, "#/")
    phone.locator("#results").wait_for()
    phone.evaluate("""Watch.addCandidate({ title: "Spirited Away", type: "anime movie", year: 2001, language: "japanese", confidence: 0.7,
                       source: { kind: "screenshot", ref: "content://shot/1", method: "hashtag", text: "#spiritedaway" } })""")
    phone.get_by_text("Spirited Away").wait_for()  # the open list refreshes
    m = db_of(phone)["media"][0]
    assert m["type"] == "anime_movie" and m["language"] == "ja" and m["verified"] == "unverified" and m["confidence"] == 0.7


SEARCH_DB = """(() => {
  const db = { media: [], reels: [], quotes: [] };
  const add = (title, type, genres, runtime, status, year, language, episodes) => {
    const m = Catalog.add(db, { title, type, year, language: language || "en" }).entry;
    m.genres = genres; if (runtime) m.runtime = runtime; if (status) m.status = status; if (episodes) m.episodes = episodes;
    m.verified = runtime ? "verified" : "unverified";
  };
  add("Hereditary", "movie", ["Horror", "Mystery"], 127, "", 2018);
  add("The Babadook", "movie", ["Horror", "Drama"], 94, "", 2014);
  add("Host", "movie", ["Horror"], 57, "", 2020);
  add("Barbarian", "movie", ["Horror", "Thriller"], 102, "done", 2022);
  add("Talk to Me", "movie", ["Horror"], 0, "", 2023);
  add("Kingdom", "kdrama", ["Horror", "Drama"], 50, "", 2019, "ko", 12);
  add("Inception", "movie", ["Science fiction", "Action"], 148, "done", 2010);
  add("Another", "anime", ["Horror", "Mystery", "Supernatural"], 24, "", 2012, "ja", 12);
  db.reels.push({ code: "HR1", url: "https://www.instagram.com/reel/HR1/", status: "done", added_at: 5,
    notes: { topic: "How horror movies use sound", points: ["Low drones make you uneasy"], tags: ["horror", "filmmaking"] }, notes_by: "phone" });
  db.quotes.push({ id: "q1", text: "We all go a little mad sometimes", from: "Psycho", at: 3 });
  return db;
})()"""


def test_everyday_words_become_filters(phone):
    phone.open_with()
    got = phone.evaluate("""(() => { const P = (q) => { const p = Search.parse(q, new Date(2026, 10, 5));
        return { types: p.types, g: p.genres.map(x => x.label), max: p.maxMin, min: p.minMin, lang: p.language, st: p.status, yf: p.yearFrom, yt: p.yearTo, text: p.text, kinds: p.kinds }; };
      return {
        a: P("I want to watch a movie where it is a horror movie and under 1.5 hours"),
        b: P("korean drama I haven't watched"), c: P("anime from the 2010s"), d: P("funny reels about money"),
        e: P("thriller between 1 and 2 hours"), f: P("comedy film in hindi 1h30 or less"), g: P("scary anime movie around 2 hours"),
        h: P("sci-fi series after 2015 already watched"), i: P("movies -horror"), j: P("an hour and a half max romcom"), k: P("recent tamil movies"),
        l: P("quotes about love"), m: P("inception") }; })()""")
    a = got["a"]
    assert a["g"] == ["Horror"] and a["max"] == 90 and "movie" in a["types"] and a["st"] == "" and a["text"] == ""  # "want to watch" is not a filter
    assert got["b"]["types"] == ["kdrama"] and got["b"]["st"] == "want"
    assert got["c"]["types"] == ["anime", "anime_movie"] and (got["c"]["yf"], got["c"]["yt"]) == (2010, 2019)
    assert got["d"]["kinds"] == ["reels"] and got["d"]["g"] == ["Comedy"] and got["d"]["text"] == "money"
    assert (got["e"]["min"], got["e"]["max"]) == (60, 120) and got["e"]["g"] == ["Thriller"]
    assert got["f"]["max"] == 90 and got["f"]["lang"] == "hi" and got["f"]["g"] == ["Comedy"]
    assert got["g"]["types"] == ["anime_movie"] and (got["g"]["min"], got["g"]["max"]) == (102, 138)
    assert got["h"]["g"] == ["Science fiction"] and got["h"]["st"] == "done" and got["h"]["yf"] == 2016
    assert got["i"]["g"] == [] and got["i"]["text"] == "-horror"  # leave-out words stay operators
    assert got["j"]["max"] == 90 and set(got["j"]["g"]) == {"Romance", "Comedy"}
    assert got["k"]["lang"] == "ta" and got["k"]["yf"] == 2023
    assert got["l"]["kinds"] == ["quotes"] and got["l"]["text"] == "love"
    assert got["m"]["text"] == "inception" and got["m"]["types"] is None


def test_search_horror_under_ninety_minutes(phone):
    phone.open_with()
    db = phone.evaluate(SEARCH_DB)
    got = phone.evaluate(f"""(() => {{ const db = {SEARCH_DB}; const T = (q, f) => {{ const r = Search.run(db, q, f || {{}});
        return {{ media: r.media.map(m => m.title), noLength: r.noLength.map(m => m.title), reels: r.reels.map(h => h.reel.code), quotes: r.quotes.map(x => x.id) }}; }};
      return {{ a: T("I want to watch a horror movie under 1.5 hours"), b: T("horror movie under 2 hours not watched"), c: T("horror"),
               d: T("movies -horror"), e: T("korean drama"), f: T("horror", {{ kind: "anime" }}), g: T("mad"), h: T("series under an hour") }}; }})()""")
    assert got["a"]["media"] == ["Host"] and got["a"]["noLength"] == ["Talk to Me"] and got["a"]["reels"] == []
    assert got["b"]["media"] == ["Host", "The Babadook"]  # Barbarian is watched
    assert set(got["c"]["media"]) == {"Hereditary", "The Babadook", "Host", "Barbarian", "Talk to Me", "Kingdom", "Another"}
    assert got["c"]["reels"] == ["HR1"]  # plain words search reels too
    assert got["c"]["media"][-1] == "Barbarian"  # titles you watched come last
    assert got["d"]["media"] == ["Inception"]
    assert got["e"]["media"] == ["Kingdom"]
    assert got["f"]["media"] == ["Another"]
    assert got["g"]["quotes"] == ["q1"]
    assert set(got["h"]["media"]) == {"Kingdom", "Another"}  # one episode's length

    phone.open_with({"db": json.dumps(db)}, "#/")
    phone.locator("#tq").fill("horror movie under 1.5 hours")
    phone.wait_for_function("() => document.querySelectorAll('#results > a.list-item').length === 1")
    phone.locator("#results").get_by_text("Host", exact=True).wait_for()
    assert phone.locator("#understood .tag").all_inner_texts() == ["≤ 1h 30m", "movie", "Horror"]
    phone.locator("#results summary").get_by_text("+1 · length unknown (1 not checked online yet)").wait_for()
    phone.locator("#results a.list-item").first.click()
    phone.get_by_role("heading", name="Host").wait_for()
    phone.get_by_text("57m").wait_for()


def test_voice_search_and_the_inbox(phone):
    phone.open_with()
    db = phone.evaluate(SEARCH_DB)
    db["reels"].append({"code": "NEW1", "url": "https://www.instagram.com/reel/NEW1/", "status": "new", "added_at": 4102444800000, "caption": "Fresh one"})
    phone.open_with({"db": json.dumps(db), "said": "korean drama"}, "#/inbox")
    phone.get_by_role("button", name="Start 1", exact=True).wait_for()
    phone.get_by_role("link", name="Screenshots").wait_for()
    phone.get_by_role("button", name="Comments").wait_for()
    phone.locator("#ibadge").get_by_text("1").wait_for()
    phone.locator(".list-item", has_text="Fresh one").wait_for()  # today's share
    phone.locator("#mic").click()
    phone.wait_for_url("**#/")
    phone.locator("#results").get_by_text("Kingdom", exact=True).wait_for()
    assert phone.locator("#tq").input_value() == "korean drama"
    assert ["listen"] in phone.rn()["calls"]
    assert phone.evaluate("document.documentElement.scrollWidth") <= 390
