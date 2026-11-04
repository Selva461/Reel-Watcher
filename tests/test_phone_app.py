"""The Reel Shelf that runs inside the Android app (android/app-shell/app/src/main/assets/local), no Termux.

The page is driven in Chromium at phone size with a fake window.RN (the Java bridge): storage, shared items,
Instagram pages, the on-phone AI model and file saving are all simulated. No network, no model."""
import functools
import http.server
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from test_app import CHROME

LOCAL = Path(__file__).resolve().parents[1] / "android" / "app-shell" / "app" / "src" / "main" / "assets" / "local"

# The fake bridge. window.__rn holds its state so tests can set it up and look at it.
FAKE_RN = r"""
(() => {
  const st = window.__rn = Object.assign({
    db: "", settings: "{}", shared: [], pages: {}, model: { ready: false, partial: 0, installed: [] },
    answers: [], calls: [], saved: [], copied: "", sharedOut: [], opened: [], stopped: 0,
  }, JSON.parse(sessionStorage.getItem("rn") || "{}"));
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  const later = (fn) => setTimeout(fn, 5);
  window.RN = {
    load: () => st.db,
    store: (j) => { st.db = j; keep(); return true; },
    takeShared: () => { const s = JSON.stringify(st.shared.map((t) => ({ text: t, at: 1 }))); st.shared = []; keep(); return s; },
    getSettings: () => st.settings,
    setSettings: (j) => { st.settings = j; keep(); },
    copy: (t) => { st.copied = t; keep(); },
    shareText: (t, title) => { st.sharedOut.push([title, t]); keep(); },
    openUrl: (u) => { st.opened.push(u); keep(); },
    openServerMode: () => { st.opened.push("server"); keep(); },
    allowWork: () => {},
    stopModel: () => { st.stopped++; keep(); },
    modelInfo: (name) => JSON.stringify({ file: name, ready: st.model.ready, bytes: st.model.ready ? 1.6e9 : 0, partial: st.model.partial,
      downloading: false, backend: st.model.ready ? "gpu" : "", installed: st.model.installed }),
    deleteModel: () => { st.model.ready = false; keep(); return true; },
    fetchPage: (id, url) => { st.calls.push(["fetchPage", url]); keep(); later(() => {
      const p = Object.keys(st.pages).find((k) => url.includes(k));
      p ? rnDone(id, true, st.pages[p]) : rnDone(id, false, "Instagram answered 429"); }); },
    generate: (id, prompt, opts) => { st.calls.push(["generate", prompt, JSON.parse(opts)]); keep(); later(() => {
      const a = st.answers.shift();
      a ? rnDone(id, true, JSON.stringify({ text: a, backend: "gpu", ms: 10 })) : rnDone(id, false, "The AI model failed: out of memory"); }); },
    downloadModel: (id, url, name) => { st.calls.push(["download", url, name]); keep();
      later(() => rnProgress("download", 800e6, 1.6e9)); later(() => { st.model.ready = true; keep(); rnDone(id, true, "ready"); }); },
    pickModel: (id) => later(() => rnDone(id, false, "cancelled")),
    postJson: (id, url, body) => { st.calls.push(["postJson", url, JSON.parse(body)]); keep(); later(() => {
      st.player ? rnDone(id, true, JSON.stringify(st.player)) : rnDone(id, false, "YouTube answered 403"); }); },
    openInstagram: () => { st.opened.push("instagram-export"); keep(); },
    workUpdate: (title, text, d, t) => { st.work = (st.work || []).concat([["update", title]]); keep(); },
    workEnd: () => { st.work = (st.work || []).concat([["end"]]); keep(); },
    isNight: () => !!st.night,
    nightDone: () => { st.nightDone = (st.nightDone || 0) + 1; keep(); },
    nightRunInfo: () => JSON.stringify(st.nightRun || { on: true, hour: 0, minBattery: 40, exact: true }),
    setNightRun: (on, hour, bat) => { st.nightRun = { on, hour, minBattery: bat, exact: true }; keep(); },
    instagramWaitingSince: () => st.igWaiting || 0,
    dismissInstagramWaiting: () => { st.igWaiting = 0; keep(); },
    takeInstagramExport: () => { const s = st.igExport ? JSON.stringify(st.igExport) : ""; st.igExport = null; keep(); return s; },
    signOutInstagram: () => { st.opened.push("ig-signout"); keep(); },
    // the watchlist's online check: st.verifyAnswers is what the phone "finds"; st.verifyPending waits to be taken
    verifyNow: (id) => { st.calls.push(["verifyNow"]); keep(); later(() => rnProgress("verify", 1, 2)); later(() => {
      st.verifyPending = Object.assign(st.verifyPending || {}, st.verifyAnswers || {}); keep();
      rnDone(id, true, JSON.stringify({ checked: Object.keys(st.verifyAnswers || {}).length, offline: false, stopped: false })); }); },
    stopVerify: () => { st.calls.push(["stopVerify"]); keep(); },
    takeVerified: () => { const s = JSON.stringify(st.verifyPending || {}); st.verifyPending = {}; keep(); return s; },
    setNightly: (on) => { st.nightly = on; keep(); },
    nightlyInfo: () => JSON.stringify({ on: !!st.nightly, scheduled: !!st.nightly }),
    saveFile: (id, name, mime, text) => { st.saved.push({ name, mime, text }); keep(); later(() => rnDone(id, true, "Downloads/ReelShelf/" + name)); },
  };
  if (st.ytApps) window.RN.postYoutube = (id, url, body, client) => {  // the newer app: asks as one of YouTube's apps
    st.calls.push(["postYoutube", url, JSON.parse(body), client]); keep(); later(() => {
      const a = st.ytApps[/get_transcript/.test(url) ? "transcript" : client];
      a ? rnDone(id, true, JSON.stringify(a)) : rnDone(id, false, "YouTube answered 403"); }); };
})();
"""

