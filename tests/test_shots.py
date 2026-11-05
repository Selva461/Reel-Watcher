"""Titles from screenshots and reel captions in the built-in phone app (assets/local/titles.js and shots.js).

The text reader (ML Kit on the phone) is faked: each fake picture comes with the lines it "reads". No network."""
import json

from test_phone_app import FAKE_RN, db_of, phone, site  # noqa: F401  (pytest fixtures)

SHOTS_RN = r"""
(() => {
  const st = window.__rn;
  const later = (fn) => setTimeout(fn, 5);
  Object.assign(st, Object.assign({ folders: [], pics: [], text: {}, shotsDb: "", battery: { level: 80, charging: false }, awake: [] }, st));
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  Object.assign(window.RN, {
    shotFolders: () => JSON.stringify(st.folders),
    addShotFolder: (id) => { const f = { uri: "content://x/tree/primary%3AScreens", name: "Pictures/Anime" }; st.folders.push(f); keep(); later(() => rnDone(id, true, JSON.stringify(f))); },
    removeShotFolder: (u) => { st.folders = st.folders.filter((f) => f.uri !== u); keep(); },
    listShots: (id) => later(() => rnDone(id, true, JSON.stringify(st.pics))),
    readShots: (id, keys) => { st.calls.push(["readShots", JSON.parse(keys)]); keep(); later(() => rnDone(id, true, JSON.stringify(JSON.parse(keys).map((k) =>
      st.text[k] ? { k, ok: true, W: 1080, H: 2400, lines: st.text[k] } : { k, ok: false, error: "could not open the picture" })))); },
    stopShots: () => { st.stopped++; keep(); },
    shotThumb: () => "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
    shotToLens: (k) => { st.opened.push("lens:" + k); keep(); },
    battery: () => JSON.stringify(st.battery),
    keepAwake: (on) => { st.awake.push(on); keep(); },
    loadShots: () => st.shotsDb,
    storeShots: (j) => { st.shotsDb = j; keep(); return true; },
  });
})();
"""


def L(t, y, h=40):
    return {"t": t, "x": 40, "y": y, "w": 600, "h": h}


def read(pg, lines, **opts):
    return pg.evaluate("([l, o]) => { const r = Titles.read(l, o); r.verdict = Titles.verdict(r); return r; }", [lines, opts])


def titles(res):
    return [c["title"] for c in res["candidates"]]


def test_titles_from_typical_screens(phone):
    phone.open_with()
    ig = read(phone, ["12:30", "creator.page", "Follow", "Movies to watch if you loved Inception", "1. Interstellar (2014)",
                      "2. Shutter Island", "3) Prisoners", "Liked by someone and 2,301 others",
                      "creator.page must watch #movies #shutterisland #hollywood", "View all 120 comments"])
    assert titles(ig)[:3] == ["Interstellar", "Shutter Island", "Prisoners"]
    assert ig["candidates"][0]["year"] == 2014 and ig["kind"] == "movie" and ig["lang"] == "english" and ig["verdict"] == "several"
    assert "shutterisland" not in titles(ig)  # the hashtag is the same title, merged
    nf = read(phone, ["Stranger Things", "2016 · TV-14 · 4 Seasons", "Play", "Download", "Episodes"],
              name="Screenshot_20240101-120000_com.netflix.mediaclient.jpg")
    assert titles(nf) == ["Stranger Things"] and nf["candidates"][0]["year"] == 2016 and nf["candidates"][0]["kind"] == "series"
    assert nf["app"] == "netflix"
    g = read(phone, ["Google", "Vikram", "2022 ‧ Action/Thriller ‧ 2h 55m", "Overview", "Cast"])
    assert titles(g) == ["Vikram"] and g["candidates"][0]["year"] == 2022
    asked = read(phone, ["what's the movie name??", "user_two", "@user_one The Prestige", "Reply"])
    assert titles(asked) == ["The Prestige"] and asked["candidates"][0]["why"] == "comment"
    lab = read(phone, ["Anime: Mushishi", "Watch this kdrama: Move to Heaven (2021)"], folder="Pictures/Anime")
    assert titles(lab) == ["Mushishi", "Move to Heaven"]
    assert lab["candidates"][0]["kind"] == "anime" and lab["candidates"][1]["kind"] == "kdrama" and lab["candidates"][1]["lang"] == "korean"
    manga = read(phone, ["Solo Leveling Chapter 110", "Next"], name="Screenshot_x_app.mihon.jpg")
    assert titles(manga) == ["Solo Leveling"] and manga["candidates"][0]["kind"] == "manga"
    tamil = read(phone, ["Best thriller ever #Ratsasan #tamilmovie #kollywood"])
    assert titles(tamil) == ["Ratsasan"] and tamil["lang"] == "tamil"


