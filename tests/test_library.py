"""Part 1: library database and Instagram collections import (no network)."""
import json
import threading
import zipfile

from reel_watcher import ig_export
from reel_watcher.library import Library


def col_header(name):
    return {"title": "Collection", "string_map_data": {"Name": {"value": name}, "Creation Time": {"timestamp": 1}}}


def col_item(code, kind="reel"):
    return {"string_map_data": {"Name": {"href": f"https://www.instagram.com/{kind}/{code}/", "value": "creator_a"},
                                "Added Time": {"timestamp": 2}}}


def export_dict():
    return {"saved_saved_collections": [
        col_header("Movies"), col_item("M1"), col_item("M2"),
        col_header("Anime"), col_item("A1"), col_item("M2"),  # M2 is in two collections
        col_header("Empty"),
        col_header("Motivation"), col_item("Q1", "p"),
    ]}


def posts_dict():
    return {"saved_saved_media": [
        {"title": "x", "string_map_data": {"Saved on": {"href": f"https://www.instagram.com/reel/{c}/"}}}
        for c in ("M1", "M2", "A1", "Q1", "LOOSE1", "LOOSE1")]}


def test_parse_collections_official_layout():
    cols = ig_export.parse_collections(export_dict())
    assert list(cols) == ["Movies", "Anime", "Empty", "Motivation"]
    assert cols["Movies"] == ["https://www.instagram.com/reel/M1/", "https://www.instagram.com/reel/M2/"]
    assert cols["Anime"][1].endswith("/M2/") and cols["Empty"] == [] and cols["Motivation"] == ["https://www.instagram.com/p/Q1/"]


def test_parse_collections_label_values_layout():
    data = {"saved_saved_collections": [
        {"label_values": [{"label": "Name", "value": "Manga"}]},
        {"label_values": [{"label": "Name", "value": "creator", "href": "https://www.instagram.com/reel/G1/?igsh=x"}]},
    ]}
    assert ig_export.parse_collections(data) == {"Manga": ["https://www.instagram.com/reel/G1/"]}


def test_parse_collections_nested_layouts():
    """Newer exports keep each collection's items inside its entry instead of after a header."""
    vec = {"saved_saved_collections": [
        {"label_values": [{"label": "Name", "value": "Anime"},
                          {"label": "Items", "vec": [{"dict": [{"label": "Owner", "value": "creator_a"},
                                                               {"label": "URL", "href": "https://www.instagram.com/reel/V1/"}]},
                                                     {"dict": [{"label": "URL", "value": "https://www.instagram.com/p/V2/?igsh=1"}]}]}]},
        {"label_values": [{"label": "Collection name", "value": "Movies"},
                          {"label": "Items", "vec": [{"dict": [{"label": "URL", "href": "https://www.instagram.com/creator_b/reel/V3/"}]}]}]},
    ]}
    assert ig_export.parse_collections(vec) == {
        "Anime": ["https://www.instagram.com/reel/V1/", "https://www.instagram.com/p/V2/"],
        "Movies": ["https://www.instagram.com/creator_b/reel/V3/"]}
    wrapped = {"collections": {"items": [
        {"string_map_data": {"Name": {"href": "", "value": "Manga", "timestamp": 0}}},
        {"string_map_data": {"Name": {"href": "https://www.instagram.com/reel/W1/", "value": "creator", "timestamp": 0}}}]}}
    assert ig_export.parse_collections(wrapped) == {"Manga": ["https://www.instagram.com/reel/W1/"]}
    outline = ig_export.outline(vec)
    assert "label_values" in outline and "creator_a" not in outline and "V1" not in outline


def test_read_export_zip_and_unsorted(tmp_path):
    z = tmp_path / "instagram-export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("your_instagram_activity/saved/saved_collections.json", json.dumps(export_dict()))
        f.writestr("your_instagram_activity/saved/saved_posts.json", json.dumps(posts_dict()))
    cols = ig_export.read_export(z)
    assert cols[ig_export.UNSORTED] == ["https://www.instagram.com/reel/LOOSE1/"]
    folder = tmp_path / "unzipped" / "saved"
    folder.mkdir(parents=True)
    (folder / "saved_collections.json").write_text(json.dumps(export_dict()), encoding="utf-8")
    assert ig_export.read_export(tmp_path / "unzipped")["Anime"] == cols["Anime"]


