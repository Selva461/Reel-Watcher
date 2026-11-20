"""The phone procedure for the notes evaluation (A3-4; design: docs/design/A3-prompt-budget.md, "On a real phone later").

`python tests/notes_eval.py make-backup` writes the synthetic fixture as a Reel Shelf backup ZIP; the owner restores it on a phone,
runs Start, taps Back up now and copies the new ZIP back; `python tests/notes_eval.py check ZIP` judges what the app stored.

What these tests can and cannot prove without a phone:

* the ZIP is the same bytes on every run and its manifest and hashes match its entries (pure Python, below);
* the app's REAL reader (LibraryBackup.check and LibraryFile.replaceWith of the S4-3 branch, Java) accepts it: that needs the
  Android toolchain's javac and org.json, so it was run by hand and recorded in the pull request, not here;
* `check` on good, bad, failed and hostile files, with the page's own `Notes.parse` and `Notes.FORMAT`, and on what the real page
  stores after a run with a fake bridge (so the field names `check` reads are the ones the page writes).

Everything is generated placeholder text; no real reel data."""
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

import notes_eval as ne
from test_notes_eval import CORPUS, GOOD  # the answers the checker is tested with (no test_ name is imported, so nothing runs twice)
from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)

SCRIPT = ne.HERE / "notes_eval.py"
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(ne.ROOT / "src"), os.environ.get("PYTHONPATH", "")) if p)}

# The keys the app's own writer puts in a manifest (LibraryBackup.write on the S4-3 branch) and in the counts (BackupNow.counts).
REAL_MANIFEST_KEYS = {"format", "format_version", "created_at", "app", "files", "counts", "contains"}
REAL_APP_KEYS = {"version_name", "version_code"}
REAL_FILE_KEYS = {"bytes", "sha256", "schema_version"}
REAL_COUNT_KEYS = {"reels", "titles", "screenshots"}


def cli(*args, cwd=None, env=ENV):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env)


def reel(code, **fields):
    return {"code": code, "url": f"https://example.invalid/reel/{code}/", "author": "eval_creator_01", "collections": ["eval"], "status": "new",
            "added_at": 1, "caption_read": 1, "video_tried": 1, **fields}


def done(code, text, **fields):
    """A reel the on-phone AI wrote notes for: the answer text is in `raw`, as the page's setNotes stores it."""
    return reel(code, status="done", notes_by="phone", notes={"topic": "x"}, raw=text, **fields)


def library(reels):
    return {"reels": reels, "inbox": [], "media": [], "mediaTypes": [], "schema_version": 1}


def backup(tmp_path, reels, name="after.zip"):
    path = tmp_path / name
    path.write_bytes(ne.backup_bytes(library(reels)))
    return path


