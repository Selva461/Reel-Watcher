"""Part 4: the app. HTTP API tests, then real-browser UI tests at phone size (Chromium via Playwright).
No network and no AI model: the engine runs with online lookups off."""
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from reel_watcher import demo, ig_export, server, study, worker

try:
    from playwright.sync_api import expect
except ImportError:  # pragma: no cover  UI tests are skipped without Playwright
    expect = None

CHROME = next((p for p in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",) if os.path.exists(p)), None) or \
    shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setenv("REEL_SHELF_ROOTS", str(tmp_path))
    monkeypatch.setattr(study, "ocr_image", lambda p: "")
    lib = demo.build(tmp_path / "lib")
    eng = worker.Engine(lib, vision_factory=None, online=False, idle_wait=0.05, watch_every=3600)
    app = server.App(lib, eng)
    app.save_settings({"online": False})
    eng.start()
    srv = server.make_server(app, "127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield {"base": base, "lib": lib, "app": app, "tmp": tmp_path, "srv": srv}
    srv.shutdown()
    eng.stop(5)


def call(base, path, method="GET", body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null") if "json" in r.headers.get("Content-Type", "") else r.read()
    except urllib.error.HTTPError as e:
        raw_body = e.read()
        try:
            return e.code, json.loads(raw_body or b"null")
        except ValueError:
            return e.code, raw_body


# ---------------------------------------------------------------- API

def test_api_home_search_and_filters(running):
    b = running["base"]
    s, home = call(b, "/api/home")
    assert s == 200 and {c["name"] for c in home["collections"]} == {"Anime", "Movies", "Manga", "Motivation", "Screenshots"}
    assert home["check"] == 2 and len(home["recent"]) == 5
    names = lambda q: sorted(r["name"] for r in call(b, "/api/search?" + q)[1]["results"])
    assert names("q=par") == ["Parasite"]
    assert names("language=Korean,Tamil") == ["Parasite", "Vikram Vedha"]
    assert names("type=anime&collection=Anime") == ["Frieren: Beyond Journey's End", "Pluto", "Vinland Saga"]
    assert names("reel_language=Tamil") == ["Vikram Vedha", "Vinland Saga"]
    assert names("found_from=Screenshot") == ["Berserk", "Vagabond", "Vinland Saga"]
    assert names("found_from=Comment") == ["Vikram Vedha", "Vinland Saga"]
    assert names("status=watched") == ["Parasite"] and names("status=favorites") == ["Frieren: Beyond Journey's End"]
    assert names("confidence=check") == ["Berserk", "Dark", "Vagabond"]
    assert names("year_from=2020&type=anime") == ["Frieren: Beyond Journey's End", "Pluto"]
    assert names("genre=Thriller") == ["Parasite", "Vikram Vedha"]
    top = call(b, "/api/search?sort=most")[1]["results"][0]
    assert top["name"] == "Vinland Saga" and top["n_reels"] == 2 and top["confidence"] == "confirmed"
    f = call(b, "/api/facets")[1]
    assert {"Japanese", "Korean", "Hindi", "Tamil", "German"} <= set(f["languages"]) and "Tamil" in f["reel_languages"]
    s, csv = call(b, "/api/export.csv?collection=Movies")
    assert s == 200 and b"Parasite" in csv and b"Vinland" not in csv


def test_api_titles_check_quotes_and_errors(running):
    b, lib = running["base"], running["lib"]
    tid = lib.one("SELECT id FROM titles WHERE name='Pluto'")["id"]
    assert call(b, f"/api/titles/{tid}", "PATCH", {"watch": "watching", "favorite": True, "notes": "hi"})[1]["watch"] == "watching"
    assert call(b, f"/api/titles/{tid}", "PATCH", {"watch": "nope"})[0] == 400
    assert call(b, "/api/titles/9999")[0] == 404
    checks = call(b, "/api/check")[1]["finds"]
    berserk = next(f for f in checks if f["name"] == "Berserk")
    item = call(b, f"/api/finds/{berserk['id']}/confirm", "POST", {})[1]
    assert [f["name"] for f in item["finds"]] == ["Berserk"] and item["status"] == "done"  # the other guess was removed
    dark = next(f for f in call(b, "/api/check")[1]["finds"] if f["name"] == "Dark")
    item = call(b, f"/api/finds/{dark['id']}/rename", "POST", {"name": "Dark (German series)", "type": "series"})[1]
    assert item["finds"][0]["name"] == "Dark (German series)" and item["finds"][0]["source"] == "user"
    q = call(b, "/api/quotes?collection=Motivation")[1]["quotes"]
    assert len(q) == 2 and call(b, "/api/quotes?favorites=1")[1]["quotes"][0]["quote"] == "Start before you feel ready."
    assert call(b, f"/api/quotes/{q[0]['id']}/favorite", "POST", {"on": True})[1] == {"favorite": True}
    assert call(b, f"/api/quotes/{q[0]['id']}/render", "POST", {"style": "comic"})[0] == 400
    if shutil.which("ffmpeg"):
        media = call(b, f"/api/quotes/{q[0]['id']}/render", "POST", {"style": "clean", "format": "mp4"})[1]["media"]
        assert media.endswith("_clean.mp4") and call(b, "/media/" + media)[0] == 200
    assert call(b, "/media/../library.db")[0] == 404  # no escaping the media folder
    assert call(b, "/api/nope")[0] == 404


def test_api_import_read_and_jobs(running):
    b = running["base"]
    z = running["tmp"] / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("saved/saved_collections.json", json.dumps({"saved_saved_collections": [
            {"string_map_data": {"Name": {"value": "Series"}}},
            {"string_map_data": {"Name": {"href": "https://www.instagram.com/reel/NEW1/", "value": "x"}}}]}))
    s, r = call(b, "/api/import", "POST", raw=z.read_bytes(), headers={"X-Filename": "export.zip", "Content-Type": "application/octet-stream"})
    assert s == 200 and r == {"collections": {"Series": 1}}
    assert call(b, "/api/import", "POST", raw=b"not a zip", headers={"X-Filename": "x.zip"})[0] == 400
    s, r = call(b, "/api/collections/Series/read", "POST", {})
    assert r["queued"] == 1
    jobs = call(b, f"/api/jobs/{r['job']}/pause", "POST", {})[1]
    assert next(j for j in jobs["jobs"] if j["id"] == r["job"])["state"] == "paused"
    assert call(b, "/api/jobs/all/resume", "POST", {})[1]["jobs"][0]["state"] == "running"
    assert call(b, "/api/identify/reel", "POST", {"url": "https://example.com/x"})[0] == 400


def test_api_import_loose_json_files(running):
    """Exports saved to Google Drive arrive as separate JSON files, picked one at a time and sometimes renamed."""
    b, lib = running["base"], running["lib"]
    up = lambda name, data: call(b, "/api/import", "POST", raw=json.dumps(data).encode(),
                                 headers={"X-Filename": name, "Content-Type": "application/octet-stream"})
    reel = lambda c: {"string_map_data": {"Name": {"href": f"https://www.instagram.com/reel/{c}/", "value": "x"}}}
    s, r = up("saved_posts.json", {"saved_saved_media": [reel("DRV1"), reel("LOOSE9")]})
    assert s == 200 and r["collections"] == {ig_export.UNSORTED: 2}
    s, r = up("saved_collections (1).json", {"saved_saved_collections": [{"string_map_data": {"Name": {"value": "Drive"}}}, reel("DRV1")]})
    assert s == 200 and r["collections"] == {"Drive": 1, ig_export.UNSORTED: 1}
    in_coll = lambda c: [x["collection"] for x in lib.q(
        "SELECT collection FROM item_collections WHERE item_id=(SELECT id FROM items WHERE key=?)", (f"reel:{c}",))]
    assert in_coll("DRV1") == ["Drive"] and in_coll("LOOSE9") == [ig_export.UNSORTED]
    s, r = up("saved_music.json", {"saved_saved_music": []})
    assert s == 400 and "saved_collections.json" in r["error"]


def test_api_folders_and_identify_image(running):
    b, tmp = running["base"], running["tmp"]
    folder = tmp / "pics"
    for n in range(5):
        p = folder / f"s{n}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (90, 160), (n * 50, 20, 200 - n * 30)).save(p)
    fs = call(b, "/api/fs?path=" + urllib.request.quote(str(tmp)))[1]
    assert any(d["name"] == "pics" for d in fs["dirs"]) and call(b, "/api/fs?path=" + urllib.request.quote(str(folder)))[1]["images"] == 5
    assert call(b, "/api/folders", "POST", {"folders": ["/definitely/missing"]})[0] == 403  # outside storage
    assert call(b, "/api/folders", "POST", {"folders": [str(tmp / "missing")]})[0] == 400
    job = call(b, "/api/folders", "POST", {"folders": [str(folder)], "collection": "Shots"})[1]["job"]
    running["app"].engine.run_until_idle(20)
    import time
    for _ in range(50):
        j = next(x for x in call(b, "/api/jobs")[1]["jobs"] if x["id"] == job)
        if j["finished"]:
            break
        time.sleep(0.1)
    assert j["finished"] and j["total"] >= 1
    raw = (folder / "s1.png").read_bytes()
    s, r = call(b, "/api/identify/image", "POST", raw=raw, headers={"X-Filename": "shot.png", "Content-Type": "application/octet-stream"})
    assert s == 200 and r["item"]
    assert call(b, "/api/identify/image", "POST", raw=b"x", headers={"X-Filename": "notes.txt"})[0] == 400


def test_lan_token_required(tmp_path):
    lib = demo.build(tmp_path / "l")
    srv = server.make_server(server.App(lib), "127.0.0.1", 0, token="secret123")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert call(base, "/api/home")[0] == 401
        assert call(base, "/api/home", headers={"X-Token": "secret123"})[0] == 200
        assert call(base, "/api/home", headers={"X-Token": "secret12"})[0] == 401
        import http.client
        h = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        h.request("GET", "/?t=secret123")
        r = h.getresponse()
        cookie = r.getheader("Set-Cookie", "")
        # the code is moved into an HttpOnly cookie and removed from the address bar
        assert r.status == 303 and r.getheader("Location") == "/" and "rs_token=secret123" in cookie and "HttpOnly" in cookie
        h.close()
        assert call(base, "/api/home", headers={"Cookie": "rs_token=secret123"})[0] == 200
    finally:
        srv.shutdown()


def test_security_rebinding_csrf_and_headers(running):
    """Attacks a web page in the phone's browser could try against the local server."""
    b = running["base"]
    port = b.rsplit(":", 1)[1]
    import http.client

    def raw(method, path, headers, body=None):
        h = http.client.HTTPConnection("127.0.0.1", int(port))
        h.request(method, path, body=body, headers=headers)
        r = h.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        h.close()
        return out
    # DNS rebinding: a site whose name now points at 127.0.0.1 is refused by name
    assert raw("GET", "/api/home", {"Host": f"evil.example:{port}"})[0] == 421
    assert raw("GET", "/api/home", {"Host": f"localhost:{port}"})[0] == 200
    assert raw("GET", "/api/home", {"Host": f"[::1]:{port}"})[0] == 200
    # cross-site request forgery: a plain form post, or JSON from another site's page, changes nothing
    before = running["app"].settings()["region"]
    body = json.dumps({"region": "ZZ"})
    assert raw("POST", "/api/settings", {"Host": f"localhost:{port}", "Content-Type": "text/plain"}, body)[0] == 403
    assert raw("POST", "/api/settings", {"Host": f"localhost:{port}", "Content-Type": "application/x-www-form-urlencoded"}, "region=ZZ")[0] == 403
    assert raw("POST", "/api/settings", {"Host": f"localhost:{port}", "Content-Type": "application/json", "Origin": "https://evil.example"}, body)[0] == 403
    assert running["app"].settings()["region"] == before != "ZZ"  # the blocked calls changed nothing
    st, _, out = raw("POST", "/api/settings", {"Host": f"localhost:{port}", "Content-Type": "application/json", "Origin": f"http://localhost:{port}"},
                     json.dumps({"region": "US"}))
    assert st == 200 and json.loads(out)["region"] == "US"
    # browser protections on the page itself
    st, hdr, _ = raw("GET", "/", {"Host": f"localhost:{port}"})
    assert "script-src 'self'" in hdr["Content-Security-Policy"] and "frame-ancestors 'none'" in hdr["Content-Security-Policy"]
    assert hdr["X-Frame-Options"] == "DENY" and hdr["X-Content-Type-Options"] == "nosniff" and hdr["Referrer-Policy"] == "no-referrer"
    assert raw("POST", "/api/settings", {"Host": f"localhost:{port}", "Content-Type": "application/json", "Content-Length": "-5"})[0] in (400, 403)


# ---------------------------------------------------------------- UI in a real browser at phone size

@pytest.fixture
def page(running):
    if not CHROME:
        pytest.skip("Chromium not available")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                  permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        # the app must work under its own Content Security Policy: any violation fails the test
        pg.on("console", lambda m: errors.append(m.text) if "Content Security Policy" in m.text else None)
        pg.goto(running["base"] + "/")
        pg.running = running
        pg.errors = errors
        yield pg
        assert not errors, errors
        browser.close()


def no_side_scroll(pg):
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390


def test_ui_home_collection_and_title(page):
    pg = page
    pg.get_by_role("heading", name="What did you save?").wait_for()
    for name in ("Anime", "Movies", "Motivation", "Screenshots", "Manga"):
        assert pg.locator(f'a[href="#/c/{name}"]').count() == 1
    assert pg.get_by_text("2 unsure guesses to confirm").is_visible()
    no_side_scroll(pg)
    pg.locator('a[href="#/c/Anime"]').click()
    pg.get_by_role("heading", name="Anime").wait_for()
    assert pg.locator(".list-item").count() == 3
    pluto = pg.get_by_role("button", name="Mark Pluto as watched")
    pluto.click()
    pg.get_by_text("Marked as watched").wait_for()
    assert pg.get_by_role("button", name="Mark Pluto as not watched").get_attribute("aria-pressed") == "true"
    pg.get_by_role("button", name="Watched", exact=True).click()
    expect(pg.locator(".list-item")).to_have_count(1)
    assert pg.locator(".list-item .title").inner_text() == "Pluto"
    pg.get_by_role("button", name="All", exact=True).click()
    expect(pg.locator(".list-item")).to_have_count(3)
    pg.get_by_text("Frieren: Beyond Journey's End").click()
    pg.get_by_role("heading", name="Frieren: Beyond Journey's End").wait_for()
    assert pg.get_by_text("28 episodes").is_visible() and pg.get_by_text("Number one has to be Frieren").first.is_visible()
    assert pg.get_by_text("An elf mage outlives").is_visible() and pg.get_by_text("Madhouse").is_visible()
    assert pg.get_by_text("AniList 90% · MAL 9.3").is_visible() and pg.get_by_text("Details from AniList, MyAnimeList").is_visible()
    assert pg.get_by_role("link", name="Crunchyroll").get_attribute("href") == "https://www.crunchyroll.com/"
    assert pg.get_by_text("Source · Manga · 2020").is_visible() and pg.get_by_role("link", name="MyAnimeList").count() == 1
    pg.get_by_role("button", name="Refresh details").click()
    pg.get_by_text("Turn on online lookups in Settings to fetch details").wait_for()  # tests run offline
    pg.get_by_role("button", name="Watching").click()
    pg.wait_for_selector('[data-w="watching"][aria-pressed="true"]')
    pg.get_by_role("button", name="Remove from favorites").click()
    pg.get_by_role("button", name="Add to favorites").wait_for()
    pg.fill("#notes", "watch with friends")
    pg.locator("#notes").dispatch_event("change")
    pg.get_by_text("Note saved").wait_for()
    t = pg.running["lib"].one("SELECT watch, favorite, notes FROM titles WHERE name LIKE 'Frieren%'")
    assert t == {"watch": "watching", "favorite": 0, "notes": "watch with friends"}
    no_side_scroll(pg)


def test_ui_search_language_and_filters(page):
    pg = page
    pg.locator("nav.tabs").get_by_text("Search").click()
    pg.locator("#q").wait_for()
    pg.get_by_role("button", name="Korean").click()
    expect(pg.locator("#results .list-item")).to_have_count(1)
    assert pg.locator("#results .title").inner_text() == "Parasite"
    pg.get_by_role("button", name="Tamil").click()
    expect(pg.locator("#results .list-item")).to_have_count(2)
    pg.get_by_role("button", name="All").first.click()
    pg.fill("#q", "idiots")
    expect(pg.locator("#results .list-item")).to_have_count(1)
    expect(pg.locator("#results .title")).to_have_text("3 Idiots")
    pg.fill("#q", "")
    pg.locator("#results .list-item").nth(5).wait_for()
    pg.get_by_role("link", name="All filters").click()
    pg.get_by_role("heading", name="Filters").wait_for()
    pg.locator('[data-k="type"][data-v="anime"]').click()
    pg.wait_for_selector('[data-k="type"][data-v="anime"][aria-pressed="true"]')
    pg.locator('[data-k="found_from"][data-v="Comment"]').click()
    pg.get_by_role("link", name="Show 1 result").wait_for()
    pg.select_option("#sort", "az")
    pg.get_by_role("link", name="Show 1 result").click()
    expect(pg.locator("#results .list-item")).to_have_count(1)
    assert pg.locator("#results .title").inner_text() == "Vinland Saga"
    assert pg.get_by_role("link", name="All filters, 2 active").is_visible()
    pg.get_by_role("link", name="All filters, 2 active").click()
    pg.get_by_role("button", name="Reset").click()
    pg.get_by_role("link", name="Show 9 results").wait_for()  # all 9 demo titles
    no_side_scroll(pg)


def test_ui_motivation_gif_styles_and_actions(page):
    pg = page
    pg.locator('a[href="#/c/Motivation"]').click()
    pg.get_by_role("heading", name="Motivation").wait_for()
    assert pg.locator(".tile").count() == 2
    pg.get_by_role("button", name="Switch to list view").click()
    pg.get_by_text("Rest if you must, but do not quit.").wait_for()
    pg.get_by_role("button", name="Favorites").click()
    expect(pg.locator(".list-item")).to_have_count(1)
    pg.get_by_role("button", name="All", exact=True).click()
    pg.get_by_role("button", name="Switch to grid view").click()
    pg.locator(".tile").first.click()
    pg.locator(".quote-text").wait_for()
    if shutil.which("ffmpeg"):
        pg.wait_for_selector("#mf img[src$='_bold.gif']")
        pg.get_by_role("button", name="Typewriter").click()
        pg.wait_for_selector("#mf img[src$='_typewriter.gif']", timeout=20000)
        pg.get_by_role("button", name="Video with sound").click()
        pg.wait_for_selector("#mf video[src$='_typewriter.mp4']", timeout=20000)
        assert pg.locator("#save").get_attribute("download").endswith(".mp4")
    pg.get_by_role("button", name="Copy text").click()
    pg.get_by_text("Quote copied").wait_for()
    fav = pg.locator("#fav")
    before = fav.get_attribute("aria-pressed")
    fav.click()
    expect(pg.locator("#fav")).not_to_have_attribute("aria-pressed", before)
    assert pg.get_by_role("link", name="Next").count() + pg.get_by_role("link", name="Previous").count() == 1
    no_side_scroll(pg)


def test_ui_same_name_switch(page):
    pg = page
    tid = pg.running["lib"].one("SELECT title_id FROM finds WHERE name_raw='Dark'")["title_id"]
    pg.goto(pg.running["base"] + f"/#/t/{tid}")
    pg.get_by_text("Could also be:").wait_for()
    pg.get_by_role("button", name="Dark · 2005 · Movie").click()
    pg.get_by_text("Changed").wait_for()
    pg.get_by_role("heading", name="Dark").wait_for()
    assert pg.get_by_text("2005").first.is_visible()
    f = pg.running["lib"].one("SELECT f.confidence, f.alts, t.ext_key FROM finds f JOIN titles t ON t.id=f.title_id WHERE f.name_raw='Dark'")
    assert f["ext_key"] == "wikidata:Q1167447" and f["confidence"] == "confirmed" and f["alts"][0]["year"] == 2017  # the old pick became the alternative


def test_ui_check_identify_and_read(page):
    pg = page
    pg.get_by_text("2 unsure guesses to confirm").click()
    pg.get_by_role("heading", name="Possible matches").wait_for()
    pg.get_by_role("button", name="Not Berserk").click()
    pg.get_by_text("Removed").wait_for()
    pg.locator("[data-ok]").first.click()
    pg.get_by_text("Confirmed").wait_for()
    pg.locator("[data-fix]").first.click()
    pg.fill("#rn", "Dark")
    pg.select_option("#rt", "series")
    pg.get_by_role("button", name="Save").click()
    pg.get_by_text("Nothing to check. Nice.").wait_for()
    pg.goto(pg.running["base"] + "/#/settings")
    pg.select_option("#region", "US")
    pg.get_by_text("Country saved").wait_for()
    assert pg.running["app"].settings()["region"] == "US"
    pg.goto(pg.running["base"] + "/#/")

    pg.locator("nav.tabs").get_by_text("Identify").click()
    pg.get_by_role("tab", name="Reel link").click()
    pg.fill("#url", "https://example.com/not-instagram")
    pg.get_by_role("button", name="Identify").click()
    pg.get_by_text("Paste an Instagram reel or post link").wait_for()
    pg.get_by_role("tab", name="Screenshot").click()
    img = pg.running["tmp"] / "pick.png"
    Image.new("RGB", (90, 160), (10, 120, 200)).save(img)
    pg.set_input_files("#pic", str(img))
    pg.wait_for_url("**#/item/*")
    pg.get_by_role("heading", name="Not found").wait_for(timeout=20000)  # offline + no AI: nothing to confirm
    pg.get_by_role("button", name="Type the name myself").wait_for()

    pg.goto(pg.running["base"] + "/#/c/Movies")
    pg.get_by_role("button", name="Read this collection (1 reels)").click()
    pg.get_by_text("Reading 1 reels in the background").wait_for()
    pg.locator("nav.tabs").get_by_text("Jobs").click()
    pg.get_by_role("heading", name="Running in background").wait_for()
    pg.get_by_text("Read Movies").first.wait_for()
    no_side_scroll(pg)


def test_ui_no_match_shows_steps_retry_and_type_name(page):
    """A screenshot nothing could identify: the app says what was tried, can try again, and lets you type the name."""
    pg = page
    pg.goto(pg.running["base"] + "/#/identify")
    img = pg.running["tmp"] / "blank.png"
    Image.new("RGB", (90, 160), (200, 30, 30)).save(img)
    pg.set_input_files("#pic", str(img))
    pg.wait_for_url("**#/item/*")
    pg.get_by_role("heading", name="Not found").wait_for(timeout=20000)
    pg.get_by_text("What was tried").wait_for()
    pg.get_by_text("Read text", exact=True).wait_for()
    pg.get_by_text("no text in the picture").wait_for()
    pg.get_by_role("button", name="Try again").click()
    pg.get_by_text("Trying again").wait_for()
    pg.get_by_role("heading", name="Not found").wait_for(timeout=20000)
    pg.get_by_role("button", name="Type the name myself").click()
    pg.fill("#rn", "Scene")
    pg.select_option("#rt", "movie")
    pg.get_by_role("button", name="Save").click()
    pg.wait_for_url("**#/t/*")
    pg.get_by_role("heading", name="Scene").wait_for()
    no_side_scroll(pg)


def test_ui_server_down_message(page):
    pg = page
    pg.goto(pg.running["base"] + "/#/search")
    pg.get_by_placeholder("Title, creator, genre").wait_for()
    pg.running["srv"].shutdown()
    pg.running["srv"].server_close()
    pg.evaluate("location.hash = '#/check'")
    pg.get_by_text("Reel Shelf is not running").wait_for()


def test_ui_folder_scan_and_progress(page):
    pg = page
    folder = pg.running["tmp"] / "phone" / "Screenshots"
    for n in range(4):
        p = folder / f"s{n}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (90, 160), (n * 60, 90, 30)).save(p)
    pg.evaluate("p => localStorage.setItem('rs.lastFolder', JSON.stringify(p))", str(folder.parent))
    pg.goto(pg.running["base"] + "/#/folder")
    pg.get_by_role("heading", name="Scan a folder").wait_for()
    assert pg.get_by_role("button", name="Start scanning in background").is_disabled()
    pg.get_by_role("button", name="Screenshots").click()
    pg.get_by_role("button", name="Select this folder (4 images here)").click()
    pg.get_by_role("button", name=f"Remove {folder}").wait_for()
    sw = pg.get_by_role("switch", name="Watch these folders")
    sw.click()
    assert sw.get_attribute("aria-checked") == "false"
    pg.get_by_role("button", name="Up").click()
    pg.get_by_role("button", name="Start scanning in background").click()
    pg.get_by_role("heading", name="Running in background").wait_for()
    pg.get_by_text("Scan Screenshots").first.wait_for()
    pg.locator(".card", has_text="Scan Screenshots").filter(has_text="Done").first.wait_for(timeout=20000)
    job = pg.running["lib"].one("SELECT params FROM jobs WHERE name='Scan Screenshots'")
    assert job["params"]["watch"] is False and job["params"]["folders"] == [str(folder)]
    no_side_scroll(pg)


def test_ui_import_and_settings(page):
    pg = page
    z = pg.running["tmp"] / "ig.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("saved_collections.json", json.dumps({"saved_saved_collections": [
            {"string_map_data": {"Name": {"value": "K-drama"}}},
            {"string_map_data": {"Name": {"href": "https://www.instagram.com/reel/KD1/", "value": "x"}}}]}))
    pg.goto(pg.running["base"] + "/#/import")
    pg.set_input_files("#zip", str(z))
    pg.get_by_role("heading", name="Found 1 collections").wait_for()
    pg.get_by_role("button", name="Read").click()
    pg.get_by_role("button", name="Started").wait_for()
    # loose files from Google Drive, chosen together; saved_music.json is not needed and is skipped
    t = pg.running["tmp"]
    (t / "saved_posts.json").write_text(json.dumps({"saved_saved_media": [
        {"string_map_data": {"Name": {"href": "https://www.instagram.com/reel/GD1/", "value": "x"}}}]}), encoding="utf-8")
    (t / "saved_collections.json").write_text(json.dumps({"saved_saved_collections": [
        {"string_map_data": {"Name": {"value": "From Drive"}}},
        {"string_map_data": {"Name": {"href": "https://www.instagram.com/reel/GD1/", "value": "x"}}}]}), encoding="utf-8")
    (t / "saved_music.json").write_text("{}", encoding="utf-8")
    pg.set_input_files("#zip", [str(t / "saved_posts.json"), str(t / "saved_music.json"), str(t / "saved_collections.json")])
    pg.get_by_text("From Drive").wait_for()
    pg.get_by_text("Skipped: saved_music.json").wait_for()
    pg.goto(pg.running["base"] + "/#/settings")
    sw = pg.get_by_role("switch", name="Online lookups")
    assert sw.get_attribute("aria-checked") == "false"
    sw.click()
    pg.get_by_text("Online lookups on").wait_for()
    assert pg.running["app"].settings()["online"] is True
    pg.get_by_text("Updates: run the setup command again.").wait_for()  # test server has no restart hook
    from reel_watcher import checks

    def fake_checks(data_dir=None, progress=None):
        rows = [{"name": "Text reader (OCR)", "ok": True, "detail": "read: 'VINLAND SAGA'", "hint": "", "seconds": 0.1},
                {"name": "AI model (Ollama)", "ok": False, "detail": "Ollama: HTTP 500: out of memory", "hint": "Optional.", "seconds": 0.1}]
        for i in range(len(rows) + 1):
            progress(rows[i]["name"] if i < len(rows) else "", rows[:i])
            time.sleep(0.4)
        return rows
    real, checks.run_checks = checks.run_checks, fake_checks
    try:
        pg.get_by_role("button", name="Run self-check").click()
        pg.get_by_text("1 of 2 passed").wait_for(timeout=10000)
        pg.get_by_text("Ollama: HTTP 500: out of memory").wait_for()
    finally:
        checks.run_checks = real
    assert Path(pg.running["lib"].dir / "settings.json").exists()