def test_import_into_library_and_queue(tmp_path):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("saved_collections.json", json.dumps(export_dict()))
        f.writestr("saved_posts.json", json.dumps(posts_dict()))
    lib = Library(tmp_path / "data")
    counts = ig_export.import_into(lib, z)
    assert counts == {"Movies": 2, "Anime": 2, "Empty": 0, "Motivation": 1, ig_export.UNSORTED: 1}
    assert lib.counts()["total"] == 5  # M2 stored once
    m2 = lib.one("SELECT id FROM items WHERE key='reel:M2'")["id"]
    assert lib.item(m2)["collections"] == ["Anime", "Movies"]
    assert lib.claim_next("reel") is None  # idle until a collection is started
    cols = {c["name"]: c for c in lib.collections()}
    assert cols["Anime"]["items"] == 2 and cols["Anime"]["finished"] == 0
    job, n = lib.queue_collection("Anime")
    assert n == 2 and lib.job(job)["state"] == "running"
    got = [lib.claim_next("reel")["key"], lib.claim_next("reel")["key"]]
    assert sorted(got) == ["reel:A1", "reel:M2"] and lib.claim_next("reel") is None
    ig_export.import_into(lib, z)  # importing again adds nothing
    assert lib.counts()["total"] == 5


def test_pause_quota_and_resume_after_crash(tmp_path):
    lib = Library(tmp_path)
    job = lib.add_job("Scan", "folder")
    a, _ = lib.add_item("img:a", "image", "/a.jpg", ["Screenshots"], job_id=job)
    lib.set_job_state(job, "paused")
    assert lib.claim_next("image") is None
    lib.set_job_state(job, "running")
    assert lib.claim_next("image")["id"] == a
    assert lib.reset_stuck() == 1 and lib.item(a)["status"] == "waiting"  # killed mid-way: back in the queue
    lib.update_item(a, status="waiting_quota", next_try_at=9e18)
    assert lib.claim_next("image") is None
    lib.update_item(a, next_try_at=0)
    assert lib.claim_next("image")["id"] == a
    assert [lib.quota_take("trace", 2, "2026-01-01") for _ in range(3)] == [True, True, False]
    assert lib.quota_take("trace", 2, "2026-01-02")
    lib.quota_exhaust("sauce", "2026-01-01")
    assert not lib.quota_take("sauce", 100, "2026-01-01")


def test_titles_finds_and_threads(tmp_path):
    lib = Library(tmp_path)
    iid, _ = lib.add_item("reel:X", "reel", "u", ["Anime"])
    t = lib.upsert_title("anilist:1", "Frieren", type="anime", year=2023, genres=["Fantasy"])
    assert lib.upsert_title("anilist:1", "Frieren", language="Japanese") == t
    lib.add_find(iid, "title", title_id=t, source="speech", evidence="watch Frieren", confidence="confirmed")
    lib.update_title(t, watch="watched", favorite=1, bogus="x")
    got = lib.title(t)
    assert got["language"] == "Japanese" and got["genres"] == ["Fantasy"] and got["watch"] == "watched"
    assert got["finds"][0]["evidence"] == "watch Frieren"
    assert lib.collections()[0]["titles"] == 1

    for n in range(40):
        lib.add_item(f"img:{n}", "image", f"/{n}.jpg")
    claimed, lock = [], threading.Lock()

    def worker():
        while (it := lib.claim_next("image")) is not None:
            with lock:
                claimed.append(it["id"])
    ths = [threading.Thread(target=worker) for _ in range(4)]
    [th.start() for th in ths]
    [th.join() for th in ths]
    assert len(claimed) == 40 == len(set(claimed))  # no item is processed twice


def test_describe_unknown_layout(tmp_path):
    f = tmp_path / "saved_collections.json"
    f.write_text("﻿" + json.dumps({"something_new": [{"x": {"y": "https://www.instagram.com/stories/a/1/"}}]}), encoding="utf-8")
    assert ig_export.read_export(f) == {}
    assert ig_export.describe(f) == "saved_collections.json: {something_new: [1 x {x: {y: link}}]}"