ANSWER = """Here is the breakdown:

**TOPIC:** Hardcoded secrets in mobile apps

**POINTS:**
1. A researcher scanned the app with AI and found a database password in the code
2. It exposed 8.5M rewards members
- Tools: gitleaks found it in seconds

**MEANING:** Anything shipped inside an app can be read by anyone.

**USE IT FOR:** Checking my own apps before release

**TOOLS:** gitleaks, TruffleHog

**TAKEAWAY:** Keep secrets on the server and rotate leaked ones.

**TAGS:** #cybersecurity, #appsecurity, hardcodedpasswords
"""

EMBED = """<html><body><div class="Embed"><div class="Caption"><a class="CaptionUsername" href="#">creator_a</a>
Three free tools for <b>notes</b><br>1. Obsidian<br>2. Notion<script>window.__pwned = 1</script>
<div class="CaptionComments">View all 20 comments</div></div></div></body></html>"""


@pytest.fixture
def site():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(LOCAL))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


@pytest.fixture
def phone(site):
    if not CHROME:
        pytest.skip("Chromium not available")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(FAKE_RN)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if "Content Security Policy" in m.text or m.type == "error" else None)
        pg.on("dialog", lambda d: d.accept())

        def open_with(state=None, hash_="#/"):
            pg.goto(site + "#/blank")
            if state:
                pg.evaluate("s => sessionStorage.setItem('rn', JSON.stringify(s))", state)
            pg.goto(site + hash_)
            pg.reload()
            pg.wait_for_selector("#app > *")
        pg.open_with = open_with
        pg.rn = lambda: pg.evaluate("window.__rn")
        yield pg
        assert not errors, errors
        browser.close()


def db_of(pg):
    return json.loads(pg.rn()["db"] or '{"reels": []}')


# ---------------------------------------------------------------- the notes format, links and exports (pure helpers)

def test_parse_meta_ai_answer_and_links(phone):
    phone.open_with()
    n = phone.evaluate("a => Notes.parse(a)", ANSWER)
    assert n["topic"] == "Hardcoded secrets in mobile apps"
    assert n["points"] == ["A researcher scanned the app with AI and found a database password in the code",
                           "It exposed 8.5M rewards members", "Tools: gitleaks found it in seconds"]  # a dash line stays a point
    assert n["tools"] == ["gitleaks", "TruffleHog"] and n["use"] == ["Checking my own apps before release"]
    assert n["tags"] == ["cybersecurity", "appsecurity", "hardcodedpasswords"]
    assert phone.evaluate("Notes.parse('just some chat text')") is None
    again = phone.evaluate("a => Notes.parse(Notes.format(Notes.parse(a)))", ANSWER)
    assert again == n  # format and parse round-trip
    got = phone.evaluate("""Notes.links('look https://www.instagram.com/reel/ABC123xyz/?igsh=q and instagram.com/p/POST_99-x/ '
                           + 'https://www.instagram.com/reel/ABC123xyz/ again, https://www.instagram.com/someone/reel/DEF4567/')""")
    assert got == [{"code": "ABC123xyz", "url": "https://www.instagram.com/reel/ABC123xyz/", "source": "instagram"},
                   {"code": "POST_99-x", "url": "https://www.instagram.com/p/POST_99-x/", "source": "instagram"},
                   {"code": "DEF4567", "url": "https://www.instagram.com/reel/DEF4567/", "source": "instagram"}]
    yt = phone.evaluate("""Notes.links('https://youtu.be/dQw4w9WgXcQ https://www.youtube.com/watch?feature=x&v=abcdefghijk '
                          + 'https://m.youtube.com/shorts/dQw4w9WgXcQ')""")
    assert [x["code"] for x in yt] == ["yt-dQw4w9WgXcQ", "yt-abcdefghijk"] and yt[0]["url"] == "https://www.youtube.com/shorts/dQw4w9WgXcQ"
    two = phone.evaluate("t => Notes.splitAnswers(t).map(p => p.notes.topic)", ANSWER + "\n\nTOPIC: Second one\nPOINTS:\n- a\nTAGS: x")
    assert two == ["Hardcoded secrets in mobile apps", "Second one"]


def test_caption_read_from_embed_page_without_running_its_scripts(phone):
    phone.open_with()
    got = phone.evaluate("h => Notes.readPage(h)", EMBED)
    assert got == {"author": "creator_a", "caption": "Three free tools for notes\n1. Obsidian\n2. Notion"} or \
        (got["author"] == "creator_a" and got["caption"].startswith("Three free tools for notes\n1. Obsidian\n2. Notion"))
    og = '<meta property="og:description" content="1,204 likes, 33 comments - someone.here on May 2, 2026: &quot;Use Canva for thumbnails&quot;. ">'
    assert phone.evaluate("h => Notes.readPage(h)", og) == {"author": "someone.here", "caption": "Use Canva for thumbnails"}
    assert phone.evaluate("window.__pwned") is None