def parts_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def raw_zip(path, entries, method=zipfile.ZIP_DEFLATED):
    """A ZIP with exactly these (name, bytes) entries, written without any of the checks that ne.backup_bytes makes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # zipfile warns about a duplicate name
        with zipfile.ZipFile(path, "w", method) as z:
            for name, data in entries:
                z.writestr(name, data)
    return path


def manifest_for(reels_bytes, **over):
    """A good manifest for reels_bytes, with the given keys replaced."""
    m = json.loads(parts_of(ne.backup_bytes())["manifest.json"])
    m["files"]["reels.json"].update(bytes=len(reels_bytes), sha256=hashlib.sha256(reels_bytes).hexdigest())
    m.update(over)
    return json.dumps(m).encode()


def blocks(out, codes):
    """{code: the line `check` prints for that reel and the indented lines under it}."""
    lines, got = out.splitlines(), {}
    for i, line in enumerate(lines):
        if line.split(" ")[0] in codes:
            j = i + 1
            while j < len(lines) and lines[j].startswith(" " * 16):   # the lines under a reel are indented to its column
                j += 1
            got[line.split(" ")[0]] = "\n".join(lines[i:j])
    return got


def verdict_lines(out):
    """{code: (verdict, [failed rules])} from the lines `check` prints for the reels that have an answer."""
    got = {}
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+(PASS|FAIL)  (.*)$", line)
        if m:
            got[m.group(1)] = (m.group(2), re.findall(r"(\w+) FAIL", m.group(3)))
    return got


# ---------------------------------------------------------------- make-backup (pure Python)

def test_the_backup_is_the_same_bytes_on_every_run(tmp_path):
    first = ne.backup_bytes()
    assert ne.backup_bytes() == first
    out = tmp_path / "a.zip"
    done_ = cli("make-backup", "--out", str(out), cwd=tmp_path, env={**ENV, "PYTHONHASHSEED": "random"})   # another process, its own string-hash seed
    assert done_.returncode == 0, done_.stderr
    assert out.read_bytes() == first
    here = tmp_path / "cwd"
    here.mkdir()
    assert cli("make-backup", cwd=here).returncode == 0   # the default name, in the folder it is run from
    assert (here / "notes-eval-backup.zip").read_bytes() == first


def test_the_backup_has_exactly_the_entries_and_manifest_keys_the_app_writes_and_the_hashes_match():
    data = ne.backup_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None and z.comment == b""
        assert z.namelist() == ["reels.json", "manifest.json"]   # manifest last, as LibraryBackup writes it; shots.json is optional and left out
        for info in z.infolist():   # nothing in an entry depends on the day, the platform or the zlib that made it
            assert (info.date_time, info.compress_type, info.flag_bits, info.extra, info.comment, info.create_system) == ((2026, 1, 1, 0, 0, 0), zipfile.ZIP_STORED, 0, b"", b"", 3)
    parts = parts_of(data)
    m = json.loads(parts["manifest.json"])
    assert set(m) == REAL_MANIFEST_KEYS and set(m["app"]) == REAL_APP_KEYS and set(m["counts"]) == REAL_COUNT_KEYS
    assert set(m["files"]) == {"reels.json"} and set(m["files"]["reels.json"]) == REAL_FILE_KEYS
    assert m["format"] == "reelshelf-backup" and m["format_version"] == 1 and type(m["format_version"]) is int
    assert m["created_at"] == "2026-01-01T00:00:00Z" and isinstance(m["app"]["version_name"], str) and isinstance(m["app"]["version_code"], int)
    f = m["files"]["reels.json"]
    assert f["bytes"] == len(parts["reels.json"]) and f["sha256"] == hashlib.sha256(parts["reels.json"]).hexdigest() and f["schema_version"] == 1
    assert m["counts"] == {"reels": 12, "titles": 0, "screenshots": 0}


def test_the_library_in_the_backup_is_the_fixture_with_nothing_written_yet():
    lib = json.loads(parts_of(ne.backup_bytes())["reels.json"])
    fx = ne.load_fixture()
    assert set(lib) == {"reels", "inbox", "media", "mediaTypes", "schema_version"} and lib["schema_version"] == 1
    assert lib["reels"] == fx["reels"] and [r["code"] for r in lib["reels"]] == [c["reel"]["code"] for c in ne.cases()]
    assert [r["code"] for r in lib["reels"]][:3] == ["EVAL001", "EVAL002", "EVAL003"] and len(lib["reels"]) == 12
    for r in lib["reels"]:   # Start has work to do: nothing is written, and nothing is left from a run
        assert r["status"] == "new" and not {"notes", "notes_by", "raw", "error", "last_fail", "tries"} & set(r), r["code"]
    text = json.dumps(lib, ensure_ascii=False)
    assert "localExtra" not in text and "instagram" not in text.lower() and "@" not in text and chr(0x2014) not in text   # the 'Also:' text is a setting, not a reel field
    assert all(r["url"].startswith("https://example.invalid/") for r in lib["reels"])


def test_make_backup_says_how_to_type_the_extra_instruction(tmp_path):
    done_ = cli("make-backup", "--out", str(tmp_path / "e.zip"))
    assert done_.returncode == 0, done_.stderr
    out = done_.stdout
    assert "EVAL004: 2,000 characters" in out and "EVAL011: 2,000 characters" in out and "localExtra" in out
    assert ne.EXTRA_SETTING in out and "Restore from a backup" in out and "Save a backup of the current library first" in out


def test_every_checker_rule_has_a_plain_explanation():
    assert set(ne.RULE_HELP) == set(ne.RULES)


# ---------------------------------------------------------------- check: good, bad, failed, none

def test_check_prints_pass_for_every_reel_with_a_good_answer_and_exits_0(tmp_path):
    good = [build(None) for build, breaks in CORPUS.values() if not breaks]
    reels = [done(f"C{i:03d}", t) for i, t in enumerate(good)]
    reels += [reel("E011", status="ready_no_text", error="Instagram gave too little to work from"), reel("E012")]   # nothing to read: not a failure of the AI
    done_ = cli("check", str(backup(tmp_path, reels)))
    assert done_.returncode == 0, done_.stdout + done_.stderr
    got = verdict_lines(done_.stdout)
    assert got == {f"C{i:03d}": ("PASS", []) for i in range(len(good))} and len(good) >= 8
    assert "RESULT: PASS" in done_.stdout and f"{len(reels)} reels: {len(good)} PASS, 0 FAIL, 2 without answer text (0 of them failed on the phone)" in done_.stdout


def test_check_exits_1_and_names_the_rule_when_one_answer_is_bad(tmp_path):
    cut = GOOD[:GOOD.index("TAGS:")]
    reels = [done("G1", GOOD), done("BAD", cut), done("G2", GOOD)]
    done_ = cli("check", str(backup(tmp_path, reels)))
    assert done_.returncode == 1, done_.stdout + done_.stderr
    assert verdict_lines(done_.stdout) == {"G1": ("PASS", []), "BAD": ("FAIL", ["sections", "complete", "limits"]), "G2": ("PASS", [])}
    assert "complete: " + ne.RULE_HELP["complete"] in done_.stdout and "RESULT: FAIL" in done_.stdout and "1 FAIL" in done_.stdout


def test_check_gives_the_checkers_verdict_for_every_answer_of_the_corpus(phone, tmp_path):
    """The whole corpus of test_notes_eval.py through the real command: each answer gets the verdict check_answer is tested to give.
    The last reel's answer is longer than the 20,000 characters the app keeps: only the first 20,000 are judged."""
    phone.open_with()
    template = phone.evaluate("() => Notes.FORMAT")
    answers = {name: build(template) for name, (build, _) in CORPUS.items() if name != "an_empty_answer"}
    reels = [done(f"C{i:03d}", text) for i, text in enumerate(answers.values())]
    reels.append(done("CAPPED", GOOD + "\n" * 25000 + GOOD))   # a second copy of the answer after the cap would break `order`
    reels.append(reel("EMPTY", status="done", notes_by="phone", raw=""))
    done_ = cli("check", str(backup(tmp_path, reels)))
    got = verdict_lines(done_.stdout)
    want = {f"C{i:03d}": ("FAIL" if CORPUS[n][1] else "PASS", sorted(CORPUS[n][1])) for i, n in enumerate(answers)}
    assert {k: (v, sorted(r)) for k, (v, r) in got.items() if k.startswith("C0")} == want
    assert got["CAPPED"] == ("PASS", []) and "EMPTY" not in got
    assert done_.returncode == 1 and sum(1 for v, _ in want.values() if v == "FAIL") >= 15
    assert all(f"{rule}: {text}" in done_.stdout for rule, text in ne.RULE_HELP.items())   # every rule broke somewhere in the corpus
    assert "no answer text: the app does not keep the text of an answer that failed" in done_.stdout


