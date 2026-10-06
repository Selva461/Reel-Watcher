"""A small sample library for trying the app (`reel-watcher app --demo`) and for the UI tests.
Creators are placeholders; titles are real public works so the lookups and filters behave as they would."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .library import Library

TITLES = [
    ("anilist:101348", "Vinland Saga", "anime", 2019, "Japanese", ["Action", "Drama"], {"episodes": 48}),
    ("anilist:154587", "Frieren: Beyond Journey's End", "anime", 2023, "Japanese", ["Adventure", "Fantasy"], {"episodes": 28}),
    ("anilist:99088", "Pluto", "anime", 2023, "Japanese", ["Mystery", "Sci-Fi"], {"episodes": 8}),
    ("anilist:30656", "Vagabond", "manga", 1998, "Japanese", ["Action", "Drama"], {"chapters": 327}),
    ("wikidata:Q61448040", "Parasite", "movie", 2019, "Korean", ["Thriller"], {}),
    ("wikidata:Q229071", "3 Idiots", "movie", 2009, "Hindi", ["Comedy", "Drama"], {}),
    ("wikidata:Q30595380", "Vikram Vedha", "movie", 2017, "Tamil", ["Action", "Thriller"], {}),
    ("wikidata:Q24572018", "Dark", "series", 2017, "German", ["Sci-Fi", "Mystery"], {}),
]
COLORS = [(58, 63, 74), (63, 58, 48), (47, 58, 51), (64, 46, 54), (59, 58, 44), (45, 53, 64), (42, 45, 51), (44, 52, 66)]


def _img(path: Path, color, label: str) -> None:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (360, 640), color)
    d = ImageDraw.Draw(im)
    d.rectangle((24, 260, 336, 380), fill=(0, 0, 0))
    d.text((40, 300), label[:30], fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=80)


def build(data_dir: Path | str) -> Library:
    lib = Library(data_dir)
    if lib.one("SELECT id FROM items LIMIT 1"):
        return lib
    media = lib.dir / "media"
    tids = {}
    for ext, name, kind, year, lang, genres, extra in TITLES:
        tids[name] = lib.upsert_title(ext, name, type=kind, year=year, language=lang, genres=genres, extra=extra)
    lib.update_title(tids["Parasite"], watch="watched")
    lib.merge_title_extra(tids["Frieren: Beyond Journey's End"], {
        "synopsis": "An elf mage outlives the hero party she travelled with and sets out to understand the people she lost.",
        "status": "Finished", "season": "Fall 2023", "episodes": 28, "studios": ["Madhouse"], "score": 90, "mal_score": 9.3,
        "where_to_watch": [{"site": "Crunchyroll", "url": "https://www.crunchyroll.com/", "language": None}],
        "related": [{"relation": "Source", "name": "Frieren", "type": "manga", "year": 2020, "ext_key": "anilist:118586"}],
        "url": "https://anilist.co/anime/154587", "mal_url": "https://myanimelist.net/anime/52991",
        "sources": ["AniList", "MyAnimeList"], "checked_at": 1790000000})
    lib.update_title(tids["Frieren: Beyond Journey's End"], favorite=1)

    def reel(code, coll, title, source, evidence, lang="en", conf="confirmed", n=0, detail="", author="creator_a"):
        iid, _ = lib.add_item(f"reel:{code}", "reel", f"https://www.instagram.com/reel/{code}/", [coll], status="done")
        _img(media / f"reel_{iid}.jpg", COLORS[n % len(COLORS)], title)
        lib.merge_meta(iid, thumb=f"reel_{iid}.jpg", author=author, reel_language=lang, caption=evidence)
        lib.add_find(iid, "title", title_id=tids[title], name_raw=title, source=source, evidence=evidence, confidence=conf, detail=detail)
        return iid

    reel("DEMO1", "Anime", "Vinland Saga", "comment", "Anime: Vinland Saga", "ta", n=0)
    reel("DEMO2", "Anime", "Frieren: Beyond Journey's End", "speech", "Number one has to be Frieren", n=1, author="creator_b")
    reel("DEMO3", "Anime", "Pluto", "text", "1. Pluto 2. Monster", n=2)
    reel("DEMO4", "Movies", "Parasite", "caption", "movie name: Parasite", "ko", n=3)
    reel("DEMO5", "Movies", "3 Idiots", "speech", "watch 3 Idiots this weekend", "hi", n=4, author="creator_c")
    reel("DEMO6", "Movies", "Vikram Vedha", "comment", "its Vikram Vedha", "ta", n=5)
    dark = reel("DEMO7", "Movies", "Dark", "text", "DARK", "en", conf="check", n=6)
    lib.x("UPDATE finds SET alts=? WHERE item_id=?", ('[{"ext_key": "wikidata:Q1167447", "name": "Dark", "type": "movie", "year": 2005, "language": "English"}]', dark))
    lib.add_item("reel:IDLE1", "reel", "https://www.instagram.com/reel/IDLE1/", ["Movies"], status="idle")
    lib.add_item("reel:IDLE2", "reel", "https://www.instagram.com/reel/IDLE2/", ["Manga"], status="idle")

    shot, _ = lib.add_item("img:demo-shot", "image", str(media / "img_demo.jpg"), ["Screenshots"], status="done")
    _img(media / "img_demo.jpg", COLORS[0], "screenshot")
    lib.merge_meta(shot, thumb="img_demo.jpg", ocr="")
    lib.add_find(shot, "title", title_id=tids["Vinland Saga"], name_raw="Vinland Saga", source="scene", evidence="trace.moe 96% match",
                 confidence="matched", detail="Episode 12 · at 8:41", score=0.96)
    unsure, _ = lib.add_item("img:demo-unsure", "image", str(media / "img_unsure.jpg"), ["Screenshots"], status="check")
    _img(media / "img_unsure.jpg", COLORS[3], "panel")
    lib.merge_meta(unsure, thumb="img_unsure.jpg", ocr="")
    lib.add_find(unsure, "title", title_id=tids["Vagabond"], name_raw="Vagabond", source="ai", evidence="ink style samurai panel", confidence="check", score=0.3)
    lib.add_find(unsure, "title", title_id=lib.upsert_title("name:berserk", "Berserk", type="manga"), name_raw="Berserk", source="ai",
                 evidence="dark fantasy panel", confidence="check", score=0.2)

    words = [{"w": w, "s": 0.4 + i * 0.4, "e": 0.75 + i * 0.4} for i, w in enumerate("Start before you feel ready.".split())]
    for k, (q, author) in enumerate([("Start before you feel ready.", "creator_d"), ("Rest if you must, but do not quit.", "creator_e")]):
        iid, _ = lib.add_item(f"reel:QUOTE{k}", "reel", f"https://www.instagram.com/reel/QUOTE{k}/", ["Motivation"], status="done")
        _img(media / f"reel_{iid}.jpg", COLORS[k + 4], q)
        name = ""
        if shutil.which("ffmpeg"):
            vid = media / f"reel_{iid}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3B3530:s=360x640:d=3", "-f", "lavfi", "-i", "sine=f=220:d=3",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)], check=False)
            if vid.exists():
                from . import gif
                try:
                    name = gif.make_clip(vid, media / f"quote_{iid}_bold.gif", 0.4, 2.4, words, "bold", "gif").name
                except RuntimeError:
                    name = ""
        lib.merge_meta(iid, thumb=f"reel_{iid}.jpg", author=author, reel_language="en", quote_words=words, quote_span=[0.4, 2.4], favorite=1 if k == 0 else 0)
        lib.add_find(iid, "quote", quote=q, source="speech", confidence="confirmed", media=name, detail="0.40-2.40")
    return lib