# ---------------------------------------------------------------- the app

def test_shared_reel_is_only_saved_then_start_reads_and_writes_notes(phone):
    phone.open_with({"shared": ["Check this https://www.instagram.com/reel/AAA111/?igsh=zz", "hello"],
                     "pages": {"AAA111/embed": EMBED}, "model": {"ready": True, "partial": 0, "installed": []},
                     "answers": [ANSWER]})
    phone.get_by_text("1 new reel saved").wait_for()
    st = phone.rn()
    assert not any(c[0] in ("fetchPage", "generate") for c in st["calls"])  # sharing only saves: no work until Start
    assert db_of(phone)["reels"][0]["status"] == "new"
    phone.get_by_role("button", name="Start: 1 reel").click()
    phone.get_by_role("heading", name="Done").wait_for()
    r = db_of(phone)["reels"][0]
    assert r["status"] == "done" and r["notes_by"] == "phone" and r["author"] == "creator_a"
    assert r["notes"]["topic"] == "Hardcoded secrets in mobile apps"
    gen = [c for c in phone.rn()["calls"] if c[0] == "generate"][0]
    assert "Obsidian" in gen[1] and "TOPIC:" in gen[1] and gen[2]["gpu"] is True and gen[2]["maxTokens"] == 800
    assert phone.rn()["stopped"] >= 1  # the model is freed as soon as the work is done
    work = phone.rn()["work"]  # a notification (with Stop) while it runs, gone as soon as it is done
    assert work[0] == ["update", "Writing reel notes"] and work[-1] == ["end"]
    phone.goto(phone.url.split("#")[0] + "#/")
    phone.get_by_text("Hardcoded secrets in mobile apps").click()
    phone.get_by_text("Notes by the on-phone AI (from the caption)").wait_for()
    phone.get_by_role("button", name="Copy notes").click()
    assert phone.rn()["copied"].startswith("TOPIC: Hardcoded secrets") and "Reel: https://www.instagram.com/reel/AAA111/" in phone.rn()["copied"]


def test_without_the_model_start_reads_captions_and_ask_meta_ai_files_the_answer(phone):
    phone.open_with({"shared": ["https://www.instagram.com/reel/BBB222/"], "pages": {"BBB222/embed": EMBED}})
    phone.get_by_role("button", name="Start: 1 reel").click()
    phone.get_by_role("heading", name="Done").wait_for()
    assert not any(c[0] == "generate" for c in phone.rn()["calls"])
    r = db_of(phone)["reels"][0]
    # no AI on the phone: quick notes are made from the caption with plain maths, so the reel is already searchable
    assert r["status"] == "done" and r["notes_by"] == "auto"
    assert "Obsidian" in " ".join(r["notes"]["points"]) and r["notes"]["tags"]
    phone.goto(phone.url.split("#")[0] + "#/r/BBB222")
    phone.get_by_role("button", name="Ask Meta AI").click()
    st = phone.rn()
    assert st["sharedOut"][0][0] == "Ask Meta AI"
    assert "https://www.instagram.com/reel/BBB222/" in st["copied"] and "TAKEAWAY:" in st["copied"]
    # Meta AI's answer is shared back to Reel Shelf (no link in it): it goes to the reel you just asked about
    phone.evaluate("a => { const s = window.__rn; s.shared.push(a); sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }", ANSWER)
    phone.get_by_text("1 Meta AI answer filed").wait_for()
    r = db_of(phone)["reels"][0]
    assert r["notes_by"] == "meta" and r["notes"]["tools"] == ["gitleaks", "TruffleHog"]


def test_custom_prompt_and_model_settings_are_used(phone):
    phone.open_with(hash_="#/settings")
    phone.locator("#prompt").fill("My master prompt for {link} please")
    phone.get_by_role("button", name="Save prompt").click()
    phone.get_by_role("button", name="CPU").click()
    phone.get_by_role("button", name="Long").click()
    s = json.loads(phone.rn()["settings"])
    assert s["prompt"] == "My master prompt for {link} please" and s["gpu"] is False and s["maxTokens"] == 1500
    phone.get_by_role("button", name="Download model").click()
    phone.get_by_text("The AI model is ready").wait_for()
    dl = [c for c in phone.rn()["calls"] if c[0] == "download"][0]
    assert dl[1].startswith("https://huggingface.co/litert-community/Qwen2.5-1.5B-Instruct/resolve/main/") and dl[2].endswith(".litertlm")
    phone.get_by_text("running on GPU").wait_for()
    phone.evaluate("() => { const s = window.__rn; s.shared.push('https://www.instagram.com/reel/CCC333/'); sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }")
    phone.goto(phone.url.split("#")[0] + "#/r/CCC333")
    phone.get_by_role("button", name="Ask Meta AI").click()
    assert phone.rn()["copied"] == "My master prompt for https://www.instagram.com/reel/CCC333/ please"