def test_api_version_and_self_update(tmp_path, monkeypatch):
    import subprocess
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    git = lambda *a: subprocess.run(["git", *a], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "--bare", str(tmp_path / "up.git"))
    git("clone", "-q", str(tmp_path / "up.git"), str(tmp_path / "dev"))
    (tmp_path / "dev" / "f.txt").write_text("1", encoding="utf-8")
    git("-C", str(tmp_path / "dev"), "add", "f.txt")
    git("-C", str(tmp_path / "dev"), "commit", "-qm", "one")
    git("-C", str(tmp_path / "dev"), "push", "-q", "origin", "HEAD")
    git("clone", "-q", str(tmp_path / "up.git"), str(tmp_path / "phone"))
    app = server.App(demo.build(tmp_path / "lib"))
    assert app.version()["can_update"] is False  # no restart hook: not running as the app
    app.repo, restarts = tmp_path / "phone", []
    app.restart = lambda: restarts.append(1)
    v = app.version()
    assert v["can_update"] and v["version"] == git("-C", str(tmp_path / "phone"), "rev-parse", "--short", "HEAD")
    assert app.update() == {"updated": False, "version": v["version"]} and not restarts
    (tmp_path / "dev" / "f.txt").write_text("2", encoding="utf-8")
    git("-C", str(tmp_path / "dev"), "commit", "-qam", "two")
    git("-C", str(tmp_path / "dev"), "push", "-q", "origin", "HEAD")
    r = app.update()
    assert r["updated"] and r["from"] == v["version"] and r["version"] != v["version"] and restarts == [1]
    (tmp_path / "up.git").rename(tmp_path / "gone.git")  # no connection to the server
    with pytest.raises(server.ApiError, match="Update failed"):
        app.update()