def test_check_shows_the_reason_and_no_verdict_for_a_reel_that_failed(tmp_path):
    reels = [done("GOOD1", GOOD),
             reel("F1", status="failed", tries=3, last_fail="The AI model failed: out of memory", last_fail_at=5, error="older text"),
             reel("F2", status="failed", error="The on-phone AI's answer was not in the notes format. Try again, or Ask Meta AI."),   # the page of today: only `error`
             reel("Q1", status="done", notes_by="auto", notes={"topic": "x"}),
             reel("N1")]
    done_ = cli("check", str(backup(tmp_path, reels)))
    block = blocks(done_.stdout, ("F1", "F2", "Q1", "N1"))
    assert set(block) == {"F1", "F2", "Q1", "N1"}
    assert done_.returncode == 1, done_.stdout   # a reel that failed on the phone is a failed evaluation, not a pass
    assert set(verdict_lines(done_.stdout)) == {"GOOD1"}   # no PASS or FAIL for the others
    assert all("no answer text" in b and "PASS" not in b and "FAIL" not in b for b in block.values()), block
    assert "status failed, notes by -, 3 tries" in block["F1"] and "reason: The AI model failed: out of memory" in block["F1"] and "older text" not in block["F1"]
    assert "reason: The on-phone AI's answer was not in the notes format." in block["F2"]
    assert "quick notes written without the AI" in block["Q1"] and "status new" in block["N1"]
    assert "5 reels: 1 PASS, 0 FAIL, 4 without answer text (2 of them failed on the phone)" in done_.stdout and "RESULT: FAIL" in done_.stdout


