"""Part 3: folder scanning, screenshot and reel processing, quotas, parallel background jobs, motivation clips."""
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from reel_watcher import gif, lookups, study, worker
from reel_watcher.library import Library

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def make_img(path, seed, size=(180, 320)):
    im = Image.new("RGB", size, (seed * 37 % 255, seed * 91 % 255, seed * 53 % 255))
    d = ImageDraw.Draw(im)
    for k in range(6):
        x0, x1 = sorted((10 + k * seed % 120, 60 + k * 17))
        d.rectangle((x0, 20 + k * 40, x1 + 1, 50 + k * 41), fill=((seed * k * 29) % 255, 200, (k * 70) % 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


class FakeVision:
    def __init__(self, out):
        self.out, self.calls = out, 0

    def ask(self, prompt, image=None, max_tokens=0):
        self.calls += 1
        return self.out


HITS = {
    "vinland saga": {"ext_key": "anilist:1", "name": "Vinland Saga", "names": ["Vinland Saga"], "type": "anime", "year": 2019, "language": "Japanese",
                     "genres": ["Action"], "cover": "", "extra": {}, "score": 1.0},
    "frieren": {"ext_key": "anilist:2", "name": "Frieren: Beyond Journey's End", "names": [], "type": "anime", "year": 2023, "language": "Japanese",
                "genres": ["Fantasy"], "cover": "", "extra": {}, "score": 0.9},
    "parasite": {"ext_key": "wikidata:Q3", "name": "Parasite", "names": [], "type": "movie", "year": 2019, "language": "Korean",
                 "genres": ["thriller film"], "cover": "", "extra": {}, "score": 1.0},
    "vagabond": {"ext_key": "anilist:4", "name": "Vagabond", "names": [], "type": "manga", "year": 1998, "language": "Japanese",
                 "genres": [], "cover": "", "extra": {}, "score": 1.0},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    lib = Library(tmp_path / "data")
    calls = {"ocr": 0, "trace": 0, "sauce": 0}
    ocr = {}

    def fake_ocr(p):
        calls["ocr"] += 1
        return ocr.get(p.name, "")
    monkeypatch.setattr(study, "ocr_image", fake_ocr)
    monkeypatch.setattr(lookups, "resolve_name", lambda name, hint="", min_score=0.82, **kw: HITS.get(name.lower().split(":")[0].strip()))
    enriched = []
    monkeypatch.setattr(worker.details, "enrich", lambda t, region="IN": enriched.append(t["name"]) or {"checked_at": 1, "synopsis": "S", "poster": "P"})
    monkeypatch.setattr(lookups, "anilist", lambda search=None, id_=None, media_type=None: [HITS["frieren"]] if id_ == 2 else [])
    trace = {"res": None}
    sauce = {"res": None}

    def fake_trace(b):
        calls["trace"] += 1
        if isinstance(trace["res"], Exception):
            raise trace["res"]
        return trace["res"]

    def fake_sauce(b):
        calls["sauce"] += 1
        return sauce["res"]
    monkeypatch.setattr(lookups, "trace_moe", fake_trace)
    monkeypatch.setattr(lookups, "saucenao", fake_sauce)
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 5, "sauce": 5})
    monkeypatch.setattr(lookups, "trace_me", lambda: {"quota": 100, "used": 0, "left": 100})
    web = {"pages": {}, "queries": []}

    def fake_fetch(url, data=None, timeout=20):  # search engines; a page per engine host, or an exception
        web["queries"].append((url, (data or {}).get("q")))
        page = web["pages"].get(lookups.urllib.parse.urlparse(url).hostname, lookups.ServiceError("offline in tests"))
        if isinstance(page, Exception):
            raise page
        return page
    monkeypatch.setattr(lookups, "fetch_html", fake_fetch)
    monkeypatch.setattr(lookups, "wikipedia_search", lambda q, limit=6: web.get("wiki", []))
    return {"web": web, "lib": lib, "tmp": tmp_path, "calls": calls, "ocr": ocr, "trace": trace, "sauce": sauce, "enriched": enriched}


def add_image(env, name, seed, collection="Screenshots"):
    p = make_img(env["tmp"] / "shots" / name, seed)
    iid, _ = env["lib"].add_item("img:" + name, "image", str(p), [collection])
    return iid


def finds(lib, iid):
    return lib.q("SELECT f.*, t.name title FROM finds f LEFT JOIN titles t ON t.id=f.title_id WHERE item_id=? ORDER BY f.id", (iid,))


def run_one(eng, kind="image"):
    it = eng.lib.claim_next(kind)
    (eng.process_image if kind == "image" else eng.process_reel)(it)
    return eng.lib.item(it["id"])


# What the text reader got from a real phone screenshot of the Wikipedia page "Scene (2026 film)"
WIKI_SCREEN = ("8:58 >- ± △ Vo en.wikipedia.org/wik + 2 三WIKIPEDIA D Scene (2026 film) Talk Article 不 ☆ Scene is an upcoming Indian "
               "Tamil-language action comedy film2l written and directed by Jithu Madhavan. Produced by Suriya and Jyothika's newly "
               "established Zhagaram Studios and 2D Entertainment, the film stars Suriya, Naslen and Nazriya Nazim in the lead roles. "
               "Scene ABRAS SCENE CINOV2026 E CAO")
DDG_PAGE = """<html><body><div class="results">
<div class="result results_links results_links_deep web-result"><div class="links_main links_deep result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FScene_(2026_film)&amp;rut=abc">Scene (2026 film) - Wikipedia</a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Scene is an upcoming Indian <b>Tamil</b>-language action comedy film written and directed by Jithu Madhavan.</a>
</div></div>
<div class="result results_links results_links_deep web-result"><div class="links_main links_deep result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.imdb.com%2Ftitle%2Ftt33000001%2F&amp;rut=def">Scene (2026) - IMDb</a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=y">Scene: Directed by Jithu Madhavan. With Suriya, Naslen, Nazriya Nazim.</a>
</div></div>
<div class="result results_links web-result"><div class="links_main result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FSuriya_(actor)">Suriya (actor) - Wikipedia</a></h2>
</div></div></div></body></html>"""
BING_PAGE = """<html><body><ol id="b_results">
<li class="b_algo" data-id=""><div class="b_tpcn"></div><h2><a href="https://www.bing.com/ck/a?!&amp;&amp;p=1&amp;u=a1aHR0cHM6Ly9lbi53aWtpcGVkaWEub3JnL3dpa2kvU2NlbmVfKDIwMjZfZmlsbSk&amp;ntb=1" h="ID=SERP">Scene (2026 film) - Wikipedia</a></h2>
<div class="b_caption"><p>Scene is an upcoming Indian Tamil-language action comedy film.</p></div></li>
</ol></body></html>"""


class BrokenVision:
    """The phone's AI model failing the way Ollama does when it cannot load the model (HTTP 500)."""
    def ask(self, *a, **kw):
        raise RuntimeError("Ollama: HTTP 500: model requires more system memory (3.9 GiB) than is available (2.1 GiB)")


def test_search_result_pages_are_parsed():
    ddg = lookups.parse_search_results(DDG_PAGE)
    assert [r["url"] for r in ddg] == ["https://en.wikipedia.org/wiki/Scene_(2026_film)", "https://www.imdb.com/title/tt33000001/",
                                       "https://en.wikipedia.org/wiki/Suriya_(actor)"]
    assert ddg[0]["title"] == "Scene (2026 film) - Wikipedia" and "Tamil-language" in ddg[0]["snippet"]
    bing = lookups.parse_search_results(BING_PAGE)
    assert bing[0]["url"] == "https://en.wikipedia.org/wiki/Scene_(2026_film)" and bing[0]["title"].startswith("Scene")
    assert lookups.parse_search_results("<html>captcha</html>") == []


def test_screenshot_of_wikipedia_page_found_by_web_search_even_when_ai_fails(env):
    """The real failing case: a new Tamil film the databases do not know yet, and an AI model that errors."""
    iid = add_image(env, "wiki.jpg", 5)
    env["ocr"]["wiki.jpg"] = WIKI_SCREEN
    env["web"]["pages"]["html.duckduckgo.com"] = DDG_PAGE
    eng = worker.Engine(env["lib"], vision_factory=BrokenVision)
    it = run_one(eng)
    f = finds(env["lib"], iid)
    assert it["status"] == "done", it
    assert [(x["title"], x["source"], x["confidence"]) for x in f] == [("Scene", "web", "confirmed")]
    t = env["lib"].one("SELECT * FROM titles WHERE name='Scene'")
    assert (t["type"], t["year"], t["language"]) == ("movie", 2026, "Tamil")
    assert t["extra"]["wikipedia_title"] == "Scene (2026 film)"
    assert env["web"]["queries"][0][1] == "Scene 2026 film"  # searched the page title, not the screen junk
    steps = it["meta"]["steps"]
    assert steps["Read text"]["ok"] and steps["Check names"]["ok"] is None and steps["Web search"]["ok"]  # None: nothing in the databases


def test_search_engine_blocked_falls_back_to_bing_then_wikipedia(env):
    iid = add_image(env, "w2.jpg", 6)
    env["ocr"]["w2.jpg"] = WIKI_SCREEN
    env["web"]["pages"]["html.duckduckgo.com"] = lookups.RateLimited("html.duckduckgo.com: HTTP 202")
    env["web"]["pages"]["www.bing.com"] = BING_PAGE
    it = run_one(worker.Engine(env["lib"], vision_factory=None))
    assert it["status"] == "done" and finds(env["lib"], iid)[0]["title"] == "Scene"
    iid = add_image(env, "w3.jpg", 7)
    env["ocr"]["w3.jpg"] = WIKI_SCREEN
    env["web"]["pages"]["www.bing.com"] = "<html>nothing</html>"
    env["web"]["wiki"] = [{"title": "Scene (2026 film) - Wikipedia", "url": "https://en.wikipedia.org/wiki/Scene_(2026_film)", "snippet": ""}]
    it = run_one(worker.Engine(env["lib"], vision_factory=None))
    assert it["status"] == "done" and finds(env["lib"], iid)[0]["title"] == "Scene"


def test_every_step_failing_is_reported_not_crashed(env):
    iid = add_image(env, "dead.jpg", 8)
    env["ocr"]["dead.jpg"] = WIKI_SCREEN
    env["sauce"]["res"] = None
    eng = worker.Engine(env["lib"], vision_factory=BrokenVision)
    eng.ai = True
    it = run_one(eng)
    assert it["status"] == "skipped" and it["error"] == "Not found (AI guesses failed). Try Google Lens, or type the name."
    steps = it["meta"]["steps"]
    # two engines were offline, Wikipedia answered with nothing: "found nothing", with each engine's note kept
    assert steps["Web search"]["ok"] is None and "offline in tests" in steps["Web search"]["detail"]
    assert steps["AI guesses"]["ok"] is False and "more system memory" in steps["AI guesses"]["detail"]
    assert steps["Manga and movie scene search"]["ok"] is None  # tried; found nothing (not an error)
    del iid


def test_scanner_dedupes_and_rescans(tmp_path):
    lib = Library(tmp_path / "d")
    a = make_img(tmp_path / "f" / "a.png", 3)
    make_img(tmp_path / "f" / "sub" / "b.png", 9)
    shutil.copy(a, tmp_path / "f" / "a_copy.png")                     # exact copy -> same key
    Image.open(a).convert("RGB").save(tmp_path / "f" / "a.jpg", quality=90)  # same picture re-saved -> near duplicate
    (tmp_path / "f" / "notes.txt").write_text("x")
    job, res = worker.start_folder_job(lib, [str(tmp_path / "f")], "Screenshots")
    assert res == {"found": 4, "added": 2, "duplicates": 1, "known": 1}
    assert lib.counts(job_id=job) == {"waiting": 2, "duplicate": 1, "total": 3}
    make_img(tmp_path / "f" / "c.png", 21)
    assert worker.scanner.scan_folders(lib, [str(tmp_path / "f")], job) == {"found": 5, "added": 1, "duplicates": 0, "known": 4}
    assert lib.job(job)["params"]["watch"] is True


def test_image_confirmed_from_text(env):
    iid = add_image(env, "v.png", 1)
    env["ocr"]["v.png"] = "VINLAND SAGA"
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    it = run_one(eng)
    assert it["status"] == "done" and it["meta"]["thumb"] == f"img_{iid}.jpg"
    f = finds(env["lib"], iid)
    assert [(x["title"], x["confidence"], x["source"]) for x in f] == [("Vinland Saga", "confirmed", "text")]
    assert env["calls"]["trace"] == 0  # no scene search spent when the text already names it
    assert (env["lib"].dir / "media" / f"img_{iid}.jpg").exists()


def test_picture_match_alone_is_possible_and_with_the_name_on_screen_verified(env):
    """A 95% scene match alone is a possible match (picture searches can be wrong); the same match plus the title
    written on the screen is verified."""
    iid = add_image(env, "f.png", 2)
    env["trace"]["res"] = {"ext_key": "anilist:2", "anilist_id": 2, "name": "Frieren", "names": [], "episode": 3, "at_s": 521.0, "score": 0.95}
    it = run_one(worker.Engine(env["lib"]))
    f = finds(env["lib"], iid)
    assert it["status"] == "check" and len(f) == 1
    assert (f[0]["title"], f[0]["confidence"], f[0]["detail"]) == ("Frieren: Beyond Journey's End", "check", "Episode 3 · at 8:41")
    assert f[0]["evidence"].startswith("picture match only")
    iid = add_image(env, "f2.png", 3)
    env["ocr"]["f2.png"] = "FRIEREN"
    it = run_one(worker.Engine(env["lib"]))
    f = finds(env["lib"], iid)
    assert it["status"] == "done" and (f[0]["title"], f[0]["confidence"]) == ("Frieren: Beyond Journey's End", "confirmed")
    assert "picture match agrees with the name on screen" in f[0]["evidence"] or f[0]["evidence"].startswith("named in the screenshot")


def test_quota_wait_keeps_ai_guess_then_resumes(env, monkeypatch):
    iid = add_image(env, "q.png", 4)
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 0, "sauce": 0})
    v = FakeVision({"is_media": True, "guesses": [{"name": "Frieren", "type": "anime"}]})
    eng = worker.Engine(env["lib"], vision_factory=lambda: v)
    eng.ai = True
    it = run_one(eng)
    assert it["status"] == "waiting_quota" and it["next_try_at"] > 0
    f = finds(env["lib"], iid)
    assert f == []  # the AI is only asked at the end, after the free searches
    assert env["lib"].claim_next("image") is None  # not retried before the limit resets
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 5, "sauce": 5})
    env["lib"].update_item(iid, next_try_at=0)
    env["trace"]["res"] = None
    env["sauce"]["res"] = None
    it = run_one(eng)
    assert it["status"] == "check" and env["calls"]["ocr"] == 1 and v.calls == 1  # OCR not repeated, AI asked once
    assert [(x["title"], x["confidence"], x["source"]) for x in finds(env["lib"], iid)] == [("Frieren: Beyond Journey's End", "check", "ai")]
    assert env["calls"]["trace"] == 1 and env["calls"]["sauce"] == 1


