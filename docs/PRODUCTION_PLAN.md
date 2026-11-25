# Reel Shelf - Production Plan (commercial, server-backed)

Owner decision (2026-11-25): drop the old constraints (local-only, no server, no Instagram login, no paid API,
Play-Protect-only). This becomes a product sold to customers. **Target: reliable for ~50 customers on Vercel's free
(Hobby) plan. Functionality first; scale later.** Keep the existing (redesigned) phone UI; add a backend that
actually reads reels. Nothing in the old code is deleted - the on-phone reading, Meta AI and typing stay as offline
fallbacks.

## 1. The one hard problem
Instagram no longer serves reel content (caption/video) to logged-out clients. Any reliable reader must get past
Instagram's anti-bot. That needs **one** of: a managed third-party Instagram data provider, a residential proxy +
Instagram session cookie, or self-hosted account/proxy rotation. **There is no free, credential-less path** - that is
the single dependency the whole product hangs on, and it needs a credential *you* supply once.

## 2. Architecture

```
[ phone app ] --https+token--> [ Vercel API ] --> [ Instagram data provider ]
                                     |--> [ cache: Redis ]  [ DB: Postgres ]  [ LLM for notes ]
```

- **Phone app** (existing WebView app): sends a reel link + the user's token; shows caption + notes; stores almost
  nothing. "Directly connect, low space" = the server connects, the phone gets a little text.
- **Vercel serverless API** (Hobby): thin, cache-first, fast functions.
- **Instagram data provider**: the component that makes reading actually work (§3).
- **Cache** (Upstash Redis free tier) + **DB** (Neon or Supabase Postgres free tier): reel-data cache, user
  accounts, saved notes.
- **LLM** (cheap API): turns caption/transcript into structured notes server-side for consistent quality. The
  on-phone model stays as an offline fallback.

## 3. The reel-reading engine (the decision that makes it work)
**Recommended v1: a managed third-party Instagram data API.** It owns the proxy / anti-bot / login problem so you
don't, and it is the difference between "works reliably" and "blocked on a datacenter IP." Default recommendation:
**Apify's Instagram scraper** (documented, pay-per-result, free trial credits, simple API token). Any equivalent
(a RapidAPI Instagram scraper, ScrapeCreators, etc.) also works - I'll wire whichever you pick.

You do this once: create the account, get the API key, set it as a Vercel environment variable. I wire the backend
to it. (Alternative DIY path - residential proxy + rotating IG session cookies, self-managed - is cheaper at high
volume but high-maintenance; not recommended for v1.)

The Vercel reader already in `server/api/reel.js` is the skeleton: v1 just swaps its "fetch Instagram directly"
body for "call the provider," keeping the same response shape.

## 4. What we extract, in phases
- **v1 (cheap, works now):** caption + author + thumbnail + video URL -> notes generated from the caption. Most
  reels have an informative caption; this delivers real value immediately with near-zero cost.
- **Phase 2 (richer):** spoken words via a transcription API (Whisper / Deepgram / AssemblyAI) on the video URL, and
  on-screen text via OCR. Heavier and costs more per reel, so it runs async (queued), never inline.

## 5. Backend (Vercel) design
Endpoints (all thin, cache-first):
- `POST /api/reel {url}` -> `{caption, author, video_url, thumbnail}`. Cache hit returns instantly; on miss, call the
  provider, normalize, cache, return.
- `POST /api/notes {reel}` -> structured notes from the LLM (topic, points, takeaway, tags).
- `auth`: email magic-link or device token; per-user notes in Postgres.