def test_check_with_no_answer_text_at_all_is_not_a_pass(tmp_path, capsys):
    assert ne.main(["check", str(backup(tmp_path, [reel("N1"), reel("N2", status="ready_no_text", error="too little")]))]) == 1
    out = capsys.readouterr().out
    assert "nothing to judge" in out and "RESULT: PASS" not in out


def test_check_says_so_when_chromium_cannot_start_and_judges_nothing(tmp_path, monkeypatch, capsys):
    def boom(texts):
        raise OSError("no browser here")
    monkeypatch.setattr(ne, "parse_with_page", boom)
    assert ne.main(["check", str(backup(tmp_path, [done("G1", GOOD)]))]) == 3
    captured = capsys.readouterr()
    assert "playwright install chromium" in captured.err and "PASS" not in captured.out


def test_what_check_prints_from_the_file_cannot_move_the_terminal(tmp_path, capsys):
    reels = [reel("\x1b[31mRED\x1b[0m", status="fail\ned", notes_by="‮evil", error="x\x00y\x07\ry" + "z" * 1000)]
    assert ne.main(["check", str(backup(tmp_path, reels))]) == 1
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x00" not in out and "\x07" not in out and "\r" not in out and "‮" not in out
    assert "RED" in out and len(max(out.splitlines(), key=len)) < 500   # a long reason is cut


# ---------------------------------------------------------------- check: the page's own parser, and what the page really stores

def test_check_reads_the_notes_the_same_way_the_whole_page_does(phone):
    phone.open_with()
    texts = [b(None) for b, _ in CORPUS.values()] + [GOOD]
    page_parsed = phone.evaluate("(ts) => ts.map((t) => Notes.parse(t))", texts)
    page_template = phone.evaluate("() => Notes.FORMAT")
    with ThreadPoolExecutor(1) as pool:   # notes.js alone, in a Chromium of its own (a thread of its own: the fixture's Playwright holds this one)
        template, parsed = pool.submit(ne.parse_with_page, texts).result()
    assert template == page_template and parsed == page_parsed


def test_check_judges_what_the_page_stores_after_a_run(phone, tmp_path):
    """Restore is Java and cannot run here; the rest of the procedure can: the page opens the library of the backup, Start writes
    notes with the on-phone AI (a fake bridge answers), the library file is backed up, and `check` reads what the page stored."""
    lib = json.dumps(ne.backup_library(), ensure_ascii=False)
    cut = GOOD[:GOOD.index("TAGS:")]   # in the notes format, but cut off before TAGS: the page keeps it and `check` fails it
    refusal = "I'm sorry, but I can't help with that request."   # not in the format: the page keeps no text, only the reason
    answers = [GOOD] * 8 + [cut, refusal]   # the 11th reel gets no answer: the fake bridge says "The AI model failed: out of memory"
    phone.open_with({"db": lib, "model": {"ready": True, "partial": 0, "installed": []}, "answers": answers}, "#/inbox")
    phone.get_by_role("button", name="Start 11", exact=True).click()   # 11 of the 12: EVAL012 is only a link, so there is nothing to write from
    phone.wait_for_function("() => typeof run !== 'undefined' && run && run.finished")
    order = phone.evaluate("() => run.codes")   # the page works through the reels in its own order: the answers are handed out in that order
    assert len(order) == 11 and "EVAL012" not in order
    stored = json.loads(phone.rn()["db"])
    by = {r["code"]: r for r in stored["reels"]}
    assert len(by) == 12 and by["EVAL012"]["status"] == "new" and "raw" not in by["EVAL012"]
    for code in order[:8]:
        assert by[code]["status"] == "done" and by[code]["notes_by"] == "phone" and by[code]["raw"] == GOOD, code
    assert by[order[8]]["raw"] == cut and by[order[8]]["status"] == "done"
    assert by[order[9]]["status"] == "failed" and "raw" not in by[order[9]] and "not in the notes format" in by[order[9]]["error"]
    assert by[order[10]]["status"] == "failed" and "raw" not in by[order[10]] and "out of memory" in by[order[10]]["error"]
    path = tmp_path / "after-run.zip"
    path.write_bytes(ne.backup_bytes(stored))   # what Back up now makes of the library file, in the same format
    done_ = cli("check", str(path))
    got = verdict_lines(done_.stdout)
    assert got == {**{c: ("PASS", []) for c in order[:8]}, order[8]: ("FAIL", ["sections", "complete", "limits"])}
    blk = blocks(done_.stdout, set(by))
    assert "not in the notes format" in blk[order[9]] and "out of memory" in blk[order[10]] and "no answer text" in blk["EVAL012"]
    assert done_.returncode == 1 and "12 reels: 8 PASS, 1 FAIL, 3 without answer text (2 of them failed on the phone)" in done_.stdout


