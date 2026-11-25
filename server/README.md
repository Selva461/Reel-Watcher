# Reel Shelf reader (Vercel)

A tiny serverless backend that reads a **public** Instagram reel and hands the phone app back only small text (the
caption and author) plus the media URLs. The phone keeps almost nothing, which is the point: Instagram no longer lets
a logged-out phone read a reel from its link, so this server does the read instead.

## What it returns

`GET /api/reel?code=<shortcode>` (or `?url=<reel url>`) →

```json
{ "ok": true, "code": "Cxxxx", "source": "media-info",
  "caption": "…", "author": "someone", "video_url": "https://…", "thumbnail": "https://…" }
```

On failure: `{ "ok": false, "error": "…", "blocked": true }` (see "If it is blocked" below).

## Deploy

1. Install the Vercel CLI: `npm i -g vercel`
2. From this `server/` folder: `vercel` (follow the prompts) then `vercel --prod`.
   - Or import the repo in the Vercel dashboard and set the **Root Directory** to `server`.
3. Your endpoint is `https://<your-project>.vercel.app/api/reel`.

## Test it (this is the make-or-break step)

Open in a browser (replace the code with any public reel's shortcode, the bit after `/reel/`):

```
https://<your-project>.vercel.app/api/reel?code=Bt0lmZ1A7uu
```

- If you get `"ok": true` with a real `caption` → **Vercel can read Instagram**, and the phone app can be wired to it.
- If you get `"blocked": true` → Instagram refused the server's IP (very common on datacenter hosts like Vercel).
  Do one of these, then retry:

### If it is blocked

- **Add a session cookie (quickest):** in a browser logged in to Instagram, copy the `Cookie` header of any
  `instagram.com` request (DevTools → Network), and set it as a Vercel **Environment Variable** named `IG_COOKIE`
  (Project → Settings → Environment Variables), then redeploy. The server will send it with each request.
  Note: this ties the reads to that account and can expire; it is also against Instagram's Terms, so use a throwaway
  account you are comfortable with, not your main one.
- **Or use a residential proxy:** sign up for a residential-proxy service and route the function's `fetch` through it
  (hook `IG_PROXY` into an undici dispatcher). More reliable, but it costs money.

## Honest caveats

- Automated reading is against Instagram's Terms of Service. This is for reading your own saved, public reels for
  personal notes, not scraping at scale.
- Datacenter IPs get blocked and endpoints change; expect to maintain this. The cookie/proxy options above are the
  usual fixes.
- Only text and media URLs leave Instagram through this server; it stores nothing.
