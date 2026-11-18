"""Makes the upgrade fixtures in tests/fixtures/library/<version>/ (reels.json and shots.json).

Each fixture is written by THE PAGE CODE OF THAT RELEASE, not by hand: this script takes the page assets of a git tag
(`git archive vX android/app-shell/app/src/main/assets/local`), opens the page in Chromium at phone size with the fake
`window.RN` of tests/test_phone_app.py, plays one fixed scenario with synthetic data, and saves the exact text the
page handed to `RN.store` (reels.json) and `RN.storeShots` (shots.json). Nothing is edited afterwards.

Run it by hand when a version is released (the CI clone has no tags):

    python tests/fixtures/make_library_fixtures.py 1.3.6 1.3.7 1.3.8 1.3.10 1.3.11
    python tests/fixtures/make_library_fixtures.py --assets DIR 1.3.12     # page assets from a folder instead of a tag

The clock is fixed and only moves when the scenario moves it, so the same tag always gives the same bytes.
Everything in the data is invented (made-up reel codes, creators, captions, titles, brands). No real reel data."""
import argparse
import functools
import http.server
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_app import CHROME  # noqa: E402
from test_phone_app import ANSWER, FAKE_RN  # noqa: E402
from test_shots import SHOTS_RN, L  # noqa: E402

ASSETS_IN_TAG = "android/app-shell/app/src/main/assets/local"
START = 1767225600000  # 2026-01-01 00:00 UTC: the fixed clock starts here
DAY = 86400000

# The clock only moves when the scenario moves it (tick). Date.now is the only time source the page's data uses.
CLOCK = """
window.__now = Number(sessionStorage.getItem("clock") || %d);
Date.now = () => window.__now;
""" % START

# What the fake bridge of test_phone_app.py leaves out: the quote and product checks answer "offline" (nothing found),
# generate can be made to hang (the app is closed while a reel is being written), and takeShared is the older way a
# page took the shared items (1.3.6: everything is handed over and the list is emptied; later pages peek and acknowledge).
EXTRA_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  const hang = window.RN.generate;
  window.RN.generate = (id, prompt, opts) => { if (st.hangGenerate) { st.calls.push(["generate-hangs"]); keep(); return; } return hang(id, prompt, opts); };
  window.RN.takeShared = () => { const t = JSON.stringify(st.shared.map((x) => ({ id: "id-" + x, text: x, at: 1 }))); st.shared = []; keep(); return t; };
  window.RN.quoteCheck = (id) => setTimeout(() => rnDone(id, false, "No internet"), 5);
  window.RN.productCheck = (id) => setTimeout(() => rnDone(id, false, "No internet"), 5);
})();
"""

LINK = "https://www.instagram.com/reel/%s/"


def embed(author, caption):
    return ('<html><body><div class="Embed"><div class="Caption"><a class="CaptionUsername" href="#">%s</a>\n%s\n'
            '<div class="CaptionComments">View all 3 comments</div></div></div></body></html>' % (author, caption))


YT = "SampleYT001"  # a made-up YouTube id (11 characters)
WATCH = '<html><script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaSampleKey_000"});</script></html>'
PLAYER = {
    "playabilityStatus": {"status": "OK"},
    "videoDetails": {"title": "Sample video about desk stretches", "author": "Sample Channel", "shortDescription": "Stretch every day."},
    "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
        {"baseUrl": "https://www.youtube.com/api/timedtext?v=%s&lang=en&fmt=srv3" % YT, "languageCode": "en", "kind": "asr"}]}},
}
TIMED = """<?xml version="1.0" encoding="utf-8" ?><transcript>
<text start="0" dur="2">Stretch your neck first and breathe slowly.</text>
<text start="2" dur="3">Then roll your wrists and open your chest every hour.</text>
<text start="5" dur="2">Finish with a short walk around the room.</text></transcript>"""

PAGES = {
    "youtube.com/watch": WATCH,
    "api/timedtext": TIMED,
    "FIXA0001/embed": embed("sample_creator_one", "Three free note taking tools for students<br>1. Alpha Notes<br>2. Beta Pad<br>3. Gamma Docs #notes #study"),
    "FIXA0002/embed": embed("sample_creator_two", "How to keep a budget with a simple sheet<br>Step 1: list the fixed costs<br>Step 2: set a weekly limit #money"),
    "FIXA0005/embed": embed("sample_creator_five", "Movie name: Arrival (2016)<br>A quiet film about language and time, worth a rewatch #movies"),
    "FIXA0006/embed": embed("sample_creator_six", "Five stretches to do at your desk every day before lunch<br>Neck, wrists, back, hips, ankles #health"),
}

# A Meta AI answer that names a reel (it is filed under that reel), with a PRODUCTS line.
ANSWER_FOR_A4 = (LINK % "FIXA0004") + "\n\n" + ANSWER.replace("**TAGS:**", "**PRODUCTS:** Bluebird Daily Face Wash\n\n**TAGS:**")
# An answer with no link and no reel asked about: it waits in the inbox to be filed.
ANSWER_LOOSE = """**TOPIC:** A loose answer for the inbox

