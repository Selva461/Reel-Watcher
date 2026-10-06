"""Part 4: the app. HTTP API tests, then real-browser UI tests at phone size (Chromium via Playwright).
No network and no AI model: the engine runs with online lookups off."""
import json
import os
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from reel_watcher import demo, server, study, worker

CHROME = next((p for p in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",) if os.path.exists(p)), None) or \
    shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")


@pytest.fixture
def running(tmp_path, monkeypatch):
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


def test_api_folders_and_identify_image(running):
    b, tmp = running["base"], running["tmp"]
    folder = tmp / "pics"
    for n in range(5):
        p = folder / f"s{n}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (90, 160), (n * 50, 20, 200 - n * 30)).save(p)
    fs = call(b, "/api/fs?path=" + urllib.request.quote(str(tmp)))[1]
    assert any(d["name"] == "pics" for d in fs["dirs"]) and call(b, "/api/fs?path=" + urllib.request.quote(str(folder)))[1]["images"] == 5
    assert call(b, "/api/folders", "POST", {"folders": ["/definitely/missing"]})[0] == 400
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
        req = urllib.request.Request(base + "/?t=secret123")
        with urllib.request.urlopen(req) as r:
            assert "rs_token=secret123" in r.headers.get("Set-Cookie", "")
    finally:
        srv.shutdown()


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
    pg.wait_for_function("document.querySelectorAll('.list-item').length === 1")
    assert pg.locator(".list-item .title").inner_text() == "Pluto"
    pg.get_by_role("button", name="All", exact=True).click()
    pg.wait_for_function("document.querySelectorAll('.list-item').length === 3")
    pg.get_by_text("Frieren: Beyond Journey's End").click()
    pg.get_by_role("heading", name="Frieren: Beyond Journey's End").wait_for()
    assert pg.get_by_text("28 episodes").is_visible() and pg.get_by_text("Number one has to be Frieren").first.is_visible()
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
    pg.wait_for_function("document.querySelectorAll('#results .list-item').length === 1")
    assert pg.locator("#results .title").inner_text() == "Parasite"
    pg.get_by_role("button", name="Tamil").click()
    pg.wait_for_function("document.querySelectorAll('#results .list-item').length === 2")
    pg.get_by_role("button", name="All").first.click()
    pg.fill("#q", "idiots")
    pg.wait_for_function("document.querySelectorAll('#results .list-item').length === 1 && document.querySelector('#results .title').textContent === '3 Idiots'")
    pg.fill("#q", "")
    pg.wait_for_function("document.querySelectorAll('#results .list-item').length > 5")
    pg.get_by_role("link", name="All filters").click()
    pg.get_by_role("heading", name="Filters").wait_for()
    pg.locator('[data-k="type"][data-v="anime"]').click()
    pg.wait_for_selector('[data-k="type"][data-v="anime"][aria-pressed="true"]')
    pg.locator('[data-k="found_from"][data-v="Comment"]').click()
    pg.get_by_role("link", name="Show 1 result").wait_for()
    pg.select_option("#sort", "az")
    pg.get_by_role("link", name="Show 1 result").click()
    pg.wait_for_function("document.querySelectorAll('#results .list-item').length === 1")
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
    pg.wait_for_function("document.querySelectorAll('.list-item').length === 1")
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
    pg.wait_for_function(f"document.querySelector('#fav').getAttribute('aria-pressed') !== '{before}'")
    assert pg.get_by_role("link", name="Next").count() + pg.get_by_role("link", name="Previous").count() == 1
    no_side_scroll(pg)


def test_ui_check_identify_and_read(page):
    pg = page
    pg.get_by_text("2 unsure guesses to confirm").click()
    pg.get_by_role("heading", name="Check this").wait_for()
    pg.get_by_role("button", name="Not Berserk").click()
    pg.get_by_text("Removed").wait_for()
    pg.locator("[data-ok]").first.click()
    pg.get_by_text("Confirmed").wait_for()
    pg.locator("[data-fix]").first.click()
    pg.fill("#rn", "Dark")
    pg.select_option("#rt", "series")
    pg.get_by_role("button", name="Save").click()
    pg.get_by_text("Nothing to check. Nice.").wait_for()

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
    pg.get_by_role("heading", name="No match yet").wait_for(timeout=20000)  # offline + no AI: nothing to confirm
    pg.get_by_role("button", name="Type the name myself").wait_for()

    pg.goto(pg.running["base"] + "/#/c/Movies")
    pg.get_by_role("button", name="Read this collection (1 reels)").click()
    pg.get_by_text("Reading 1 reels in the background").wait_for()
    pg.locator("nav.tabs").get_by_text("Jobs").click()
    pg.get_by_role("heading", name="Running in background").wait_for()
    assert pg.get_by_text("Read Movies").count() >= 1
    no_side_scroll(pg)


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
    pg.wait_for_function("[...document.querySelectorAll('.card')].some(c => c.textContent.includes('Scan Screenshots') && c.textContent.includes('Done'))", timeout=20000)
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
    pg.goto(pg.running["base"] + "/#/settings")
    sw = pg.get_by_role("switch", name="Online lookups")
    assert sw.get_attribute("aria-checked") == "false"
    sw.click()
    pg.get_by_text("Online lookups on").wait_for()
    assert pg.running["app"].settings()["online"] is True
    assert Path(pg.running["lib"].dir / "settings.json").exists()