def test_trace_monthly_budget_and_busy_signal(env, monkeypatch):
    lib = env["lib"]
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 0, "sauce": 5})
    monkeypatch.setattr(lookups, "trace_me", lambda: {"quota": 100, "used": 100, "left": 0})
    eng = worker.Engine(lib, vision_factory=lambda: FakeVision({"is_media": True, "guesses": [{"name": "Frieren", "type": "anime"}]}))
    iid = add_image(env, "t1.png", 15)
    it = run_one(eng)
    assert it["status"] == "waiting_quota" and it["next_try_at"] >= worker.next_month_ts() - 1  # month used up: wait for next month
    assert env["calls"]["trace"] == 0
    monkeypatch.setattr(lookups, "trace_me", lambda: {"quota": 100, "used": 10, "left": 90})
    eng2 = worker.Engine(lib, vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    env["trace"]["res"] = lookups.RateLimited("api.trace.moe: HTTP 429")
    lib.update_item(iid, next_try_at=0)
    import time as _t
    it = run_one(eng2)
    assert it["status"] == "waiting_quota" and it["next_try_at"] - _t.time() < 300  # busy: retry in a couple of minutes
    assert lib.quota_take("trace", 1000)  # the day was not marked as used up


def test_details_fetched_once_per_title(env):
    iid = add_image(env, "d.png", 16)
    env["ocr"]["d.png"] = "VINLAND SAGA"
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    run_one(eng)
    iid2 = add_image(env, "d2.png", 17)
    env["ocr"]["d2.png"] = "VINLAND SAGA"
    run_one(eng)
    t = env["lib"].one("SELECT extra, cover FROM titles WHERE name='Vinland Saga'")
    assert env["enriched"] == ["Vinland Saga"] and t["extra"]["synopsis"] == "S" and t["cover"] == "P"
    del iid, iid2


def test_service_limit_reached_mid_run(env):
    iid = add_image(env, "z.png", 5)
    env["trace"]["res"] = lookups.QuotaExceeded("api.trace.moe: HTTP 402")
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    assert run_one(eng)["status"] == "waiting_quota"
    assert not env["lib"].quota_take("trace", 5)  # whole day marked as used


def test_manga_scene_match_and_other_and_live_action(env):
    m = add_image(env, "m.png", 6, "Manga panels")
    env["sauce"]["res"] = {"name": "Vagabond", "part": "210", "score": 0.87, "source_url": ""}
    eng = worker.Engine(env["lib"])
    it = run_one(eng)
    f = finds(env["lib"], m)
    assert it["status"] == "check" and (f[0]["title"], f[0]["detail"], f[0]["confidence"]) == ("Vagabond", "Chapter 210", "check")
    assert env["calls"]["trace"] == 0  # manga: SauceNAO only (trace.moe only knows anime)
    weak = add_image(env, "m2.png", 9, "Manga panels")
    env["sauce"]["res"] = {"name": "Vagabond", "part": "1", "score": 0.81, "source_url": ""}
    run_one(eng)
    assert finds(env["lib"], weak)[0]["evidence"].startswith("picture match too weak (81%)") and finds(env["lib"], weak)[0]["confidence"] == "check"

    chat = add_image(env, "chat.png", 7)
    env["ocr"]["chat.png"] = "Mom 10:42 PM Delivered Seen 10:43 typing"
    assert run_one(eng)["status"] == "other" and not finds(env["lib"], chat)

    meme = add_image(env, "meme.png", 8)
    env["sauce"]["res"] = None
    eng2 = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": False, "guesses": []}))
    eng2.ai = True
    assert run_one(eng2)["status"] == "other"

    # live action: SauceNAO's movie/show (IMDb) indexes are tried, anime-only trace.moe is not spent
    film = add_image(env, "film.png", 10)
    env["web"]["pages"]["html.duckduckgo.com"] = lookups.ServiceError("offline")
    before = dict(env["calls"])
    env["sauce"]["res"] = {"name": "Parasite", "kind": "movie", "part": "", "year": 2019, "imdb": "tt6751668", "score": 0.86, "source_url": ""}
    eng3 = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": [{"name": "Dark", "type": "series"}]}))
    eng3.ai = True
    assert run_one(eng3)["status"] == "check"
    f = finds(env["lib"], film)
    assert [(x["title"], x["confidence"], x["source"]) for x in f] == [("Parasite", "check", "scene"), ("Dark", "check", "ai")]
    assert env["calls"]["trace"] == before["trace"] and env["calls"]["sauce"] == before["sauce"] + 1
    film2 = add_image(env, "film2.png", 14)
    env["sauce"]["res"] = None
    assert run_one(eng3)["status"] == "check" and finds(env["lib"], film2)[0]["source"] == "ai"  # guess kept for you to check
    del meme


def test_no_ai_model_still_works(env):
    iid = add_image(env, "n.png", 11)

    def broken():
        raise RuntimeError("Ollama is not reachable")
    eng = worker.Engine(env["lib"], vision_factory=broken)
    it = run_one(eng)
    assert it["status"] == "skipped" and "ai" in it["meta"] and not eng.warnings  # AI is off by default: never tried
    assert it["error"].startswith("Not found") and "Google Lens" in it["error"]
    iid = add_image(env, "n2.png", 12)
    eng.ai = True
    it = run_one(eng)
    assert it["status"] == "skipped" and "Ollama" in eng.warnings[0] and it["meta"]["steps"]["AI guesses"]["ok"] is None
    del iid


def fake_reel_env(monkeypatch, tmp_path, rec, comments=(), caption=""):
    def prep(item, work_parent, comments_flag=False, **kw):
        work = work_parent / item["code"]
        work.mkdir(parents=True, exist_ok=True)
        v = work / "v.mp4"
        if HAS_FFMPEG:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=navy:s=180x320:d=4", "-f", "lavfi", "-i",
                            "sine=f=300:d=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v)], check=True)
        else:
            v.write_bytes(b"x")
        return {"item": item, "meta": {"caption": caption, "author": "creator_a"}, "work": work, "media": [v], "comments": list(comments)}
    monkeypatch.setattr(study, "prepare_ytdlp", lambda item, wp, comments=False: prep(item, wp, comments))
    key = make_img(tmp_path / "key.jpg", 12)
    monkeypatch.setattr(study, "analyze_video", lambda vision, video, work, collections, meta: (rec, key))


def test_reel_titles_from_comments_and_ai(env, monkeypatch):
    rec = {"transcript": {"language": "ta", "text": "This one will break you", "words": []},
           "frames": [{"visual": {"on_screen_text": "NAME IN COMMENTS"}}],
           "analysis": {"titles": [{"name": "Parasite", "type": "movie"}, {"name": "Some Guess", "type": "movie"}]}}
    fake_reel_env(monkeypatch, env["tmp"], rec, comments=[{"author": "creator_a", "text": "Anime: Vinland Saga"}, {"author": "b", "text": "name??"}])
    iid, _ = env["lib"].add_item("reel:R1", "reel", "https://www.instagram.com/reel/R1/", ["Anime"])
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({}))
    eng.ai = True
    it = run_one(eng, "reel")
    f = finds(env["lib"], iid)
    assert it["status"] == "done" and it["meta"]["reel_language"] == "ta" and it["meta"]["thumb"] == f"reel_{iid}.jpg"
    assert ("Vinland Saga", "confirmed", "comment") in [(x["title"], x["confidence"], x["source"]) for x in f]
    assert ("Parasite", "check", "ai") in [(x["title"], x["confidence"], x["source"]) for x in f]
    assert ("Some Guess", "check") in [(x["title"], x["confidence"]) for x in f]
    assert not (env["lib"].dir / "work" / "R1").exists()  # downloaded video removed


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_reel_read_without_ai_model(env, monkeypatch):
    """Phone case: the AI model fails to load. The reel is still read from on-screen text, speech and comments,
    and a name the databases do not know is found by web search."""
    fake_reel_env(monkeypatch, env["tmp"], {}, comments=[{"author": "b", "text": "its Scene (2026 film), Suriya is back"}])
    monkeypatch.setattr(study, "analyze_video", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Ollama: HTTP 500: out of memory")))
    monkeypatch.setattr(study, "transcribe_words", lambda v: (_ for _ in ()).throw(RuntimeError("no whisper")))
    env["ocr"]["b_000.jpg"] = "VINLAND SAGA"
    monkeypatch.setattr(study, "ocr_image", lambda p: "VINLAND SAGA" if p.name.startswith("b") else "")
    env["web"]["pages"]["html.duckduckgo.com"] = DDG_PAGE
    iid, _ = env["lib"].add_item("reel:R9", "reel", "https://www.instagram.com/reel/R9/", ["Movies"])
    eng = worker.Engine(env["lib"], vision_factory=BrokenVisionFactory)
    eng.ai = True
    it = run_one(eng, "reel")
    got = [(x["title"], x["confidence"], x["source"]) for x in finds(env["lib"], iid)]
    assert it["status"] == "done", it
    assert ("Vinland Saga", "confirmed", "text") in got and ("Scene", "confirmed", "web") in got
    assert any("out of memory" in w for w in eng.warnings)


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_reel_without_ai_setting_never_calls_the_model(env, monkeypatch):
    fake_reel_env(monkeypatch, env["tmp"], {}, caption="movie name: Parasite")
    monkeypatch.setattr(study, "analyze_video", lambda *a, **kw: pytest.fail("AI analysis must not run when AI guesses are off"))
    monkeypatch.setattr(study, "transcribe_words", lambda v: {"language": "ko", "text": "", "words": []})
    monkeypatch.setattr(study, "ocr_image", lambda p: "")
    asked = []
    iid, _ = env["lib"].add_item("reel:NOAI", "reel", "https://www.instagram.com/reel/NOAI/", ["Movies"])
    it = run_one(worker.Engine(env["lib"], vision_factory=lambda: asked.append(1) or FakeVision({})), "reel")
    assert it["status"] == "done" and not asked
    f = finds(env["lib"], iid)
    assert [(x["title"], x["confidence"]) for x in f] == [("Parasite", "confirmed")]
    assert f[0]["evidence"].startswith("named in the reel and identified by Wikidata")


def BrokenVisionFactory():
    return BrokenVision()


def test_reel_download_blocked_waits_an_hour(env, monkeypatch):
    monkeypatch.setattr(study, "prepare_ytdlp", lambda item, wp, comments=False: {"item": item, "error": "ytdlp: login required"})
    env["lib"].add_item("reel:B1", "reel", "https://www.instagram.com/reel/B1/", ["Movies"])
    it = run_one(worker.Engine(env["lib"]), "reel")
    assert it["status"] == "waiting_quota" and it["next_try_at"] > 1000


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_reel_quote_gif_and_rerender(env, monkeypatch):
    words = [{"w": w, "s": 0.4 + i * 0.35, "e": 0.7 + i * 0.35} for i, w in enumerate("Listen. Start before you feel ready. Write it down.".split())]
    rec = {"transcript": {"language": "en", "text": " ".join(w["w"] for w in words), "words": words}, "frames": [],
           "analysis": {"motivational_quote": {"text": "Start before you feel ready.", "start_s": 0.7, "end_s": 2.2}}}
    fake_reel_env(monkeypatch, env["tmp"], rec)
    iid, _ = env["lib"].add_item("reel:Q1", "reel", "https://www.instagram.com/reel/Q1/", ["Motivation"])
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({}))
    eng.ai = True
    assert run_one(eng, "reel")["status"] == "done"
    q = finds(env["lib"], iid)[0]
    assert q["kind"] == "quote" and q["quote"] == "Start before you feel ready." and q["media"] == f"quote_{iid}_bold.gif"
    assert (env["lib"].dir / "media" / q["media"]).stat().st_size > 1000
    name = eng.render_quote(q["id"], "typewriter", "mp4")
    assert name == f"quote_{iid}_typewriter.mp4" and (env["lib"].dir / "media" / name).exists()