**POINTS:**
1. Nothing in it names a reel
2. It waits until you file it

**TAKEAWAY:** Keep it for later.

**TAGS:** #sample, #inbox
"""
ANSWER_PHONE = ANSWER.replace("Hardcoded secrets in mobile apps", "Sample notes written by the phone")

EXPORT_POSTS = {"saved_saved_media": [
    {"title": "sample_creator_five", "string_map_data": {"Saved on": {"href": LINK % "FIXA0005", "timestamp": 1}}}]}
EXPORT_COLLECTIONS = {"saved_saved_collections": [
    {"title": "Collection", "string_map_data": {"Name": {"value": "Movies"}}},
    {"title": "sample_creator_five", "string_map_data": {"Name": {"value": "sample_creator_five", "href": LINK % "FIXA0005"}}}]}

FOLDER = {"uri": "content://x/tree/primary%3AScreens", "name": "DCIM/Screenshots"}


def screenshots():
    pics, text = [], {}
    for i, name, lines in [
        (1, "Screenshot_1_com.instagram.android.jpg", [L("Movie: Interstellar", 600)]),
        (2, "Screenshot_2_com.instagram.android.jpg", [L("lol so true", 600)]),
        (3, "Screenshot_3_com.instagram.android.jpg", [L("Top anime to watch", 300), L("1. Mushishi", 400), L("2. Monster", 460)]),
        (4, "Screenshot_4_notes.jpg", [L("\"Small steps every single day will take you further than any big leap.\"", 700, 60), L("Sample Author", 800)]),
        (5, "Screenshot_5_shop.jpg", [L("Bluebird", 500), L("Daily Face Wash", 560), L("Rs 299", 620)]),
    ]:
        k = "content://x/tree/primary%3AScreens/document/" + str(i)
        pics.append({"k": k, "n": name, "f": FOLDER["name"], "m": 1000 + i, "s": 1})
        text[k] = lines
    return pics, text


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/index.html" % srv.server_address[1]


def tag_assets(version, into):
    """The page assets of a release, straight from git."""
    data = subprocess.run(["git", "archive", "v" + version, ASSETS_IN_TAG], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(into, filter="data")
    return Path(into) / ASSETS_IN_TAG


def generate(assets):
    """Plays the scenario against the page in `assets`. Returns (reels_json_text, shots_json_text, notes)."""
    from playwright.sync_api import sync_playwright
    srv, url = serve(assets)
    pics, text = screenshots()
    notes = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            for s in (CLOCK, FAKE_RN, SHOTS_RN, EXTRA_RN):
                ctx.add_init_script(s)
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("dialog", lambda d: d.accept())

            def rn():
                return pg.evaluate("window.__rn")

            def setrn(**kw):
                pg.evaluate("s => { Object.assign(window.__rn, s); sessionStorage.setItem('rn', JSON.stringify(window.__rn)); }", kw)

            def tick(days):
                pg.evaluate("d => { window.__now += d * 86400000; sessionStorage.setItem('clock', window.__now); }", days)

            def open_page(state=None):
                pg.goto(url + "#/blank")
                if state:
                    pg.evaluate("s => sessionStorage.setItem('rn', JSON.stringify(s))", state)
                pg.goto(url + "#/")
                pg.reload()
                pg.wait_for_selector("#app > *")

            def library():
                return json.loads(rn()["db"] or "{}")

            # 1. the day: five things are shared while the app is closed, then the app opens and files them
            open_page({"shared": [LINK % "FIXA0001", LINK % "FIXA0002", LINK % "FIXA0003", "https://youtube.com/shorts/" + YT, ANSWER_FOR_A4, ANSWER_LOOSE],
                       "pages": PAGES, "player": PLAYER, "folders": [FOLDER], "pics": pics, "text": text, "settings": json.dumps({"metaAi": True})})
            pg.wait_for_function("() => window.__rn.shared.length === 0")
            tick(1)
            # an Instagram export with a collection is read (the reel comes in with its collection and creator)
            pg.evaluate("([a, b]) => importParts([{ name: 'saved_posts.json', text: a }, { name: 'saved_collections.json', text: b }])",
                        [json.dumps(EXPORT_POSTS), json.dumps(EXPORT_COLLECTIONS)])
            # 2. no AI model yet: Start reads the captions and writes quick notes
            pg.evaluate("() => startRun()")
            tick(1)
            # 3. the AI model is ready: the next Start writes notes with it for the first reel, and fails on the others
            setrn(model={"ready": True, "partial": 0, "installed": []}, answers=[ANSWER_PHONE])
            pg.evaluate("() => startRun()")
            tick(1)
            # 4. screenshots are read: titles, a quote, a product; then the online check answers
            pg.evaluate("() => Shots.process()")
            pg.wait_for_function("() => !Verify.job || Verify.job.finished")
            media = {m["title"]: m["id"] for m in library().get("media", [])}
            notes.append("titles: " + ", ".join(sorted(media)))
            facts = {"title": "Interstellar", "year": 2014, "language": "en", "type": "movie", "genres": ["Science fiction"],
                     "poster": "", "ext": {"tmdb": "movie/0"}}
            answers = {}
            if "Interstellar" in media:
                answers[media["Interstellar"]] = {"verdict": "verified", "confidence": 0.97, "by": "tmdb+wikidata",
                                                  "note": "Confirmed by tmdb and wikidata", "facts": facts, "choices": []}
            if "Mushishi" in media:
                answers[media["Mushishi"]] = {"verdict": "not_found", "confidence": 0.2, "by": "tmdb", "note": "Nothing online matched well enough",
                                              "checked_at": pg.evaluate("window.__now"), "choices": []}
            setrn(verifyAnswers=answers)
            pg.evaluate("() => Verify.start()")
            pg.wait_for_function("() => Verify.job.finished")
            tick(1)
            # 5. you tapped Ask Meta AI on one reel (it is remembered, so the answer finds its reel), a category of your own and a title you typed
            pg.goto(url + "#/r/FIXA0003")
            pg.get_by_role("button", name="Ask Meta AI").click()
            pg.wait_for_function("() => window.__rn.sharedOut.length === 1")
            pg.evaluate("() => { Catalog.addType(db, 'Podcast', 'other'); Catalog.add(db, { title: 'Sample Show', type: 'series', confidence: 0.9, "
                        "source: { kind: 'manual', ref: '', method: 'typed', text: 'Sample Show', confidence: 0.9 } }); saveDb(); }")
            # 6. the nightly run (the page's own overnightRun), which files lastNight
            pg.evaluate("() => overnightRun(true)")
            tick(1)
            # 7. the next day the app is opened again; two more reels are shared; the AI starts on one and the app is closed mid-way
            setrn(shared=[LINK % "FIXA0006", LINK % "FIXA0007"], pages=PAGES)
            pg.reload()
            pg.wait_for_selector("#app > *")
            pg.wait_for_function("() => window.__rn.shared.length === 0")
            setrn(hangGenerate=True, answers=[])
            pg.evaluate("() => { startRun(['FIXA0006']); }")
            pg.wait_for_function("() => /\"code\":\"FIXA0006\"[^{}]*\"status\":\"working\"|\"status\":\"working\"[^{}]*\"code\":\"FIXA0006\"/.test(window.__rn.db || '')")
            st = rn()
            reels_text, shots_text = st["db"], st["shotsDb"]
            browser.close()
            if errors:
                raise RuntimeError("page errors: %s" % errors)
    finally:
        srv.shutdown()
    return reels_text, shots_text, notes


def summary(reels_text, shots_text):
    d, s = json.loads(reels_text), json.loads(shots_text)
    by = {}
    for r in d["reels"]:
        by.setdefault(r["status"] + "/" + (r.get("notes_by") or "-"), []).append(r["code"])
    return ("%d reels %s; keys %s; %d titles, %d quotes, %d products, %d inbox; shots: v=%s, %d seen, %d reels"
            % (len(d["reels"]), {k: len(v) for k, v in sorted(by.items())}, sorted(d), len(d.get("media", [])), len(d.get("quotes", [])),
               len(d.get("products", [])), len(d.get("inbox", [])), s.get("v"), len(s.get("seen", {})), len(s.get("reels", {}))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("versions", nargs="+", help="released versions, for example 1.3.11 (a git tag v1.3.11 must exist)")
    ap.add_argument("--assets", help="use the page assets in this folder instead of the tag (one version only)")
    ap.add_argument("--out", default=str(HERE / "library"))
    a = ap.parse_args()
    if a.assets and len(a.versions) != 1:
        ap.error("--assets is the page code of ONE version: give exactly one version with it")
    if not CHROME:
        sys.exit("Chromium is not available")
    for v in a.versions:
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(a.assets) if a.assets else tag_assets(v, tmp)
            reels_text, shots_text, notes = generate(assets)
        out = Path(a.out) / v
        out.mkdir(parents=True, exist_ok=True)
        (out / "reels.json").write_bytes(reels_text.encode("utf-8"))
        (out / "shots.json").write_bytes(shots_text.encode("utf-8"))
        print(v, "reels.json %d bytes, shots.json %d bytes" % (len(reels_text.encode()), len(shots_text.encode())))
        print("   ", summary(reels_text, shots_text))
        for n in notes:
            print("   ", n)


if __name__ == "__main__":
    main()