def test_folder_picker_stays_inside_storage(running):
    b, tmp = running["base"], running["tmp"]
    (tmp / "pics").mkdir(exist_ok=True)
    assert call(b, "/api/fs?path=" + urllib.parse.quote(str(tmp / "pics")))[0] == 200
    for outside in ("/etc", "/", str(tmp / ".." / "..")):
        s, r = call(b, "/api/fs?path=" + urllib.parse.quote(outside))
        assert s == 403 and "storage" in r["error"], outside
    s, r = call(b, "/api/folders", "POST", {"folders": ["/etc"], "collection": "x"})
    assert s == 403


def test_api_never_crashes_on_bad_input(running):
    """Every endpoint, fed missing, wrong and absurd input, answers with a 4xx and a readable message; never a 500."""
    b = running["base"]
    bodies = [None, {}, {"name": ""}, {"name": "x" * 5000, "type": "nonsense"}, {"url": 12}, {"style": "?", "format": "exe"},
              {"folders": "not a list"}, {"folders": ["/definitely/not/here"]}, {"ext_key": "nope:1"}, {"on": "maybe"}, [1, 2]]
    paths = {"id": ["999999", "0"], "name": ["NoSuchCollection", "%2e%2e"], "action": ["pause"]}
    crashes = []
    for method, rx, _ in server.ROUTES:
        if rx.pattern in ("^/api/update$",):
            continue  # real git: covered in its own test
        p = rx.pattern.strip("^$").replace("\\d+", "999999").replace("all|", "")
        p = re.sub(r"\(\?P<id>[^)]*\)", "999999", p)
        p = re.sub(r"\(\?P<name>[^)]*\)", "NoSuchCollection", p)
        p = re.sub(r"\(\?P<action>[^)]*\)", "pause", p)
        for body in (bodies if method != "GET" else [None]):
            for q in ("", "?q=%00&type=zzz&collection=&path=/etc/../..&limit=-5"):
                raw = json.dumps(body).encode() if body is not None else b"{not json"
                s, r = call(b, p + q, method, raw=raw)
                if s >= 500 or (s >= 400 and not (isinstance(r, dict) and r.get("error"))):
                    crashes.append((method, p + q, body, s, r))
    assert not crashes, crashes[:5]


