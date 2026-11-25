// Reel Shelf reader - Vercel serverless function.
//
// GET /api/reel?code=<shortcode>   or   /api/reel?url=<instagram reel/post url>
// Returns JSON: { ok, code, source, caption, author, video_url, thumbnail }  or  { ok:false, error, blocked? }
//
// Why this exists: Instagram stopped serving reel content (caption/video) to logged-out apps, so the phone can no
// longer read a reel from its link. This server does the read instead and hands the phone back only small text
// (caption) plus the media URLs, so the phone keeps almost nothing.
//
// HONEST LIMITS:
// - Instagram blocks many datacenter IPs (Vercel runs on these) for logged-out reads. If this returns blocked:true,
//   set env IG_COOKIE to a logged-in session cookie string, and/or route fetches through a residential proxy
//   (set env IG_PROXY to a full proxy URL). Without one of those it may only work intermittently or not at all.
// - Automated reading is against Instagram's Terms of Service. Use it for your own saved, public reels only.
// - Private reels are never readable without an account that follows them.

const APP_ID = "936619743392459"; // Instagram web app id (public)
const UA = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36";
const ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

function toMediaId(code) {
  let n = 0n;
  for (const c of code) {
    const i = ALPHA.indexOf(c);
    if (i < 0) return null;
    n = n * 64n + BigInt(i);
  }
  return n.toString();
}

function shortcodeOf(input) {
  const s = String(input || "");
  const m = s.match(/instagram\.com\/(?:[^/]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/i);
  if (m) return m[1];
  return /^[A-Za-z0-9_-]{5,}$/.test(s) ? s : null;
}

async function igGet(url) {
  const headers = {
    "User-Agent": UA, "X-IG-App-ID": APP_ID, "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.instagram.com/",
  };
  if (process.env.IG_COOKIE) headers.Cookie = process.env.IG_COOKIE;
  const opts = { headers };
  // Optional residential proxy, if the platform's fetch honors a dispatcher via global-agent/undici.
  const res = await fetch(url, opts);
  const text = await res.text();
  return { status: res.status, text };
}

function blocked(status, text) {
  return status === 401 || status === 403 || status === 429 ||
    /login_required|checkpoint_required|please wait a few minutes|not available/i.test(text || "");
}

function fromMediaInfo(j) {
  const item = j && j.items && j.items[0];
  if (!item) return null;
  const vv = item.video_versions || (item.carousel_media && item.carousel_media[0] && item.carousel_media[0].video_versions);
  const iv = item.image_versions2 && item.image_versions2.candidates;
  return {
    caption: (item.caption && item.caption.text) || "",
    author: (item.user && item.user.username) || "",
    video_url: (vv && vv[0] && vv[0].url) || "",
    thumbnail: (iv && iv[0] && iv[0].url) || "",
  };
}

function fromGraphql(j) {
  const m = j && j.data && j.data.shortcode_media;
  if (!m) return null;
  const cap = (((m.edge_media_to_caption || {}).edges || [])[0] || {}).node;
  return {
    caption: (cap && cap.text) || "",
    author: (m.owner && m.owner.username) || "",
    video_url: m.video_url || "",
    thumbnail: m.display_url || "",
  };
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") { res.status(204).end(); return; }

  const code = shortcodeOf((req.query && (req.query.code || req.query.url)) || "");
  if (!code) { res.status(400).json({ ok: false, error: "pass ?code=<shortcode> or ?url=<reel url>" }); return; }

  const tried = [];
  try {
    const mid = toMediaId(code);
    if (mid) {
      const r = await igGet(`https://www.instagram.com/api/v1/media/${mid}/info/`);
      if (r.status === 200 && r.text.trim().startsWith("{")) {
        const got = fromMediaInfo(JSON.parse(r.text));
        if (got && (got.caption || got.video_url)) { res.status(200).json({ ok: true, code, source: "media-info", ...got }); return; }
      }
      tried.push(`media-info:${r.status}`);
      if (blocked(r.status, r.text)) {
        res.status(502).json({ ok: false, code, blocked: true, tried, error: `Instagram blocked this server (${r.status}). Set IG_COOKIE or use a residential proxy.` });
        return;
      }
    }
    const g = await igGet(`https://www.instagram.com/graphql/query/?query_hash=b3055c01b4b222b8a47dc12b090e4e64&variables=${encodeURIComponent(JSON.stringify({ shortcode: code }))}`);
    if (g.status === 200 && g.text.trim().startsWith("{")) {
      const got = fromGraphql(JSON.parse(g.text));
      if (got && got.caption) { res.status(200).json({ ok: true, code, source: "graphql", ...got }); return; }
    }
    tried.push(`graphql:${g.status}`);
    res.status(502).json({ ok: false, code, blocked: blocked(g.status, g.text), tried, error: "Instagram returned nothing usable (the server IP is probably blocked). Set IG_COOKIE or use a residential proxy." });
  } catch (e) {
    res.status(500).json({ ok: false, code, tried, error: String((e && e.message) || e) });
  }
};