def test_without_a_ready_model_there_is_nothing_to_start_for_these_reels(phone):
    """What TESTING.md tells the owner: these reels are read already, so with no model ready Start has nothing to do (no quick notes
    either), the tile has no number and `check` would have nothing to judge."""
    phone.open_with({"db": json.dumps(ne.backup_library(), ensure_ascii=False)}, "#/inbox")
    assert phone.locator("#start").count() == 0 and phone.locator("#goRun").inner_text().strip() == "Start"
    phone.locator("#goRun").click()
    phone.get_by_text("Nothing waiting").wait_for()
    assert phone.locator("#start").count() == 0


# ---------------------------------------------------------------- check: files that are not a backup (nothing is judged, exit 2)

def _bad_files(tmp_path):
    good = parts_of(ne.backup_bytes())
    reels, man = good["reels.json"], good["manifest.json"]
    lib_ok = b'{"reels":[]}'
    out = {}

    def add(name, entries, **kw):
        out[name] = raw_zip(tmp_path / (name + ".zip"), entries, **kw)

    out["not_a_zip"] = tmp_path / "text.zip"
    out["not_a_zip"].write_text("hello", encoding="utf-8")
    out["empty_file"] = tmp_path / "empty.zip"
    out["empty_file"].write_bytes(b"")
    out["a_folder"] = tmp_path
    out["missing"] = tmp_path / "nowhere.zip"
    out["truncated"] = tmp_path / "cut.zip"
    out["truncated"].write_bytes(ne.backup_bytes()[:60000])
    add("empty_zip", [])
    add("a_bare_reels_json", [("reels.json", reels)])
    add("a_notes_export", [("reel-notes-20260101.json", b'{"reels":[]}')])
    add("no_manifest_but_a_folder", [("evidence/", b""), ("reels.json", reels)])
    add("no_reels_json", [("manifest.json", man)])
    add("manifest_not_json", [("reels.json", reels), ("manifest.json", b"not json")])
    add("manifest_not_an_object", [("reels.json", reels), ("manifest.json", b"[1]")])
    add("manifest_in_latin_1", [("reels.json", reels), ("manifest.json", "{\"a\":\"é\"}".encode("latin-1"))])
    add("another_format", [("reels.json", reels), ("manifest.json", manifest_for(reels, format="something-else"))])
    add("a_newer_format_version", [("reels.json", reels), ("manifest.json", manifest_for(reels, format_version=2))])
    add("format_version_0", [("reels.json", reels), ("manifest.json", manifest_for(reels, format_version=0))])
    add("format_version_a_string", [("reels.json", reels), ("manifest.json", manifest_for(reels, format_version="1"))])
    add("format_version_a_flag", [("reels.json", reels), ("manifest.json", manifest_for(reels, format_version=True))])
    add("format_version_1_5", [("reels.json", reels), ("manifest.json", manifest_for(reels, format_version=1.5))])
    add("manifest_lists_no_files", [("reels.json", reels), ("manifest.json", manifest_for(reels, files={}))])
    add("manifest_hash_wrong", [("reels.json", reels), ("manifest.json", man.replace(hashlib.sha256(reels).hexdigest().encode(), b"0" * 64))])
    add("manifest_bytes_wrong", [("reels.json", reels), ("manifest.json", man.replace(b'"bytes":%d' % len(reels), b'"bytes":1'))])
    add("reels_changed_after_the_manifest", [("reels.json", reels.replace(b"EVAL001", b"EVAL0x1", 1)), ("manifest.json", man)])
    add("reels_not_json", [("reels.json", b"not json"), ("manifest.json", manifest_for(b"not json"))])
    add("reels_not_an_object", [("reels.json", b"[]"), ("manifest.json", manifest_for(b"[]"))])
    add("reels_without_a_list", [("reels.json", b'{"reels":5}'), ("manifest.json", manifest_for(b'{"reels":5}'))])
    add("reels_nested_too_deep", [("reels.json", b'{"reels":' + b"[" * 300000 + b"]" * 300000 + b"}"), ("manifest.json", manifest_for(b'{"reels":' + b"[" * 300000 + b"]" * 300000 + b"}"))])
    add("an_entry_twice", [("reels.json", reels), ("manifest.json", man), ("manifest.json", man)])
    add("an_extra_entry", [("reels.json", reels), ("manifest.json", man), ("notes.txt", b"hi")])
    add("a_folder_entry", [("reels.json", reels), ("manifest.json", man), ("shots.json/", b"")])
    add("upper_case_name", [("Reels.json", reels), ("manifest.json", man)])
    add("a_name_with_a_space", [("reels.json ", reels), ("manifest.json", man)])
    add("a_name_in_a_folder", [("backup/reels.json", reels), ("manifest.json", man)])
    add("a_dot_slash_name", [("./reels.json", reels), ("manifest.json", man)])
    add("a_name_with_backslashes", [("..\\reels.json", reels), ("manifest.json", man)])
    add("zip_slip_dots", [("reels.json", reels), ("manifest.json", man), ("../zipslip-evil.txt", b"pwned")])
    add("zip_slip_deep", [("reels.json", reels), ("manifest.json", man), ("a/../../zipslip-evil.txt", b"pwned")])
    add("zip_slip_absolute", [("reels.json", reels), ("manifest.json", man), (str(tmp_path / "abs" / "zipslip-evil.txt"), b"pwned")])
    add("compressed_with_bzip2", [("reels.json", reels), ("manifest.json", man)], method=zipfile.ZIP_BZIP2)
    add("compressed_with_lzma", [("reels.json", reels), ("manifest.json", man)], method=zipfile.ZIP_LZMA)
    # a name that Python's zipfile reads as "reels.json" (it cuts a name at a NUL) but the app's reader sees whole
    hidden = raw_zip(tmp_path / "nul.zip", [("reels.jsonXevil", reels), ("manifest.json", man)], method=zipfile.ZIP_STORED)
    hidden.write_bytes(hidden.read_bytes().replace(b"reels.jsonXevil", b"reels.json\x00evil"))
    out["a_name_cut_at_a_nul"] = hidden
    assert lib_ok
    return out