JUNK = re.compile(r"\bundefined\b|\bNaN\b|\[object Object\]|Traceback|TypeError|AttributeError|KeyError|null\b")


def test_ui_every_screen_and_button_survives(page):
    """Visit every screen (also for things that do not exist) and press every button: no script error, no junk text,
    and the page always shows something useful."""
    pg, lib = page, page.running["lib"]
    tid = lib.one("SELECT id FROM titles ORDER BY id LIMIT 1")["id"]
    items = [r["id"] for r in lib.q("SELECT id FROM items ORDER BY id")]
    quote = lib.one("SELECT id FROM finds WHERE kind='quote' LIMIT 1")["id"]
    routes = ["#/", "#/import", "#/c/Anime", "#/c/Motivation", "#/c/Screenshots", "#/c/NoSuchCollection", f"#/t/{tid}", "#/t/999999",
              f"#/q/{quote}", "#/q/999999", "#/identify", "#/folder", "#/search", "#/filters", "#/progress", "#/check", "#/settings",
              "#/item/999999", "#/nonsense"] + [f"#/item/{i}" for i in items]
    problems = []
    for r in routes:
        pg.goto(pg.running["base"] + "/" + r)
        pg.wait_for_timeout(250)
        body = pg.inner_text("main") if pg.locator("main").count() else pg.inner_text("body")
        if not body.strip():
            problems.append((r, "empty screen"))
        if JUNK.search(body):
            problems.append((r, JUNK.search(body).group(0)))
        n = pg.locator("main button:visible").count()
        for k in range(min(n, 12)):
            pg.goto(pg.running["base"] + "/" + r)
            pg.wait_for_timeout(150)
            btns = pg.locator("main button:visible")
            if k >= btns.count():
                break
            label = (btns.nth(k).inner_text() or btns.nth(k).get_attribute("aria-label") or "").strip()
            if re.search(r"Update now|Remove|Delete", label):
                continue
            try:
                btns.nth(k).click(timeout=2000)
            except Exception:  # noqa: BLE001  covered or disabled: not a failure by itself
                continue
            pg.wait_for_timeout(300)
            if pg.locator("dialog[open]").count():
                pg.keyboard.press("Escape")
            text = pg.inner_text("body")
            if JUNK.search(text):
                problems.append((r, label, JUNK.search(text).group(0)))
    assert not pg.errors, pg.errors[:5]
    assert not problems, problems[:10]


