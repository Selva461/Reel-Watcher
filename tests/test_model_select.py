"""Model selection logic (no downloads, no model loading)."""
import pytest

from reel_watcher.model import SIZES, select_models

GB = 1024**3


def test_auto_small_below_32gb():
    assert select_models(env={}, ram_bytes=16 * GB)[2] == "small"
    assert select_models(env={}, ram_bytes=24 * GB)[2] == "small"


def test_auto_large_at_32gb_and_up():
    assert select_models(env={}, ram_bytes=32 * GB)[2] == "large"
    assert select_models(env={}, ram_bytes=64 * GB)[0] == SIZES["large"][0]


def test_explicit_size_beats_ram():
    assert select_models("large", env={}, ram_bytes=8 * GB)[2] == "large"
    assert select_models("small", env={}, ram_bytes=128 * GB) == (*SIZES["small"], "small")


def test_env_size_and_flag_precedence():
    assert select_models(env={"REEL_WATCHER_MODEL": "small"}, ram_bytes=64 * GB)[2] == "small"
    assert select_models("large", env={"REEL_WATCHER_MODEL": "small"})[2] == "large"


def test_model_override_keeps_whisper_of_size():
    vlm, whisper, size = select_models("small", model="org/custom", env={})
    assert (vlm, whisper, size) == ("org/custom", SIZES["small"][1], "small")


def test_env_repo_overrides():
    vlm, whisper, _ = select_models("small", env={"REEL_WATCHER_VLM": "a/b", "REEL_WATCHER_WHISPER": "c/d"})
    assert (vlm, whisper) == ("a/b", "c/d")
    assert select_models("small", model="x/y", env={"REEL_WATCHER_VLM": "a/b"})[0] == "x/y"


def test_bad_size():
    with pytest.raises(ValueError):
        select_models("huge", env={})


def test_total_ram_is_int():
    from reel_watcher.model import total_ram_bytes
    assert isinstance(total_ram_bytes(), int)


def test_vision_ollama_request(tmp_path, monkeypatch):
    from reel_watcher import model
    img = tmp_path / "s.jpg"
    img.write_bytes(b"abc")
    sent = []

    def fake(path, body=None, timeout=900):
        sent.append((path, body))
        return {"message": {"content": "not json" if len(sent) == 1 else '{"ok": true}'}}
    monkeypatch.setattr(model, "ollama_request", fake)
    v = model.Vision.__new__(model.Vision)
    v.model = "qwen2.5vl:7b"
    assert v.ask("describe", str(img), max_tokens=100) == {"ok": True}
    (p1, b1), (_, b2) = sent
    assert p1 == "/api/chat" and b1["model"] == "qwen2.5vl:7b" and b1["messages"][0]["images"] == ["YWJj"]
    assert b1["options"]["num_predict"] == 100 and b2["options"]["num_predict"] == 200
    assert b2["options"]["repeat_penalty"] == 1.15 and model.RETRY_HINT in b2["messages"][0]["content"]


def test_ensure_model_hint_when_ollama_down(monkeypatch):
    import urllib.error
    from reel_watcher import model

    def down(*a, **k):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(model, "ollama_request", down)
    with pytest.raises(RuntimeError, match="ollama.com/download"):
        model.ensure_ollama_model("qwen2.5vl:7b")