def test_engine_runs_reels_and_screenshots_in_parallel_and_pauses(env, monkeypatch):
    rec = {"transcript": {"text": "", "words": []}, "frames": [], "analysis": {"titles": []}}
    fake_reel_env(monkeypatch, env["tmp"], rec, caption="movie name: Parasite")
    lib = env["lib"]
    job, _ = worker.start_folder_job(lib, [str(make_img(env["tmp"] / "bulk" / "x1.png", 30).parent)], "Screenshots", watch=False)
    for n in range(2, 7):
        make_img(env["tmp"] / "bulk" / f"x{n}.png", 30 + n * 7)
    worker.scanner.scan_folders(lib, [str(env["tmp"] / "bulk")], job)
    for n in range(3):
        lib.add_item(f"reel:P{n}", "reel", f"https://www.instagram.com/reel/P{n}/", ["Movies"], status="idle")
    rjob, queued = lib.queue_collection("Movies")
    assert queued == 3
    lib.set_job_state(rjob, "paused")
    eng = worker.Engine(lib, vision_factory=lambda: FakeVision({"is_media": True, "guesses": [{"name": "Frieren", "type": "anime"}]}),
                        idle_wait=0.05)
    eng.ai = True  # cover the AI path too (it is off by default)
    eng.start()
    try:
        eng.run_until_idle(30)
        assert lib.counts(job_id=rjob).get("waiting") == 3  # paused job untouched
        assert lib.counts(job_id=job).get("waiting", 0) == 0
        lib.set_job_state(rjob, "running")
        eng.run_until_idle(30)
    finally:
        eng.stop()
    assert lib.counts(job_id=rjob) == {"done": 3, "total": 3}
    c = lib.counts(job_id=job)
    assert c["total"] >= 6 and c.get("waiting", 0) == 0 and c.get("failed", 0) == 0
    titles = {t["name"] for t in lib.q("SELECT name FROM titles")}
    assert {"Parasite", "Frieren: Beyond Journey's End"} <= titles


