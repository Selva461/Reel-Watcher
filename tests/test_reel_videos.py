"""Whole reels from videos on the phone (Instagram's own Download, screen recordings, shared videos), and the
"@Media" creator bug from the export. The phone side (folders, frames, speech) is faked. No network."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)

VIDEO_RN = r"""
(() => {
  const st = window.__rn;
  const later = (fn) => setTimeout(fn, 5);
  Object.assign(st, Object.assign({ videos: [], videoRead: {}, vfolders: [] }, st));
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  Object.assign(window.RN, {
    videoFolders: () => JSON.stringify(st.vfolders),
    addVideoFolder: (id) => { const f = { uri: "content://x/tree/primary%3AMovies%2FInstagram", name: "Movies/Instagram" }; st.vfolders.push(f); keep(); later(() => rnDone(id, true, JSON.stringify(f))); },
    listVideos: (id) => later(() => rnDone(id, true, JSON.stringify(st.videos))),
    readLocalVideo: (id, k) => { st.calls.push(["readLocalVideo", k]); keep(); later(() => st.videoRead[k] ? rnDone(id, true, JSON.stringify(st.videoRead[k])) : rnDone(id, false, "Could not open the video")); },
  });
})();
"""

K = "content://x/tree/primary%3AMovies%2FInstagram/document/1"


def test_a_downloaded_reel_is_read_whole_and_replaces_the_caption_only_one(phone):
    phone.context.add_init_script(VIDEO_RN)
    reels = [{"code": "OLD1", "url": "https://www.instagram.com/reel/OLD1/", "author": "chef.ana", "status": "ready", "caption": "#food",
              "caption_read": 1, "video_tried": 1, "content": "caption", "added_at": 5, "collections": ["Food"]},
             {"code": "OTHER", "url": "https://www.instagram.com/reel/OTHER/", "author": "dev.tips", "status": "ready", "caption": "#code",
              "caption_read": 1, "video_tried": 1, "content": "caption", "added_at": 6}]
    phone.open_with({"db": json.dumps({"reels": reels, "inbox": []}), "videos": [{"k": K, "n": "VID_2026.mp4", "f": "Movies/Instagram", "m": 99, "s": 1}],
                     "videoRead": {K: {"screen": "@chef.ana\nCrispy rice in 10 minutes\nUse day-old rice", "seconds": 48,
                                       "speech": "today we make crispy rice with day old rice and a hot pan then add soy and garlic for the best texture",
                                       "speechModel": True, "media": 0}}}, "#/inbox")
    phone.locator("#videos").click()
    phone.get_by_text("1 new reel video", exact=False).wait_for()
    phone.locator("#start").click()
    phone.wait_for_function("() => { const d = JSON.parse(window.__rn.db || '{}'); return (d.reels || []).some((r) => r.file && r.caption_read); }")
    reels = db_of(phone)["reels"]
    assert [r["code"] for r in reels if r["code"] == "OLD1"] == []  # the caption-only one became the video one
    r = [x for x in reels if x.get("file") == K][0]
    assert r["url"] == "https://www.instagram.com/reel/OLD1/" and r["ig_code"] == "OLD1" and r["author"] == "chef.ana"
    assert r["content"] == "video+speech" and "crispy rice" in r["transcript"] and "Use day-old rice" in r["onscreen"]
    assert r["collections"] == ["Food"]
    assert ["readLocalVideo", K] in phone.rn()["calls"]
    assert any(x["code"] == "OTHER" for x in reels)


def test_the_export_label_media_is_not_a_creator(phone):
    phone.open_with({"db": json.dumps({"reels": [{"code": "A1", "url": "https://www.instagram.com/reel/A1/", "author": "Media", "status": "new", "added_at": 1},
                                                 {"code": "yt-abcdefghijk", "url": "https://youtube.com/shorts/abcdefghijk", "author": "Dev Tips", "status": "new", "added_at": 1}],
                                       "inbox": []})}, "#/")
    phone.wait_for_selector("#app > *")
    got = phone.evaluate("""() => Notes.exportFile('saved_posts.json', JSON.stringify({saved_saved_media: [
        {title: 'chef.ana', string_map_data: {'Saved on': {href: 'https://www.instagram.com/reel/AAA111/', timestamp: 1}}},
        {title: 'Media', media: [{uri: 'https://www.instagram.com/reel/BBB222/'}], label_values: [{label: 'Username', value: 'dev.tips'}]},
        {title: 'Media', string_map_data: {'Saved on': {href: 'https://www.instagram.com/reel/CCC333/'}}}]})).map((r) => [r.code, r.author])""")
    assert got == [["AAA111", "chef.ana"], ["BBB222", "dev.tips"], ["CCC333", ""]]
    phone.evaluate("() => saveDb()")
    d = {r["code"]: r["author"] for r in db_of(phone)["reels"]}
    assert d == {"A1": "", "yt-abcdefghijk": "Dev Tips"}  # "Media" was a label; a YouTube channel name with a space stays
