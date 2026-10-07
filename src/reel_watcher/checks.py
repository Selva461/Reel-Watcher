"""Self-check on the real device: every feature tried for real, with PASS / FAIL and what to do about a failure.

  reel-watcher check            (also: Settings > Self-check in the app)

Each check is independent: one failing (no internet, no AI model) never stops the others.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import lookups, security


def _row(name: str, fn, hint: str = "") -> dict:
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001  report every failure, keep going
        ok, detail = False, f"{type(e).__name__}: {e}"
    return {"name": name, "ok": ok, "detail": str(detail)[:300], "hint": "" if ok else hint, "seconds": round(time.time() - t0, 1)}


def check_text_reader():
    from PIL import Image, ImageDraw, ImageFont

    from .study import ocr_image
    im = Image.new("RGB", (900, 260), "white")
    try:
        font = ImageFont.load_default(size=72)
    except TypeError:  # older Pillow: small bitmap font, scaled up below
        font = ImageFont.load_default()
    ImageDraw.Draw(im).text((30, 80), "VINLAND SAGA", fill="black", font=font)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "check.png"
        im.save(p)
        text = ocr_image(p)
    return ("VINLAND" in text.upper(), f"read: {text[:60]!r}" if text else "read nothing")


def check_speech_engine():
    from .study import whisper_cpp_bin
    try:
        import faster_whisper  # noqa: F401
        return True, "faster-whisper"
    except ImportError:
        pass
    b = whisper_cpp_bin()
    return (bool(b), f"whisper.cpp at {b}" if b else "no speech-to-text engine installed")


def check_ffmpeg():
    return (bool(shutil.which("ffmpeg") and shutil.which("ffprobe")), shutil.which("ffmpeg") or "ffmpeg not found")


def check_ai_model():
    from . import model
    tags = {m.get("name") for m in (model.ollama_request("/api/tags", timeout=10) or {}).get("models", [])}
    want = model.VISION_MODEL
    if want not in tags and f"{want}:latest" not in tags:
        return False, f"model {want} not downloaded (have: {', '.join(sorted(t for t in tags if t)) or 'none'})"
    # a tiny real request: loading the model is where phones run out of memory
    r = model.ollama_request("/api/generate", {"model": want, "prompt": "Reply with OK", "stream": False,
                                               "options": {"num_predict": 3}}, timeout=300)
    return True, f"{want} answered: {str((r or {}).get('response', '')).strip()[:20]!r}"


def check_engine(name: str):
    def run():
        q = "Parasite 2019 film"
        if name == "DuckDuckGo":
            res = lookups.parse_search_results(lookups.fetch_html(lookups.DDG, {"q": q, "kl": "wt-wt"}))
        elif name == "Bing":
            res = lookups.parse_search_results(lookups.fetch_html(lookups.BING + "?" + lookups.urllib.parse.urlencode({"q": q})))
        else:
            res = lookups.wikipedia_search(q)
        return (bool(res), f"{len(res)} results, first: {res[0]['title'][:60]!r}" if res else "no results (blocked or changed page)")
    return run


def check_web_identify():
    work, notes = lookups.web_identify("Scene 2026 film", name_hint="Scene", kind_hint="movie", year=2026)
    ok = bool(work) and work["name"].lower() == "scene" and work.get("year") == 2026
    return ok, (f"{work['name']} ({work.get('year')}, {work.get('type')}) via {work['site']}" if work else "; ".join(notes[-3:]))


def check_database(name: str):
    def run():
        if name == "AniList":  # call the services directly so a network error is shown as such
            hits = lookups.anilist("Frieren", media_type="ANIME")
            return (any("frieren" in h["name"].lower() for h in hits), hits[0]["name"] if hits else "no results")
        if name == "Wikidata":
            hits = lookups.wikidata("Parasite")
            p = next((h for h in hits if h.get("year") == 2019), None)
            return (bool(p), f"{p['name']} ({p['year']}, {p['type']})" if p else f"{len(hits)} results, none from 2019")
        if name == "MyAnimeList":
            j = lookups.jikan_check(52991)
            return (bool(j), str(j.get("mal_title") or j)[:60])
        if name == "TVmaze":
            t = lookups.tvmaze("Dark", 2017)
            return (bool(t), str(t.get("network") or t.get("status") or t)[:60])
        if name == "trace.moe":
            me = lookups.trace_me()
            return (me.get("left", 0) > 0, f"{me.get('left')} of {me.get('quota')} free anime scene searches left this month")
        return False, "unknown"
    return run


def check_instagram():
    import urllib.request
    req = urllib.request.Request("https://www.instagram.com/", headers={"User-Agent": lookups.BROWSER_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return (r.status < 400, f"HTTP {r.status}")


def check_security():
    bad = security.outdated()
    return (not bad, "; ".join(bad) or "no known-vulnerable package versions installed")


def check_storage(data_dir: Path):
    def run():
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        free = shutil.disk_usage(data_dir).free / 2**30
        return (free > 1.0, f"{free:.1f} GB free in {data_dir}")
    return run


def _ai_setting(data_dir: Path) -> bool:
    import json
    try:
        return bool(json.loads((data_dir / "settings.json").read_text(encoding="utf-8")).get("ai"))
    except (OSError, ValueError):
        return False


def run_checks(data_dir: Path | None = None, progress=None, ai: bool | None = None) -> list[dict]:
    data_dir = Path(data_dir or Path.home() / "ReelShelf")
    ai = _ai_setting(data_dir) if ai is None else ai
    ai_check = check_ai_model if ai else (lambda: (True, "AI guesses are off (Settings): not needed"))
    plan = [
        ("Library storage", check_storage(data_dir), "Free some space on the phone."),
        ("Security of installed packages", check_security, "Run the update command shown."),
        ("Text reader (OCR)", check_text_reader, "Phone: pkg install tesseract. PC: uv sync."),
        ("Speech-to-text", check_speech_engine, "Phone: run the setup again (step 4). Reels are still read from text and comments."),
        ("Video tools (ffmpeg)", check_ffmpeg, "Phone: pkg install ffmpeg."),
        ("AI model (Ollama)", ai_check, "Turn AI guesses off in Settings: everything else works without it. "
                                         "If it says memory, the phone is too small for the model."),
        ("Web search: DuckDuckGo", check_engine("DuckDuckGo"), "Busy or blocked for now; Bing and Wikipedia are used instead."),
        ("Web search: Bing", check_engine("Bing"), "Busy or blocked for now; the other engines are used instead."),
        ("Web search: Wikipedia", check_engine("Wikipedia"), "Check the internet connection."),
        ("Finds a new film by web search", check_web_identify, "Needs at least one web search engine above."),
        ("Anime and manga database (AniList)", check_database("AniList"), "Check the internet connection; AniList may be down briefly."),
        ("Movies and series database (Wikidata)", check_database("Wikidata"), "Check the internet connection."),
        ("MyAnimeList cross-check", check_database("MyAnimeList"), "Optional cross-check; often busy."),
        ("TV series details (TVmaze)", check_database("TVmaze"), "Optional details."),
        ("Anime scene search (trace.moe)", check_database("trace.moe"), "Monthly free searches used up, or the service is down."),
        ("Instagram reachable", check_instagram, "Check the internet connection."),
    ]
    rows = []
    for name, fn, hint in plan:
        if progress:
            progress(name, rows)
        rows.append(_row(name, fn, hint))
    if progress:
        progress("", rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    rows = run_checks(progress=lambda name, rows: name and print(f"... {name}", file=sys.stderr))
    for r in rows:
        print(f"[{'PASS' if r['ok'] else 'FAIL'}] {r['name']}  ({r['seconds']}s)\n       {r['detail']}" + (f"\n       -> {r['hint']}" if r["hint"] else ""))
    bad = [r for r in rows if not r["ok"]]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} checks passed.")
    return 0 if not bad else 1