def test_no_titles_from_chatter_buttons_or_status_bar(phone):
    phone.open_with()
    assert read(phone, ["I watched this yesterday and it was so good guys", "lol", "Reply", "1,204 likes", "2h"])["verdict"] == "none"
    assert read(phone, [])["verdict"] == "no_text"
    # status bar text at the very top of the picture is dropped, the title card below it is kept
    big = read(phone, [L("12:45", 20, 30), L("5G 85%", 20, 30), L("DUNE", 900, 160), L("some small caption text here", 1500, 36),
                       L("another line", 1560, 36), L("and one more", 1620, 36)], W=1080, H=2400)
    assert titles(big) == ["DUNE"] and big["candidates"][0]["why"] == "big-text"
    assert phone.evaluate("Titles.key('The Dark Knight') === Titles.key('Dark  knight!')")
    c = phone.evaluate("Titles.clean('\"Oldboy\" Official Trailer (2003) Hindi Dubbed')")
    assert c == {"title": "Oldboy", "year": 2003, "lang": "hindi", "kind": ""}


def test_process_reads_new_screenshots_into_the_watchlist_and_resumes(phone):
    phone.context.add_init_script(SHOTS_RN)
    pics = [{"k": f"content://x/tree/primary%3AScreens/document/{i}", "n": f"Screenshot_{i}_com.instagram.android.jpg", "f": "DCIM/Screenshots",
             "m": 1000 + i, "s": 1} for i in range(3)]
    text = {pics[0]["k"]: [L("Movie: Interstellar", 600)], pics[1]["k"]: [L("lol so true", 600)],
            pics[2]["k"]: [L("Top anime to watch", 300), L("1. Mushishi", 400), L("2. Monster", 460)]}
    reel = {"code": "R1", "url": "https://www.instagram.com/reel/R1/", "collections": ["Movies"], "status": "done", "added_at": 1,
            "caption": "This ending broke me. Movie name: Arrival (2016) #movies"}
    phone.open_with({"folders": [{"uri": "content://x/tree/primary%3AScreens", "name": "DCIM/Screenshots"}], "pics": pics, "text": text,
                     "db": json.dumps({"reels": [reel], "inbox": []})}, "#/run")
    phone.click("#shotslink")
    phone.wait_for_selector("text=DCIM/Screenshots")
    phone.click("#go")
    phone.wait_for_selector("text=Done")
    media = db_of(phone)["media"]
    got = {m["title"]: m for m in media}
    assert set(got) == {"Interstellar", "Mushishi", "Monster", "Arrival"}
    assert got["Arrival"]["year"] == 2016 and got["Arrival"]["sources"][0]["kind"] == "reel"
    assert got["Mushishi"]["type"] == "anime" and got["Interstellar"]["sources"][0]["method"] == "labelled"
    assert all(m["verified"] == "unverified" for m in media)
    st = phone.rn()
    assert ["verifyNow"] in st["calls"]  # the new titles go to the online check by themselves, no tap
    assert st["awake"] == [True, False]
    seen = json.loads(st["shotsDb"])["seen"]
    assert seen[pics[1]["k"]]["st"] == "none" and seen[pics[0]["k"]]["st"] == "found"
    # a second Process reads only new pictures
    st["pics"].append({"k": "content://x/tree/primary%3AScreens/document/9", "n": "s9.jpg", "f": "DCIM/Screenshots", "m": 5000, "s": 1})
    st["text"]["content://x/tree/primary%3AScreens/document/9"] = [L("Prisoners (2013)", 500)]
    phone.evaluate("s => { Object.assign(window.__rn, s); sessionStorage.setItem('rn', JSON.stringify(window.__rn)); }",
                   {"pics": st["pics"], "text": st["text"]})
    phone.click("#go")
    phone.wait_for_selector("text=1 new screenshot read")
    reads = [c[1] for c in phone.rn()["calls"] if c[0] == "readShots"]
    assert reads[-1] == ["content://x/tree/primary%3AScreens/document/9"]
    assert "Prisoners" in {m["title"] for m in db_of(phone)["media"]}