BAD_FILES = ["not_a_zip", "empty_file", "a_folder", "missing", "truncated", "empty_zip", "a_bare_reels_json", "a_notes_export", "no_manifest_but_a_folder",
             "no_reels_json", "manifest_not_json", "manifest_not_an_object", "manifest_in_latin_1", "another_format", "a_newer_format_version",
             "format_version_0", "format_version_a_string", "format_version_a_flag", "format_version_1_5", "manifest_lists_no_files", "manifest_hash_wrong",
             "manifest_bytes_wrong", "reels_changed_after_the_manifest", "reels_not_json", "reels_not_an_object", "reels_without_a_list",
             "reels_nested_too_deep", "an_entry_twice", "an_extra_entry", "a_folder_entry", "upper_case_name", "a_name_with_a_space", "a_name_in_a_folder",
             "a_dot_slash_name", "a_name_with_backslashes", "zip_slip_dots", "zip_slip_deep", "zip_slip_absolute", "compressed_with_bzip2",
             "compressed_with_lzma", "a_name_cut_at_a_nul"]


def test_check_exits_2_and_judges_nothing_for_everything_that_is_not_a_backup(tmp_path, capsys):
    files = _bad_files(tmp_path)
    assert sorted(files) == sorted(BAD_FILES)
    for name in BAD_FILES:
        assert ne.main(["check", str(files[name])]) == 2, name
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err.startswith("check: ") and "cannot be used" in captured.err, (name, captured)


def test_check_still_accepts_a_backup_that_has_the_optional_shots_file_and_a_deflated_zip(tmp_path):
    good = parts_of(ne.backup_bytes())
    shots = b'{"v":1,"seen":{},"reels":{}}'
    path = raw_zip(tmp_path / "app.zip", [("reels.json", good["reels.json"]), ("shots.json", shots), ("manifest.json", good["manifest.json"])])   # as the app writes: DEFLATED
    assert ne.read_backup(path)[1]["reels"][0]["code"] == "EVAL001"