XSS = '"><img src=x onerror="window.__xss=1"><svg onload="window.__xss=2">'


def test_ui_hostile_text_is_never_run(page):
    """Names, captions, comments and web results come from strangers: whatever they contain is shown as text."""
    pg, lib = page, page.running["lib"]
    tid = lib.upsert_title("web:evil", "Evil" + XSS, type="movie", year=2026, language="Tamil" + XSS, genres=["Drama" + XSS],
                           extra={"synopsis": "Story" + XSS, "url": "javascript:window.__xss=3",
                                  "where_to_watch": [{"site": "Bad" + XSS, "url": "javascript:window.__xss=4", "language": XSS}],
                                  "related": [{"relation": XSS, "name": "Rel" + XSS, "type": "movie", "year": 1, "ext_key": XSS}],
                                  "wikipedia": "javascript:window.__xss=5", "studios": [XSS], "cast": [XSS]})
    coll = "Coll" + XSS
    iid, _ = lib.add_item("reel:EVIL", "reel", "javascript:window.__xss=6", [coll], status="check")
    lib.merge_meta(iid, author="bad" + XSS, caption=XSS, transcript=XSS, steps={"Web" + XSS: {"ok": False, "detail": XSS}})
    lib.update_item(iid, error=XSS)
    lib.add_find(iid, "title", title_id=tid, name_raw=XSS, source=XSS, evidence=XSS, detail=XSS, confidence="check",
                 alts=[{"ext_key": XSS, "name": XSS, "type": "movie", "year": 2}])
    qid, _ = lib.add_item("reel:EVILQ", "reel", "javascript:window.__xss=7", ["Motivation"], status="done")
    lib.add_find(qid, "quote", quote="Quote" + XSS, source="speech", confidence="confirmed", media=XSS, detail=XSS)
    quote = lib.one("SELECT id FROM finds WHERE item_id=? AND kind='quote'", (qid,))["id"]
    for r in ["#/", f"#/t/{tid}", f"#/item/{iid}", f"#/c/{urllib.parse.quote(coll)}", "#/c/Motivation", f"#/q/{quote}",
              "#/check", "#/search", "#/progress"]:
        pg.goto(pg.running["base"] + "/" + r)
        pg.wait_for_timeout(400)
        assert pg.evaluate("window.__xss === undefined"), r
        assert pg.locator("main img[src='x'], main svg[onload]").count() == 0, r
        bad = pg.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(h => /^\\s*javascript:/i.test(h))")
        assert not bad, (r, bad)
    pg.goto(pg.running["base"] + f"/#/t/{tid}")
    pg.get_by_text("Evil" + XSS).first.wait_for()  # shown as plain text