def test_gif_helpers():
    words = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate("hey listen discipline is choosing what you want most".split())]
    assert gif.find_span(words, "Discipline is choosing what you want most.") == (2, 8)
    assert gif.find_span(words, "completely different words here") is None
    ass = gif.build_ass(words[2:6], 1.0, "bold")
    assert "PlayResX: 360" in ass and gif.HIGHLIGHT in ass and "DISCIPLINE" in ass and ass.count("Dialogue:") == 4
    assert "Dialogue: 0,0:00:00.00" in ass  # times are relative to the clip start
    tw = gif.build_ass(words[2:4], 1.0, "typewriter")
    assert "Dialogue: 0,0:00:00.00,0:00:00.50,Cap,,0,0,0,,discipline\n" in tw
    clean = gif.build_ass(words[2:6], 1.0, "clean")  # whole lines, 24 characters max
    assert ",discipline is choosing\n" in clean and clean.count("Dialogue:") == 2
    with pytest.raises(ValueError):
        gif.build_ass(words, 0, "comic")
    q = gif.pick_quote({"motivational_quote": {"text": "discipline is choosing", "start_s": 1, "end_s": 2}}, words, [])
    assert q["start"] == 1.0 and q["source"] == "speech" and len(q["words"]) == 3
    q = gif.pick_quote(None, [], ["", "Rest if you must but never quit"])
    assert q["text"] == "Rest if you must but never quit" and q["words"] == []
    assert gif.pick_quote(None, [], []) is None