def test_check_reads_a_backup_with_a_newer_schema_although_the_app_would_refuse_it(tmp_path):
    """Said in the docstrings of read_backup and check: the app's NEWER_SCHEMA rule is not applied here."""
    lib = library([done("G1", GOOD)])
    lib["schema_version"] = 99
    reels = json.dumps(lib).encode()
    man = json.loads(manifest_for(reels))
    man["files"]["reels.json"]["schema_version"] = 99
    path = raw_zip(tmp_path / "newer.zip", [("reels.json", reels), ("manifest.json", json.dumps(man).encode())])
    assert ne.read_backup(path)[1]["schema_version"] == 99


def test_check_never_reads_more_than_its_limits_from_a_file(tmp_path, monkeypatch, capsys):
    good = parts_of(ne.backup_bytes())
    bomb = b'{"reels":[],"pad":"' + b"0" * 2_000_000 + b'"}'   # 2 MB that deflates to a few KB
    path = raw_zip(tmp_path / "bomb.zip", [("reels.json", bomb), ("manifest.json", manifest_for(bomb))])
    assert path.stat().st_size < 20000
    monkeypatch.setattr(ne, "MAX_JSON_BYTES", 100000)
    served, real_open = [], zipfile.ZipFile.open

    class Spy:   # how many bytes of an entry the reader asks for and gets: never the whole 2 MB, only one more than the limit
        def __init__(self, f):
            self.f = f

        def read(self, n=-1):
            data = self.f.read(n)
            served.append(len(data))
            return data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

    monkeypatch.setattr(zipfile.ZipFile, "open", lambda self, *a, **k: Spy(real_open(self, *a, **k)))
    assert ne.main(["check", str(path)]) == 2 and "reels.json\" is bigger than 100,000 bytes" in capsys.readouterr().err
    assert max(served) == 100001   # the limit and one byte more, to see that it is over
    monkeypatch.setattr(zipfile.ZipFile, "open", real_open)
    fat = raw_zip(tmp_path / "fat.zip", [("reels.json", good["reels.json"]), ("manifest.json", b'{"pad":"' + b" " * 3000 + b'"}')])
    monkeypatch.setattr(ne, "MAX_MANIFEST_BYTES", 1000)
    assert ne.main(["check", str(fat)]) == 2 and "manifest.json\" is bigger than 1,000 bytes" in capsys.readouterr().err
    monkeypatch.setattr(ne, "MAX_ZIP_BYTES", 1000)
    assert ne.main(["check", str(path)]) == 2 and "bigger than 1,000 bytes" in capsys.readouterr().err


def test_the_real_limits_are_set():
    assert ne.MAX_ZIP_BYTES == ne.MAX_JSON_BYTES == 64 << 20 and ne.MAX_MANIFEST_BYTES == 1 << 20   # the app's own manifest limit


def test_a_zip_slip_name_is_never_extracted_anywhere(tmp_path, monkeypatch):
    """Entries are read in memory. Run the real command with its working folder and its temp folder empty, and with a name that
    would land next to them if anything were extracted; afterwards nothing exists that was not there before."""
    (tmp_path / "zips").mkdir()
    files = _bad_files(tmp_path / "zips")
    work, temp = tmp_path / "cwd", tmp_path / "tmp"
    work.mkdir()
    temp.mkdir()
    env = {**ENV, "TMPDIR": str(temp), "TEMP": str(temp), "TMP": str(temp)}
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    for name in ("zip_slip_dots", "zip_slip_deep", "zip_slip_absolute", "a_name_cut_at_a_nul"):
        done_ = cli("check", str(files[name]), cwd=work, env=env)
        assert done_.returncode == 2 and done_.stdout == "", (name, done_)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before
    assert not list(work.iterdir()) and not list(temp.iterdir()) and not (tmp_path / "zipslip-evil.txt").exists() and not (tmp_path / "abs").exists()
    # in this process too, so a read that extracts "just to look" cannot hide behind a child's temp folder
    monkeypatch.chdir(work)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    for name in ("zip_slip_dots", "zip_slip_deep", "zip_slip_absolute"):
        assert ne.main(["check", str(files[name])]) == 2
    assert not list(work.iterdir()) and not list(temp.iterdir()) and not (tmp_path / "zipslip-evil.txt").exists()