Reliability (why ~50 users won't crash Hobby):
- Functions are a thin proxy + cache lookup - milliseconds of compute, far under the Hobby per-request limit.
- Redis cache (key = shortcode, TTL ~7 days) means repeat reads never touch the provider.
- Heavy work (transcription) is queued/async, never in the request path.
- Provider calls have timeout + retry + backoff and a bounded concurrency; a failure returns a clean "couldn't read
  this one," never a crash.
- 50 users x a few reels/day is tiny traffic; the free tiers absorb it with headroom.

## 6. Phone app integration
- Keep the redesigned UI. Add a **backend base URL + user token** in Settings.
- A saved/shared reel link -> `POST /api/reel` -> show caption -> `POST /api/notes` -> show notes. No download,
  minimal storage.
- Keep on-phone AI, Meta AI and typing as offline fallbacks (nothing deleted).

## 7. Commercial layer (minimal now, room to grow)
- **Accounts:** email magic-link (Supabase Auth free, or similar). Per-user notes + a simple quota column.
- **Billing:** deferred (you said scale doesn't matter yet), but the data model carries a `plan`/`quota` field so it
  can be switched on later with Stripe.
- **Admin:** a minimal usage view.

## 8. Cost at 50 users (~1,500 reels/month) - estimate, confirm current prices
- Provider: pay-per-result, roughly **$3-15 / month** at this volume.
- Vercel Hobby, Upstash Redis free, Neon/Supabase free: **$0**.
- LLM notes: a small fast model, ~**$1-5 / month**.
- Transcription (phase 2, optional): ~$0.006/min.
- **v1 total: roughly $5-20 / month.**

## 9. Legal / risk - read this before selling
- Automated Instagram access violates Instagram's Terms. At small scale through a provider the operational risk sits
  with the provider, but as a **business you carry**: possible Instagram enforcement, **app-store rejection** (Apple
  and Google scrutinize Instagram scraping), and cease-and-desist exposure if it grows. Mitigations: keep Instagram
  login out of the app; use a provider that assumes the ToS risk; ship a Terms + Privacy Policy to your customers;
  position it as "notes for reels you bring it," not a bulk scraper. This is a business risk to accept knowingly, not
  a technical blocker.
- Privacy: you will store customers' reel links + notes -> you need a privacy policy, data minimization, and
  deletion. If you take payment, add the usual commerce/consumer obligations.

## 10. Build order
- **Phase 0 (immediate):** pick the provider; swap `server/api/reel.js` to call it; confirm real captions come back
  from a live Vercel deploy. This proves "it actually reads."
- **Phase 1:** `/api/notes` (LLM) + phone app calls the backend + minimal accounts -> end-to-end "bring a reel, get
  notes," no download. This is "it works."
- **Phase 2:** transcription + OCR for richer notes; polish.
- **Phase 3:** billing, hardening, scale.

## 11. What I need from you to start Phase 0
1. **Reel-data path:** confirm a managed provider (recommended) vs DIY cookie+proxy. If a provider, create the
   account and give me the API key (I'll tell you exactly which env var).
2. **Server-side LLM for notes - OK?** (else notes stay on-phone only.) If OK, an API key for the LLM too.
3. **Acknowledge the legal/ToS risk in §9.**

Give me #1 (the key) and I'll wire the reader and prove it reads a real reel the same day.

## 12. Scale: 10,000 reels/day and a 10,000-reel backfill
The design above still holds, but at this volume three things change and one new piece is required.

**What changes**
- The limiter is no longer Vercel - it's **cost** and **Instagram's rate limits** (through the provider). Vercel just
  paces the work.
- You outgrow Hobby for *sustained* 10k/day -> move to Pro ($20/mo), or keep each function tiny and let the queue
  pace them (below). A single-user one-time backfill can stay on Hobby; sustained 10k/day across customers -> Pro.
- Full reads (speech + OCR) get expensive fast; **caption-first stays cheap**. Make full reads an opt-in.

**New required piece: a durable job queue + background workers**
A 10,000-reel backfill can't run in one request (timeouts). Instead:
- Enqueue one job per reel (Upstash QStash, or Inngest / Trigger.dev - serverless queues built for exactly this:
  retries, rate-limit control, free tiers).
- The queue delivers jobs one-by-one, paced to the provider's rate limit, to a short Vercel function:
  read reel -> cache -> notes -> store -> bump progress.
- The phone shows "1,240 of 10,000 read"; the job survives restarts; failures retry with backoff.
This keeps everything serverless and makes 10k gracefully slow instead of crashing.

**Global cache / dedup (the big cost saver)**
Cache reel data by shortcode **platform-wide**, not per user. A popular reel read once serves every customer; any
overlap in your own 10k is free.

**Your 10,000-reel backfill flow**
1. Import your saved list from Instagram's own data export (the list of shortcodes is free - no scraping).
2. Enqueue them; the backend drips through in the background, rate-limited and budget-capped.
3. Watch progress; notes fill in over hours/days, bounded by provider rate + your budget cap - not by us.

**Honest cost (confirm live prices)**
- One-time 10,000-reel backfill, caption-only: provider ~$5-20 + LLM notes ~$10-100 -> roughly **$30-100 one-time**.
- Same backfill with full speech + OCR: add transcription (~$30) + OCR + video bandwidth -> roughly **$100-300+**.
- Sustained 10,000/day (300k/mo), caption-only: order **$500-1,500/month**; full reads: several thousand/month.
- Takeaway: a per-user one-time backfill is affordable; sustained high volume is a real monthly cost your pricing
  must cover. Ship a per-user budget cap and a caption-only vs full switch.

**Instagram risk scales too**
More volume = more block/ban pressure. That is exactly why you use a provider that rotates proxies/accounts - it
absorbs that. A budget cap + pacing also protect you from runaway cost or a hard block.

**Design implication**
Build the **queue + global cache from day one** (not a rewrite later). v1 = caption-first through the queue; full
reads are a paid opt-in. That single decision lets the same system serve 1 reel or 10,000 without changing shape.