def test_every_item_ends(env, monkeypatch):
    """No item stays 'working' or retries forever: each one ends with a state and a reason."""
    lib = env["lib"]
    eng = worker.Engine(lib, idle_wait=0.01)

    def run_loop_once(fn):
        eng.stop_ev.clear()
        item = lib.claim_next("image")
        lib.x("UPDATE items SET status='waiting', attempts=attempts-1 WHERE id=?", (item["id"],))  # let _loop claim it

        def stop_after(it):
            eng.stop_ev.set()
            fn(it)
        import threading
        timer = threading.Timer(1.0, eng.stop_ev.set)  # when the item is refused without running, stop anyway
        timer.start()
        try:
            eng._loop("image", stop_after)
        finally:
            timer.cancel()

    # 1. an unexpected error: failed, with a readable message
    a = add_image(env, "a.png", 21)
    run_loop_once(lambda it: (_ for _ in ()).throw(KeyError("boom")))
    it = lib.item(a)
    assert it["status"] == "failed" and it["error"].startswith("Unexpected problem (KeyError") and "Try again" in it["error"]
    # 2. a code path that forgets to set an end state: caught by the guard
    lib.update_item(a, status="waiting")
    run_loop_once(lambda it: None)
    assert lib.item(a)["status"] == "failed" and lib.item(a)["error"] == "Ended without a result. Tap Try again."
    # 3. an item that keeps crashing the app (killed mid-way) stops after MAX_ATTEMPTS
    lib.update_item(a, status="waiting", error="AI model ran out of memory")
    lib.x("UPDATE items SET attempts=? WHERE id=?", (worker.MAX_ATTEMPTS, a))
    run_loop_once(lambda it: pytest.fail("must not run again"))
    it = lib.item(a)
    assert it["status"] == "failed" and it["error"] == f"Stopped after {worker.MAX_ATTEMPTS} tries. Last problem: AI model ran out of memory. Tap Try again."
    # 4. watchdog: 'working' but nobody handles it -> queued again; one a worker is busy with is left alone
    b = add_image(env, "b.png", 22)
    lib.update_item(b, status="working")
    lib.x("UPDATE items SET updated_at=0 WHERE id=?", (b,))
    eng.current["image-1"] = str(env["tmp"] / "shots" / "b.png")
    assert eng.release_stale() == 0
    eng.current.clear()
    assert eng.release_stale() == 1 and lib.item(b)["status"] == "waiting"


def test_instagram_refusals_end_after_a_few_hours(env, monkeypatch):
    monkeypatch.setattr(study, "prepare_ytdlp", lambda item, wp, comments=False: {"error": "HTTP Error 429: Too Many Requests (rate-limit)"})
    iid, _ = env["lib"].add_item("reel:BLK", "reel", "https://www.instagram.com/reel/BLK/", ["Movies"])
    eng = worker.Engine(env["lib"])
    for n in range(worker.MAX_INSTAGRAM_WAITS):
        it = run_one(eng, "reel")
        assert it["status"] == "waiting_quota", it
        env["lib"].update_item(iid, next_try_at=0)
    it = run_one(eng, "reel")
    assert it["status"] == "failed" and f"refused this reel {worker.MAX_INSTAGRAM_WAITS} times" in it["error"]
