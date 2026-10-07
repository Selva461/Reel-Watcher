import json

import pytest

from reel_watcher import advice_library, cli, ig_export, media, model


def test_parse_json_strips_think_and_prose():
    assert model.parse_json('<think>x</think> here {"a": 1} done') == {"a": 1}
    assert model.parse_json("no json") is None
    assert model.parse_json("{broken") is None


def test_id_from_url():
    assert media.id_from_url("https://www.instagram.com/reel/ABC_1-x/?igsh=1") == "ig_ABC_1-x"
    assert media.id_from_url("https://instagram.com/p/Zz9/") == "ig_Zz9"
    assert media.id_from_url("https://example.com/reel/ABC/") is None


def test_export_parser_official_shape_and_walk(tmp_path):
    f = tmp_path / "saved_posts.json"
    f.write_text(json.dumps({"saved_saved_media": [
        {"title": "creator_a", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/AAA111/", "timestamp": 1}}},
        {"title": "creator_b", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/p/BBB222/?img_index=1", "timestamp": 2}}},
        {"title": "creator_a", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/AAA111/", "timestamp": 3}}},
        {"title": "x", "string_map_data": {"Saved on": {"href": "https://example.com/nope"}}},
    ]}))
    rows = ig_export.extract_urls(f, "Saved")
    assert [r["url"] for r in rows] == ["https://www.instagram.com/reel/AAA111/", "https://www.instagram.com/p/BBB222/"]
    assert rows[0]["creator"] == "creator_a" and rows[1]["collection"] == "Saved"


def test_export_html_and_cli(tmp_path, capsys):
    h = tmp_path / "saved.html"
    h.write_text('<a href="https://www.instagram.com/reel/HTML1/">x</a> <a href="https://www.instagram.com/reel/HTML1/">dup</a>')
    out = tmp_path / "urls.tsv"
    assert ig_export.main([str(h), "-o", str(out), "--collection", "Inbox"]) == 0
    assert out.read_text(encoding="utf-8") == "https://www.instagram.com/reel/HTML1/\tInbox\n"


def test_cli_usage(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["reel-watcher", "--help"])
    assert cli.main() == 0 and "study" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["reel-watcher", "bogus"])
    assert cli.main() == 2


def test_advice_renders_example(tmp_path):
    lib = json.load(open("examples/advice_library.json", encoding="utf-8"))
    html = advice_library.render(lib)
    assert "<h1>Advice library</h1>" in html and "creator_a" in html
    out = tmp_path / "a.html"
    assert advice_library.main(["--in", "examples/advice_library.json", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == html


def test_no_em_dash_in_repo_sources():
    from pathlib import Path
    bad = chr(0x2014)
    for p in list(Path("src").rglob("*.py")) + list(Path("tests").rglob("*.py")):
        assert bad not in p.read_text(encoding="utf-8"), p


def test_ollama_error_reason_is_readable(monkeypatch):
    import io
    import urllib.error

    from reel_watcher import model

    def fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", {},
                                     io.BytesIO(b'{"error":"model requires more system memory (3.9 GiB) than is available (2.1 GiB)"}'))
    monkeypatch.setattr(model.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 500: model requires more system memory"):
        model.ollama_request("/api/chat", {"x": 1})


def test_outdated_packages_are_reported(monkeypatch):
    from reel_watcher import security
    versions = {"pillow": "12.2.9", "yt-dlp": "2026.8.19"}
    monkeypatch.setattr(security.metadata, "version", lambda p: versions[p])
    out = security.outdated()
    assert len(out) == 1 and out[0].startswith("pillow 12.2.9 has known security problems")
    versions["pillow"] = "12.3.0"
    assert security.outdated() == []