def test_bulk_paste_links_and_old_answers(phone):
    phone.open_with(hash_="#/add")
    phone.locator("#paste").fill("1 https://www.instagram.com/reel/R1aaaa/\n2 https://www.instagram.com/reel/R2bbbb/ 3 https://www.instagram.com/p/P3cccc/")
    phone.get_by_role("button", name="Save to shelf").click()
    phone.get_by_text("3 reels saved").wait_for()
    phone.goto(phone.url.split("#")[0] + "#/add")
    phone.locator("#paste").fill(ANSWER + "\nTOPIC: Second note\nPOINTS:\n1. one\nTAGS: ideas")
    phone.get_by_role("button", name="Save to shelf").click()
    phone.get_by_text("2 answers saved").wait_for()
    reels = db_of(phone)["reels"]
    assert len(reels) == 5 and sum(1 for r in reels if r.get("notes")) == 2
    phone.get_by_role("button", name="#ideas").click()
    assert phone.locator(".list-item").count() == 1


def test_instagram_export_zip_with_collections(phone, tmp_path):
    posts = {"saved_saved_media": [
        {"title": "creator_a", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/EXP001/", "timestamp": 1}}},
        {"title": "creator_b", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/EXP002/", "timestamp": 2}}}]}
    colls = {"saved_saved_collections": [
        {"title": "Collection", "string_map_data": {"Name": {"value": "Coding tips"}}},
        {"title": "creator_a", "string_map_data": {"Name": {"value": "creator_a", "href": "https://www.instagram.com/reel/EXP001/"}}}]}
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("your_instagram_activity/saved/saved_posts.json", json.dumps(posts))
        f.writestr("your_instagram_activity/saved/saved_collections.json", json.dumps(colls))
        f.writestr("media/big.jpg", b"x" * 1000)
    path = tmp_path / "instagram-export.zip"
    path.write_bytes(z.getvalue())
    phone.open_with(hash_="#/add")
    phone.locator("#zip").set_input_files(str(path))
    phone.get_by_text("2 new reels saved").wait_for()
    by = {r["code"]: r for r in db_of(phone)["reels"]}
    assert by["EXP001"]["collections"] == ["Coding tips"] and by["EXP001"]["author"] == "creator_a"
    assert by["EXP002"]["url"] == "https://www.instagram.com/p/EXP002/"


def _as_zip64(data, patch_offset_of=None):
    """Rewrites a small ZIP the way big exports are written: ZIP64 end records, and optionally one entry whose
    offset sits in a ZIP64 extra field. Python only writes these past 4 GB, so the test builds them by hand."""
    import struct
    eocd = data.rindex(b"PK\x05\x06")
    count, cd_size, cd_off = struct.unpack("<HII", data[eocd + 10:eocd + 20])
    cd = data[cd_off:cd_off + cd_size]
    out_cd = b""
    p = 0
    while p < len(cd):
        nlen, elen, clen = struct.unpack("<HHH", cd[p + 28:p + 34])
        head = bytearray(cd[p:p + 46])
        name = cd[p + 46:p + 46 + nlen]
        extra = cd[p + 46 + nlen:p + 46 + nlen + elen]
        comment = cd[p + 46 + nlen + elen:p + 46 + nlen + elen + clen]
        if patch_offset_of and name.decode().endswith(patch_offset_of):
            (loff,) = struct.unpack("<I", head[42:46])
            head[42:46] = struct.pack("<I", 0xFFFFFFFF)
            extra = extra + struct.pack("<HHQ", 1, 8, loff)
            head[30:32] = struct.pack("<H", len(extra))
        out_cd += bytes(head) + name + extra + comment
        p += 46 + nlen + elen + clen
    body = data[:cd_off] + out_cd
    rec_off = len(body)
    rec = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, count, count, len(out_cd), cd_off)
    loc = struct.pack("<IIQI", 0x07064B50, 0, rec_off, 1)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return body + rec + loc + end


def test_big_zip64_export_is_read(phone, tmp_path):
    posts = {"saved_saved_media": [
        {"title": "creator_z", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/BIG001/", "timestamp": 1}}}]}
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("media/big.jpg", b"x" * 5000)
        f.writestr("your_instagram_activity/saved/saved_posts.json", json.dumps(posts))
    data = _as_zip64(z.getvalue(), patch_offset_of="saved_posts.json")
    with zipfile.ZipFile(io.BytesIO(data)) as check:  # still a valid ZIP for other readers
        assert json.loads(check.read("your_instagram_activity/saved/saved_posts.json")) == posts
    path = tmp_path / "big-export.zip"
    path.write_bytes(data)
    phone.open_with(hash_="#/add")
    phone.locator("#zip").set_input_files(str(path))
    phone.get_by_text("1 new reel saved").wait_for()
    assert [r["code"] for r in db_of(phone)["reels"]] == ["BIG001"]


def test_overnight_run_does_everything_then_ends_the_notification(phone):
    phone.open_with({"shared": ["https://www.instagram.com/reel/NIG001/"], "pages": {"NIG001/embed": EMBED}, "answers": [ANSWER]}, "#/run")
    phone.get_by_role("button", name="Run everything overnight").click()
    phone.get_by_text("Backup saved to Downloads/ReelShelf/").wait_for()
    st = phone.rn()
    assert any(c[0] == "download" for c in st["calls"]) and any(c[0] == "generate" for c in st["calls"])
    assert db_of(phone)["reels"][0]["status"] == "done" and st["saved"][-1]["name"].startswith("reel-notes-")
    assert st["work"][0][1].startswith("Overnight run") and st["work"][-1] == ["end"]


def test_nightly_run_files_the_day_and_skips_reels_already_known(phone):
    done = {"code": "OLD001", "url": "https://www.instagram.com/reel/OLD001/", "status": "done", "added_at": 1,
            "notes": {"topic": "Old"}, "notes_by": "meta", "collections": []}
    posts = {"saved_saved_media": [{"title": "c", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/NEW001/"}}},
                                   {"title": "c", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/OLD001/"}}}]}
    phone.open_with({"night": True, "db": json.dumps({"reels": [done], "inbox": []}),
                     "shared": ["https://www.instagram.com/reel/NEW001/", "https://www.instagram.com/reel/OLD001/"],
                     "igExport": [{"name": "saved_posts.json", "text": json.dumps(posts)}],
                     "pages": {"NEW001/embed": EMBED}})
    phone.wait_for_function("window.__rn.nightDone >= 1")
    st = phone.rn()
    reels = {r["code"]: r for r in db_of(phone)["reels"]}
    assert sorted(reels) == ["NEW001", "OLD001"]  # shared and imported twice: still one each
    assert reels["OLD001"]["notes_by"] == "meta"  # already done: not touched
    fetched = [c[1] for c in st["calls"] if c[0] == "fetchPage"]
    assert fetched and all("NEW001" in u for u in fetched)
    assert not any(c[0] == "download" for c in st["calls"])  # no big model download at night
    assert st["work"][-1] == ["end"] and db_of(phone)["lastNight"]["log"]


def test_nightly_run_settings(phone):
    phone.open_with(hash_="#/settings")
    phone.locator("#nrHour").select_option("1")
    phone.locator("#nrBat").select_option("50")
    assert phone.rn()["nightRun"] == {"on": True, "hour": 1, "minBattery": 50, "exact": True}


def test_waiting_for_instagram_export_reminder(phone):
    import time
    phone.open_with({"igWaiting": int(time.time() * 1000) - 3 * 3600 * 1000})
    card = phone.locator("#igwait")
    card.get_by_text("3 hours ago").wait_for()
    card.get_by_role("button", name="Check now").click()
    assert "instagram-export" in phone.rn()["opened"]
    phone.goto(phone.url.split("#")[0] + "#/add")
    phone.locator("#igwait").get_by_role("button", name="Hide").click()
    assert phone.locator("#igwait").count() == 0 and not phone.rn()["igWaiting"]
    phone.goto(phone.url.split("#")[0] + "#/")
    phone.get_by_text("Your reel notes").wait_for()
    assert phone.locator("#igwait").count() == 0


def test_exports_and_leaving_the_app_stops_work(phone):
    phone.open_with({"shared": ["https://www.instagram.com/reel/DDD444/", ANSWER + "\nhttps://www.instagram.com/reel/DDD444/"]})
    phone.goto(phone.url.split("#")[0] + "#/settings")
    phone.get_by_role("button", name="Save JSON").click()
    phone.get_by_text("Saved to Downloads/ReelShelf/").wait_for()
    saved = phone.rn()["saved"][0]
    data = json.loads(saved["text"])
    assert saved["name"].endswith(".json") and data["count"] == 1
    assert data["reels"][0]["topic"] == "Hardcoded secrets in mobile apps" and data["reels"][0]["url"] == "https://www.instagram.com/reel/DDD444/"
    phone.get_by_role("button", name="Save Markdown").click()
    for _ in range(100):
        if len(phone.rn()["saved"]) == 2:
            break
        phone.wait_for_timeout(50)
    assert phone.rn()["saved"][1]["text"].startswith("# Reel notes")
    # a reel waiting for the on-phone AI; the app leaves the screen in the middle: everything stops
    phone.evaluate("""() => { const s = window.__rn; s.model.ready = true; s.answers = [];
        s.shared.push('https://www.instagram.com/reel/EEE555/'); s.pages = {'EEE555/embed': '<div class=Caption>' + 'long caption '.repeat(10) + '</div>'};
        sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }""")
    phone.evaluate("""() => { RN.generate = (id) => { window.__genId = id; }; }""")  # the answer never comes back on its own
    phone.goto(phone.url.split("#")[0] + "#/run")
    phone.get_by_role("button", name="Start: 1 reel").click()
    for _ in range(100):
        if phone.evaluate("() => !!window.__genId"):
            break
        phone.wait_for_timeout(50)
    phone.evaluate("() => { onAppPause(); rnDone(window.__genId, false, 'stopped'); }")
    phone.get_by_role("heading", name="Paused").wait_for()
    r = next(x for x in db_of(phone)["reels"] if x["code"] == "EEE555")
    assert r["status"] == "new" and not r.get("notes")


def test_hostile_text_is_shown_as_text(phone):
    evil = "TOPIC: <img src=x onerror=window.__pwned=1>\nPOINTS:\n1. <script>window.__pwned=2</script>\nTAGS: <b>x</b>"
    phone.open_with({"shared": ["https://www.instagram.com/reel/FFF666/"]})
    phone.goto(phone.url.split("#")[0] + "#/add")
    phone.locator("#paste").fill(evil)
    phone.get_by_role("button", name="Save to shelf").click()
    phone.wait_for_selector(".list-item")
    phone.locator(".list-item").first.click()
    phone.get_by_text("<img src=x onerror=window.__pwned=1>").first.wait_for()
    assert phone.evaluate("window.__pwned") is None
    assert phone.evaluate("document.documentElement.scrollWidth") <= 390


def test_same_look_as_the_old_app():
    """The built-in app reuses the old app's stylesheet unchanged (copied into the APK's assets)."""
    old = Path(__file__).resolve().parents[1] / "src" / "reel_watcher" / "webapp" / "app.css"
    assert (LOCAL / "app.css").read_text(encoding="utf-8") == old.read_text(encoding="utf-8")
    for f in LOCAL.iterdir():
        assert chr(0x2014) not in f.read_text(encoding="utf-8"), f"em dash in {f.name}"


# ---------------------------------------------------------------- YouTube, batch Meta AI, the library, Instagram export

WATCH = '<html><script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123"});</script></html>'
PLAYER = {
    "playabilityStatus": {"status": "OK"},
    "videoDetails": {"title": "3 ways to keep API keys out of your app", "author": "Dev Tips", "shortDescription": "Secrets belong on the server."},
    "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
        {"baseUrl": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&fmt=srv3", "languageCode": "en", "kind": "asr"}]}},
}
TIMED = """<?xml version="1.0" encoding="utf-8" ?><transcript>
<text start="0" dur="2">First, never put the key in the app &amp;amp; rotate it.</text>
<text start="2" dur="3">Second, use a server proxy &lt;b&gt;always&lt;/b&gt;.</text>
<text start="5" dur="2">Third, scan with gitleaks.</text></transcript>"""


def test_youtube_short_reads_the_spoken_words_and_writes_notes(phone):
    phone.open_with({"shared": ["look https://youtube.com/shorts/dQw4w9WgXcQ?si=abc"], "model": {"ready": True, "partial": 0, "installed": []},
                     "pages": {"youtube.com/watch": WATCH, "api/timedtext": TIMED}, "player": PLAYER, "answers": [ANSWER]})
    phone.get_by_role("button", name="Start: 1 reel").click()
    phone.get_by_role("heading", name="Done").wait_for()
    st = phone.rn()
    post = next(c for c in st["calls"] if c[0] == "postJson")
    assert post[1] == "https://www.youtube.com/youtubei/v1/player?key=AIzaTestKey_123" and post[2]["videoId"] == "dQw4w9WgXcQ"
    assert any(c[0] == "fetchPage" and "fmt=srv3" not in c[1] and "timedtext" in c[1] for c in st["calls"])
    prompt = next(c for c in st["calls"] if c[0] == "generate")[1]
    assert "never put the key in the app & rotate it" in prompt and "Second, use a server proxy always." in prompt
    assert "3 ways to keep API keys" in prompt
    r = db_of(phone)["reels"][0]
    assert r["code"] == "yt-dQw4w9WgXcQ" and r["notes_by"] == "phone" and r["author"] == "Dev Tips"
    phone.goto(phone.url.split("#")[0] + "#/r/yt-dQw4w9WgXcQ")
    phone.get_by_role("button", name="Open in YouTube").wait_for()
    phone.get_by_text("What is said (from YouTube's captions)").wait_for()


def test_ask_meta_ai_about_several_reels_in_one_message(phone):
    codes = ["AAA111", "BBB222", "CCC333"]
    db = {"reels": [{"code": c, "url": f"https://www.instagram.com/reel/{c}/", "status": "new", "added_at": 1} for c in codes], "inbox": []}
    phone.open_with({"db": json.dumps(db)})
    assert phone.get_by_role("button", name="Ask Meta AI about 3 reels at once").count() == 0  # off unless you switch it on
    phone.open_with({"db": json.dumps(db), "settings": json.dumps({"metaAi": True})})
    phone.get_by_role("button", name="Ask Meta AI about 3 reels at once").click()
    title, text = phone.rn()["sharedOut"][0]
    assert title == "Ask Meta AI" and all(f"https://www.instagram.com/reel/{c}/" in text for c in codes) and "REEL:" in text
    # Meta AI answers all three in one message; sharing it back files each part under its own reel
    one = lambda c, topic: f"REEL: https://www.instagram.com/reel/{c}/\nTOPIC: {topic}\nPOINTS:\n1. point about {topic}\nTAGS: x, y\n"
    answer = one("AAA111", "Alpha") + "\n" + one("BBB222", "Bravo") + "\n" + one("CCC333", "Charlie")
    phone.evaluate("a => { const s = window.__rn; s.shared.push(a); sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }", answer)
    phone.get_by_text("3 Meta AI answers filed").wait_for()
    topics = {r["code"]: r["notes"]["topic"] for r in db_of(phone)["reels"]}
    assert topics == {"AAA111": "Alpha", "BBB222": "Bravo", "CCC333": "Charlie"}


def _library():
    mk = lambda c, topic, pts, tags, tools=(): {"code": c, "url": f"https://www.instagram.com/reel/{c}/", "status": "done", "added_at": 1,
                                                 "notes_by": "meta", "notes": {"topic": topic, "points": pts, "tags": tags, "tools": list(tools)}}
    return {"reels": [
        mk("GYM001", "Chest workout at the gym", ["Bench press 3 sets of 8", "Rest 90 seconds"], ["fitness", "gym"]),
        mk("SEC001", "Hardcoded passwords leak user data", ["Never hardcode secrets in the app", "Rotate any leaked credential"], ["cybersecurity"], ["gitleaks"]),
        mk("SEC002", "Keep API keys on a server", ["The app calls your server, the server holds the key"], ["security", "apikeys"]),
        mk("FOOD01", "High protein breakfast", ["Eggs and oats, 40g protein"], ["diet"]),
    ], "inbox": []}


def test_library_search_ranks_allows_typos_and_similar_words(phone):
    phone.open_with({"db": json.dumps(_library())})
    order = lambda q: phone.evaluate("q => Notes.search(JSON.parse(window.__rn.db).reels, q).map(x => x.reel.code)", q)
    assert order("hardcoded passwords")[0] == "SEC001"
    assert order("pasword")[0] == "SEC001"            # a typo
    assert order("credential")[0] == "SEC001"         # in a point
    assert "SEC002" in order("secret")                # a similar word (key)
    assert order("exercise") == ["GYM001"]            # a synonym, not in the notes
    assert order("nutrition") == ["FOOD01"]
    related = phone.evaluate("() => { const rs = JSON.parse(window.__rn.db).reels; return Notes.related(rs, rs[1]).map(x => x.reel.code); }")
    assert related[:1] == ["SEC002"]
    # the shelf search box uses the same ranking
    phone.fill("#q", "pasword")
    assert phone.locator("#list .list-item").count() == 1
    phone.goto(phone.url.split("#")[0] + "#/r/SEC001")
    phone.get_by_role("heading", name="Related reels").wait_for()


def test_ask_your_library_answers_from_your_notes(phone):
    phone.open_with({"db": json.dumps(_library()), "model": {"ready": True, "partial": 0, "installed": []},
                     "answers": ["Never hardcode secrets [1] and keep keys on a server [2]."]}, "#/ask")
    phone.fill("#aq", "how do I keep api keys safe")
    phone.press("#aq", "Enter")
    phone.get_by_text("[1] Keep API keys on a server").wait_for()
    phone.get_by_role("button", name="Ask any AI with these notes").click()
    assert "Question: how do I keep api keys safe" in phone.rn()["copied"]
    phone.get_by_role("button", name="Answer with phone AI").click()
    phone.get_by_text("Answer from your notes").wait_for()
    prompt = next(c for c in phone.rn()["calls"] if c[0] == "generate")[1]
    assert "The app calls your server, the server holds the key" in prompt
    assert phone.locator('.pre a[href="#/r/SEC002"]', has_text="[1]").count() == 1


def test_saved_reels_come_back_from_the_in_app_instagram_page(phone):
    phone.open_with(hash_="#/add")
    phone.get_by_role("button", name="Get my saved reels from Instagram").click()
    assert phone.rn()["opened"] == ["instagram-export"]
    saved = {"saved_saved_media": [{"title": "creator_a", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/IGX001/", "timestamp": 1}}}]}
    colls = {"saved_saved_collections": [{"title": "Collection", "string_map_data": {"Name": {"value": "Tech"}}},
                                         {"title": "creator_a", "string_map_data": {"Name": {"value": "creator_a", "href": "https://www.instagram.com/reel/IGX001/"}}}]}
    parts = [{"name": "saved_collections.json", "text": json.dumps(colls)}, {"name": "saved_posts.json", "text": json.dumps(saved)}]
    phone.evaluate("p => { const s = window.__rn; s.igExport = p; sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }", parts)
    phone.get_by_text("From Instagram: 1 new reel saved").wait_for()
    r = db_of(phone)["reels"][0]
    assert r["code"] == "IGX001" and r["added_by"] == "export" and r["collections"] == ["Tech"]
    assert not any(c[0] in ("fetchPage", "generate") for c in phone.rn()["calls"])  # importing does no other work


# ---------------------------------------------------------------- YouTube: when YouTube blocks one way, the next one is tried

def yt_player(track_url, lang="en", kind="asr", translatable=True):
    return {"playabilityStatus": {"status": "OK"},
            "videoDetails": {"title": "Keep keys safe", "author": "Dev Tips", "shortDescription": "Secrets belong on the server."},
            "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
                {"baseUrl": track_url, "languageCode": lang, "kind": kind, "isTranslatable": translatable}]}}}


SAID = "Never put the key in the app. Use a server proxy. Scan with gitleaks before you ship."
XML_SAID = f'<transcript><text start="0" dur="3">{SAID}</text></transcript>'


def run_short(phone, state):
    state = {"shared": ["https://youtube.com/shorts/dQw4w9WgXcQ?si=abc"], "pages": {}, **state}
    state["pages"].setdefault("youtube.com/watch", WATCH)
    phone.open_with(state)
    phone.get_by_role("button", name="Start: 1 reel").click()
    phone.get_by_role("heading", name="Done").wait_for()
    return db_of(phone)["reels"][0], phone.rn()["calls"]


def test_youtube_tries_the_next_app_when_captions_come_back_empty(phone):
    r, calls = run_short(phone, {
        "ytApps": {"ios": yt_player("https://www.youtube.com/api/timedtext?v=1&c=IOS&exp=xpe&fmt=srv3"),
                   "android": yt_player("https://www.youtube.com/api/timedtext?v=1&c=ANDROID")},
        "pages": {"c=IOS": "", "c=ANDROID": XML_SAID}})
    apps = [c[3] for c in calls if c[0] == "postYoutube"]
    assert apps == ["ios", "android"]
    ios = next(c for c in calls if c[0] == "postYoutube")[2]
    assert ios["context"]["client"]["clientName"] == "IOS" and ios["videoId"] == "dQw4w9WgXcQ"
    assert not any(c[0] == "fetchPage" and "fmt=" in c[1] for c in calls)
    assert r["transcript"] == SAID and r["transcript_via"] == "android" and r["title"] == "Keep keys safe"
    assert r["notes_by"] == "auto" and r["notes"]["points"]  # no AI model: notes made from the words, without AI


def test_youtube_other_language_is_translated_to_english_or_kept(phone):
    tamil = yt_player("https://www.youtube.com/api/timedtext?v=1&lang=ta", lang="ta")
    r, calls = run_short(phone, {"ytApps": {"ios": tamil}, "pages": {"tlang=en": XML_SAID}})
    assert any("lang=ta&tlang=en" in c[1] for c in calls if c[0] == "fetchPage") and r["transcript_lang"] == "en"
    # the translation is refused: the original words are used
    r, calls = run_short(phone, {"ytApps": {"ios": tamil}, "pages": {"tlang=en": "", "lang=ta": XML_SAID}})
    assert r["transcript"] == SAID and r["transcript_lang"] == "ta"
    # the setting "the video's own language": no translation asked
    r, calls = run_short(phone, {"ytApps": {"ios": tamil}, "pages": {"lang=ta": XML_SAID}, "settings": json.dumps({"ytLang": "orig"})})
    assert not any("tlang" in c[1] for c in calls if c[0] == "fetchPage") and r["transcript_lang"] == "ta"


def test_youtube_falls_back_to_the_watch_page_then_the_transcript_panel(phone):
    page_player = yt_player("https://www.youtube.com/api/timedtext?v=1&from=page")
    watch = ('<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123", "INNERTUBE_CONTEXT_CLIENT_VERSION": "2.20261101.00.00", '
             '"VISITOR_DATA": "Cgt2aXNpdG9y"});var ytInitialPlayerResponse = ' + json.dumps(page_player) + ';</script>'
             '<script>var ytInitialData = {"engagementPanels": [{"getTranscriptEndpoint": {"params": "CgtkUXc0dzlXZ1hjUQ%3D%3D"}}]};</script>')
    bot = {"playabilityStatus": {"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm you are not a bot"}}
    r, calls = run_short(phone, {"ytApps": {"ios": bot, "android": bot}, "pages": {"youtube.com/watch": watch, "from=page": XML_SAID}})
    assert r["transcript_via"] == "page" and r["title"] == "Keep keys safe"
    panel = {"actions": [{"updateEngagementPanelAction": {"content": {"transcriptRenderer": {"body": {"segments": [
        {"transcriptSegmentRenderer": {"startMs": "0", "endMs": "1500", "snippet": {"runs": [{"text": "never put the key in the app"}]}}},
        {"transcriptSegmentRenderer": {"startMs": "2500", "endMs": "4000", "snippet": {"runs": [{"text": "use a server proxy"}]}}}]}}}}}]}
    r, calls = run_short(phone, {"ytApps": {"ios": bot, "android": bot, "transcript": panel},
                                 "pages": {"youtube.com/watch": watch, "from=page": ""}})
    req = next(c for c in calls if c[0] == "postYoutube" and "get_transcript" in c[1])
    assert req[3] == "web" and req[2]["params"] == "CgtkUXc0dzlXZ1hjUQ==" and req[2]["context"]["client"]["visitorData"] == "Cgt2aXNpdG9y"
    assert r["transcript"] == "never put the key in the app\nuse a server proxy" and r["transcript_via"] == "transcript panel"


def test_youtube_nothing_works_explains_and_offers_a_retry(phone):
    r, calls = run_short(phone, {"ytApps": {}})
    assert "did not give the spoken words" in r["error"] and r["yt_tried"]
    phone.goto(phone.url.split("#")[0] + "#/r/yt-dQw4w9WgXcQ")
    phone.get_by_role("button", name="Read from YouTube again").click()
    phone.get_by_role("heading", name="Done").wait_for()
    assert sum(1 for c in phone.rn()["calls"] if c[0] == "postYoutube" and c[3] == "ios") == 2


def test_caption_formats_and_unpunctuated_auto_captions(phone):
    phone.open_with()
    j3 = {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "so the first tip"}, {"utf8": " is backups"}]},
                     {"tStartMs": 1000, "dDurationMs": 900, "segs": [{"utf8": "every single day"}]},
                     {"tStartMs": 3000, "dDurationMs": 1000, "segs": [{"utf8": "the second tip is two factor login"}]}]}
    assert phone.evaluate("t => Notes.ytCaptions(t)", json.dumps(j3)) == "so the first tip is backups every single day\nthe second tip is two factor login"
    srv3 = '<timedtext format="3"><body><p t="0" d="2000">Hello &amp;amp; welcome.</p><p t="2000" d="1000">Bye now.</p></body></timedtext>'
    assert phone.evaluate("t => Notes.ytCaptions(t)", srv3) == "Hello & welcome. Bye now."
    assert phone.evaluate("t => Notes.ytCaptions(t)", "") == ""
    long = " ".join(f"Sentence number {i} talks about backups and passwords." for i in range(400))
    short = phone.evaluate("t => Notes.condense(t, 2000)", long)
    assert len(short) <= 2000 and short.startswith("Sentence number")