# ---------------------------------------------------------------- the placeholder rule of the checker, now that it judges a file that is not ours

def test_a_long_run_of_blank_lines_is_checked_in_linear_time_and_the_rule_still_means_one_line():
    template = "TOPIC: one short line\nPOINTS:\n1. every useful point in the order it comes\n2. ...\nTAGS: 5 to 8 short tags, separated by commas"
    start = time.time()
    assert not ne.echoes("\n" * 60000, template) and not ne.echoes("  \n" * 20000 + "1. x", template)   # with \s* these took seconds each
    assert time.time() - start < 3
    assert ne.echoes("TOPIC: x\nPOINTS:\n1. a\n2. ...\nTAGS: a, b", template) and ne.echoes("1. a\r\n2. ...\r\n3. b", template)
    assert not ne.echoes("1. a\n2.\n...\n3. b", template)   # "2." and "..." on two lines is not the template's "2. ..."


# ---------------------------------------------------------------- the heading and the topic rules, on runs of blanks (review of A3-4)

OLD_HEAD = re.compile(r"^[\s>#*_]*(" + "|".join(s.replace(" ", r"\s+") for s in sorted(ne.SECTIONS, key=len, reverse=True)) +
                      r")\s*[*_]*\s*(?:[:：–-]\s*[*_]*\s*(.*)|$)", re.I)   # the form before: quadratic on a heading and thousands of blanks


def old_topic(topic):   # the form before: its [..]+$ is quadratic on thousands of such characters in the middle of the text
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`|^[\s*_\"']+|[\s*_\"']+$", "", topic)).strip()


SLOW_BEFORE = {   # each took seconds before: 3.1 s, 3.1 s, 1.3 s, 1.3 s (the app keeps 20,000 characters of an answer at most)
    "a heading and blanks": "TOPIC" + " " * 19990 + "x",
    "a heading and tabs": "TAGS" + "\t" * 19990 + "x",
    "a topic with blanks in the middle": "TOPIC: a" + " " * 19990 + "x",
    "a topic with blanks and stars in the middle": "TOPIC: a" + " *" * 9990 + "x",
}


def test_a_heading_or_a_topic_with_thousands_of_blanks_is_checked_in_linear_time():
    template = "TOPIC: one short line\nPOINTS:\n1. every useful point in the order it comes\n2. ...\nTAGS: 5 to 8 short tags, separated by commas"
    start = time.time()
    for text in SLOW_BEFORE.values():
        assert len(text) <= ne.RAW_MAX
        ne.check_answer(text, lambda _t: None, template)
    assert time.time() - start < 1.0, "the four answers took " + format(time.time() - start, ".1f") + " s (about 9 s before the fix)"


def test_a_file_of_twenty_such_answers_is_judged_in_seconds(tmp_path):
    reels = [done(f"H{i:02d}", list(SLOW_BEFORE.values())[i % 4]) for i in range(20)]   # 68 s before the fix
    start = time.time()
    done_ = cli("check", str(backup(tmp_path, reels)))
    assert time.time() - start < 15, done_.stdout[-300:]
    got = verdict_lines(done_.stdout)
    assert done_.returncode == 1 and len(got) == 20 and all(v == "FAIL" for v, _ in got.values())


def test_the_linear_heading_and_topic_rules_accept_exactly_what_the_old_ones_did():
    assert set(re.findall(r"[\s*_\"']", "".join(map(chr, range(0x110000))))) == set(ne._TRIM)   # rstrip's characters are the regex class
    rng = random.Random(7)
    pieces = [" ", "  ", "\t", " ", "　", "*", "**", "_", ":", "：", "–", "-", "#", ">", "\"", "'", "`", "a", "b c", "1.", "...",
              "TOPIC", "TAGS", "use  it   for", "USE IT FOR", "POINTS", "tone", "x", "TOPICS"]
    lines = GOOD.splitlines() + GOOD.replace("TOPIC:", "**TOPIC:**").splitlines()   # real answers, then 150,000 odd lines
    lines += ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 9))) for _ in range(150000)]
    different = []
    for line in lines:
        a, b = OLD_HEAD.match(line), ne._HEAD.match(line)
        if (a and (a.group(1), a.group(2))) != (b and (b.group(1), b.group(2))) or old_topic(line) != ne._clean_topic(line):
            different.append(line)
    assert not different, f"{len(different)} lines read differently, for example {different[:3]!r}"