def test_csv_export_neutralises_formulas(running):
    lib = running["lib"]
    tid = lib.upsert_title("web:f", '=HYPERLINK("http://evil.example","x")', type="movie")
    iid, _ = lib.add_item("reel:F1", "reel", "https://www.instagram.com/reel/F1/", ["Movies"], status="done")
    lib.add_find(iid, "title", title_id=tid, name_raw="x", source="text", confidence="confirmed")
    s, body = call(running["base"], "/api/export.csv")
    text = body.decode() if isinstance(body, bytes) else body
    assert s == 200 and "'=HYPERLINK" in text and "\n=HYPERLINK" not in text


def test_debug_reports_image_for_lens_and_ai_setting(running):
    b, lib, app = running["base"], running["lib"], running["app"]
    shot = lib.one("SELECT id FROM items WHERE kind='image' LIMIT 1")["id"]
    s, r = call(b, f"/api/items/{shot}/debug")
    text = r["text"]
    assert s == 200 and text.startswith(f"Reel Shelf debug report: item {shot}") and "version:" in text and "steps:" in text
    assert str(running["tmp"]) not in text  # file names only, never full folder paths
    s, r = call(b, "/api/debug")
    assert s == 200 and "items: " in r["text"] and "recent problems:" in r["text"]
    s, body = call(b, f"/api/items/{shot}/image")
    assert s == 200 and body[:3] == b"\xff\xd8\xff"  # the original picture, for Google Lens
    reel = lib.one("SELECT id FROM items WHERE kind='reel' LIMIT 1")["id"]
    assert call(b, f"/api/items/{reel}/image")[0] == 404 and call(b, "/api/items/999999/debug")[0] == 404
    assert app.settings()["ai"] is False                                   # AI guesses are off unless turned on
    assert call(b, "/api/settings", "POST", {"ai": True})[1]["ai"] is True and app.engine.ai is True
    call(b, "/api/settings", "POST", {"ai": False})
    assert app.engine.ai is False


def test_ui_not_found_offers_lens_and_debug_report(page):
    pg = page
    pg.goto(pg.running["base"] + "/#/identify")
    img = pg.running["tmp"] / "plain.png"
    Image.new("RGB", (90, 160), (30, 160, 60)).save(img)
    pg.set_input_files("#pic", str(img))
    pg.wait_for_url("**#/item/*")
    pg.get_by_role("heading", name="Not found").wait_for(timeout=20000)
    pg.get_by_role("button", name="Search with Google Lens").wait_for()
    pg.get_by_role("button", name="Copy debug report").click()
    pg.get_by_text("Debug report copied").wait_for()
    copied = pg.evaluate("navigator.clipboard.readText()")
    assert copied.startswith("Reel Shelf debug report: item") and "Read text" in copied
    pg.goto(pg.running["base"] + "/#/settings")
    pg.get_by_role("switch", name="AI guesses").wait_for()
    assert pg.get_by_role("switch", name="AI guesses").get_attribute("aria-checked") == "false"