def test_review_unsure_screenshots_and_low_battery_pause(phone):
    phone.context.add_init_script(SHOTS_RN)
    k = "content://x/tree/primary%3AScreens/document/1"
    shots = {"seen": {k: {"m": 1, "st": "unsure", "n": "s1.jpg", "f": "DCIM/Screenshots", "c": ["Blade Runner"], "x": ""}}, "reels": {}}
    phone.open_with({"shotsDb": json.dumps(shots), "folders": [{"uri": "content://x/tree/primary%3AScreens", "name": "S"}],
                     "pics": [{"k": "content://x/tree/primary%3AScreens/document/2", "n": "a", "f": "S", "m": 2, "s": 1}],
                     "battery": {"level": 9, "charging": False}}, "#/shots/review")
    phone.wait_for_selector("text=Blade Runner")
    phone.click("[data-lens]")
    assert phone.rn()["opened"] == ["lens:" + k]
    phone.click("[data-pick]")
    assert [m["title"] for m in db_of(phone)["media"]] == ["Blade Runner"]
    phone.goto(phone.url.split("#")[0] + "#/shots")
    phone.click("#go")
    phone.wait_for_selector("text=Battery at 9%")
    assert not [c for c in phone.rn()["calls"] if c[0] == "readShots"]


def test_quotes_kept_from_screenshots_and_searchable(phone):
    phone.open_with()
    pick = lambda t: phone.evaluate("t => Quotes.pick(t)", t)  # noqa: E731
    film = "12:30\nInterstellar (2014)\n\"Do not go gentle into that good night.\"\n1.2M likes\nReply"
    assert pick(film) == ["Do not go gentle into that good night."]
    wrapped = "Love is the one thing we're capable of perceiving\nthat transcends dimensions of time and space.\nView all 120 comments"
    assert pick(wrapped) == ["Love is the one thing we're capable of perceiving that transcends dimensions of time and space."]
    assert pick("Follow\nLiked by someone and 2,301 others\nShutter Island\nwww.example.com is great for you all") == []
    phone.context.add_init_script(SHOTS_RN)
    pics = [{"k": "content://x/tree/primary%3AScreens/document/1", "n": "Screenshot_1.jpg", "f": "DCIM/Screenshots", "m": 1001, "s": 1}]
    text = {pics[0]["k"]: [L("Movie: Interstellar", 300), L("Love is the one thing we're capable of perceiving", 600),
                           L("that transcends dimensions of time and space.", 650)]}
    phone.open_with({"folders": [{"uri": "content://x/tree/primary%3AScreens", "name": "DCIM/Screenshots"}], "pics": pics, "text": text}, "#/shots")
    phone.click("#go")
    phone.wait_for_selector("text=Done")
    q = db_of(phone)["quotes"]
    assert len(q) == 1 and q[0]["from"] == "Interstellar" and q[0]["text"].startswith("Love is the one thing")
    phone.goto(phone.url.split("#")[0] + "#/quotes")
    phone.wait_for_url("**#/")
    assert phone.locator('[data-kind="quotes"]').get_attribute("aria-pressed") == "true"
    phone.fill("#tq", "dimensions TIME")
    phone.locator("#results").get_by_text("Interstellar").wait_for()
    phone.fill("#tq", "banana")
    phone.locator("#results").get_by_text("Nothing found").wait_for()
