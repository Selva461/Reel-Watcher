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
    monkeypatch.setattr(lookups, "resolve_name", lambda name, hint="", min_score=0.82: HITS.get(name.lower().split(":")[0].strip()))
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
    return {"lib": lib, "tmp": tmp_path, "calls": calls, "ocr": ocr, "trace": trace, "sauce": sauce}


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


def test_ai_guess_shown_then_replaced_by_scene_match(env):
    iid = add_image(env, "f.png", 2)
    env["trace"]["res"] = {"ext_key": "anilist:2", "anilist_id": 2, "name": "Frieren", "names": [], "episode": 3, "at_s": 521.0, "score": 0.95}
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": [{"name": "Mushishi", "type": "anime"}]}))
    it = run_one(eng)
    f = finds(env["lib"], iid)
    assert it["status"] == "done" and len(f) == 1
    assert (f[0]["title"], f[0]["confidence"], f[0]["detail"]) == ("Frieren: Beyond Journey's End", "matched", "Episode 3 · at 8:41")


def test_quota_wait_keeps_ai_guess_then_resumes(env, monkeypatch):
    iid = add_image(env, "q.png", 4)
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 0, "sauce": 0})
    v = FakeVision({"is_media": True, "guesses": [{"name": "Frieren", "type": "anime"}]})
    eng = worker.Engine(env["lib"], vision_factory=lambda: v)
    it = run_one(eng)
    assert it["status"] == "waiting_quota" and it["next_try_at"] > 0
    f = finds(env["lib"], iid)
    assert [(x["title"], x["confidence"], x["source"]) for x in f] == [("Frieren: Beyond Journey's End", "check", "ai")]  # guess shown right away
    assert env["lib"].claim_next("image") is None  # not retried before the limit resets
    monkeypatch.setattr(lookups, "DAILY_LIMITS", {"trace": 5, "sauce": 5})
    env["lib"].update_item(iid, next_try_at=0)
    env["trace"]["res"] = None
    env["sauce"]["res"] = None
    it = run_one(eng)
    assert it["status"] == "check" and env["calls"]["ocr"] == 1 and v.calls == 1  # OCR and AI were not repeated
    assert env["calls"]["trace"] == 1 and env["calls"]["sauce"] == 1


def test_service_limit_reached_mid_run(env):
    iid = add_image(env, "z.png", 5)
    env["trace"]["res"] = lookups.QuotaExceeded("api.trace.moe: HTTP 402")
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    assert run_one(eng)["status"] == "waiting_quota"
    assert not env["lib"].quota_take("trace", 5)  # whole day marked as used


def test_manga_scene_match_and_other_and_live_action(env):
    m = add_image(env, "m.png", 6, "Manga panels")
    env["sauce"]["res"] = {"name": "Vagabond", "part": "210", "score": 0.81, "source_url": ""}
    eng = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": []}))
    it = run_one(eng)
    f = finds(env["lib"], m)
    assert it["status"] == "done" and (f[0]["title"], f[0]["detail"]) == ("Vagabond", "Chapter 210")
    assert env["calls"]["trace"] == 0  # manga collections try SauceNAO first

    chat = add_image(env, "chat.png", 7)
    env["ocr"]["chat.png"] = "Mom 10:42 PM Delivered Seen 10:43 typing"
    assert run_one(eng)["status"] == "other" and not finds(env["lib"], chat)

    meme = add_image(env, "meme.png", 8)
    eng2 = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": False, "guesses": []}))
    assert run_one(eng2)["status"] == "other"

    film = add_image(env, "film.png", 10)
    before = dict(env["calls"])
    eng3 = worker.Engine(env["lib"], vision_factory=lambda: FakeVision({"is_media": True, "guesses": [{"name": "Parasite", "type": "movie"}]}))
    assert run_one(eng3)["status"] == "check"
    assert env["calls"]["trace"] == before["trace"] and env["calls"]["sauce"] == before["sauce"]  # no free scene search for live action
    assert finds(env["lib"], film)[0]["title"] == "Parasite"
    del meme


def test_no_ai_model_still_works(env):
    iid = add_image(env, "n.png", 11)

    def broken():
        raise RuntimeError("Ollama is not reachable")
    eng = worker.Engine(env["lib"], vision_factory=broken)
    it = run_one(eng)
    assert it["status"] == "skipped" and "Ollama" in eng.warnings[0]
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
    it = run_one(eng, "reel")
    f = finds(env["lib"], iid)
    assert it["status"] == "done" and it["meta"]["reel_language"] == "ta" and it["meta"]["thumb"] == f"reel_{iid}.jpg"
    assert ("Vinland Saga", "confirmed", "comment") in [(x["title"], x["confidence"], x["source"]) for x in f]
    assert ("Parasite", "check", "ai") in [(x["title"], x["confidence"], x["source"]) for x in f]
    assert ("Some Guess", "check") in [(x["title"], x["confidence"]) for x in f]
    assert not (env["lib"].dir / "work" / "R1").exists()  # downloaded video removed


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
