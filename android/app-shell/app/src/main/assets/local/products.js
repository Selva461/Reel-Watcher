/* Reel Shelf: products seen in your screenshots and reels (a shampoo bottle, a serum, a snack, a gadget).
   Screenshots: the text read on the phone is searched for a store link (Amazon, Flipkart, Nykaa...), a price next to a
   name, or a label line naming a kind of product ("Anti-Dandruff Shampoo") with its brand. Reels: the PRODUCTS line
   of the notes. Plain rules, no AI for screenshots. Stored in the library file as db.products:
   [{id, name, brand, link, price, src, from, at, online}].
   The online check (Process) looks the name up in Open Beauty Facts, Open Food Facts and Open Products Facts (free,
   no key, not AI) and calls it confirmed only when the database's brand and name match what was read. */
"use strict";

const Products = (() => {
  const STORES = /(?:https?:\/\/)?(?:www\.|m\.)?((?:amazon\.(?:in|com|co\.uk|de|ae)|amzn\.(?:to|in|eu)|a\.co|flipkart\.com|fkrt\.it|dl\.flipkart\.com|myntra\.com|myntr\.it|nykaa\.com|nykaafashion\.com|ajio\.com|meesho\.com|tatacliq\.com|purplle\.com|bigbasket\.com|blinkit\.com|zeptonow\.com|jiomart\.com|firstcry\.com|mamaearth\.in|boat-lifestyle\.com|croma\.com|reliancedigital\.in|shopee\.\w+|aliexpress\.com|etsy\.com|ebay\.\w+|walmart\.com|target\.com|bestbuy\.com|sephora\.\w+|ulta\.com|iherb\.com)(?:\/[^\s"'<>]*)?)/i;
  const KINDS = ["shampoo", "conditioner", "hair oil", "hair mask", "serum", "face wash", "facewash", "cleanser", "moisturizer", "moisturiser",
    "sunscreen", "sunblock", "lotion", "cream", "toner", "lip balm", "lipstick", "foundation", "concealer", "mascara", "eyeliner", "perfume",
    "eau de parfum", "deodorant", "body wash", "shower gel", "soap", "toothpaste", "mouthwash", "face mask", "sheet mask", "scrub", "gel",
    "trimmer", "shaver", "hair dryer", "straightener", "earbuds", "headphones", "smartwatch", "power bank", "charger", "protein", "whey",
    "creatine", "supplement", "multivitamin", "peanut butter", "granola", "oats", "coffee", "green tea", "chips", "chocolate", "sauce",
    "masala", "noodles", "cereal", "air fryer", "blender", "mixer", "kettle", "water bottle"];
  const KIND = new RegExp("\\b(" + KINDS.sort((a, b) => b.length - a.length).map((k) => k.replace(/ /g, "\\s+")).join("|") + ")s?\\b", "i");
  const PRICE = /(₹|rs\.?|inr|mrp|\$|€|£)\s?\d[\d,]*(\.\d+)?|\d[\d,]*(\.\d+)?\s?(₹|rs\.?|inr)/i;
  const NOISE = /^(add to cart|buy now|wishlist|share|ratings?|reviews?|free delivery|deliver to|in stock|out of stock|off|save|qty|quantity|size|sponsored|ad|visit store|see more|offers?)\b/i;
  const fold = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^\p{L}\p{N} ]/gu, " ").replace(/\s+/g, " ").trim();
  const words = (s) => fold(s).split(" ").filter((w) => w.length > 1);

  function link(text) {
    const m = String(text || "").match(STORES);
    return m ? "https://" + m[1].replace(/[).,;]+$/, "") : "";
  }

  /** A short line that looks like a brand: one to three words, capitalised or all caps, not a kind of product. */
  function brandLike(l) {
    const w = l.trim().split(/\s+/);
    return w.length >= 1 && w.length <= 3 && l.length <= 30 && !KIND.test(l) && !PRICE.test(l) && !NOISE.test(l) && /^\p{Lu}/u.test(l) && !/\d{3,}/.test(l);
  }

  /** Products in one screenshot's text (lines as read on the phone): [{name, brand, link, price}], at most 2. */
  function pick(text) {
    const lines = String(text || "").split(/\n+/).map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
    const url = link(lines.join(" "));
    const out = [];
    const add = (name, brand, price) => {
      name = name.replace(/^[-–•*\s]+|[|·•]+$/g, "").trim();
      if (name.length < 4 || name.length > 140 || NOISE.test(name) || out.some((p) => fold(p.name) === fold(name))) return;
      if (brand && !fold(name).includes(fold(brand))) name = `${brand} ${name}`;
      out.push({ name, brand: brand || "", link: url, price: price || "" });
    };
    // a store page: the name is the longest line above the first price
    const at = lines.findIndex((l) => PRICE.test(l));
    if ((url || at >= 0) && at !== 0) {
      const above = lines.slice(Math.max(0, (at < 0 ? lines.length : at) - 6), at < 0 ? lines.length : at).filter((l) => !NOISE.test(l) && !/https?:|www\./i.test(l) && /\p{L}{3}/u.test(l));
      const name = above.sort((a, b) => b.length - a.length)[0];
      if (name && (url || KIND.test(name) || name.split(" ").length >= 3)) add(name, "", at >= 0 ? (lines[at].match(PRICE) || [""])[0] : "");
    }
    // a label: a line naming a kind of product, with the brand on the line before (or in the line itself)
    for (let i = 0; i < lines.length && out.length < 2; i++) {
      const l = lines[i];
      if (!KIND.test(l) || l.split(" ").length > 10 || /[.!?]$/.test(l) && l.split(" ").length > 6) continue;
      if (/^(with|for|and|contains?|enriched|made|no|free|from|new|best|our|the)\b/i.test(l)) continue;  // "With Milk Protein" describes the product above
      const prev = i > 0 && brandLike(lines[i - 1]) ? lines[i - 1] : "";
      if (!prev && l.split(" ").length < 2) continue;  // "Shampoo" alone names no product
      add(l, prev, "");
    }
    return out.slice(0, 2);
  }

  function store(db, p, src, from) {
    const list = db.products || (db.products = []);
    const k = fold(p.name);
    if (!k || list.some((x) => fold(x.name) === k)) return 0;
    list.unshift({ id: "p" + Date.now().toString(36) + list.length, name: p.name.slice(0, 140), brand: (p.brand || "").slice(0, 60), link: p.link || "",
      price: p.price || "", src: src || "", from, at: Date.now() });
    return 1;
  }

  /** Adds the products of one read screenshot. Returns how many are new. */
  function addFrom(db, text, src) {
    return pick(text).reduce((n, p) => n + store(db, p, src, "screenshot"), 0);
  }

  /** Adds the products a reel's notes name (PRODUCTS line), with a store link from its caption if there is one. */
  function addFromReel(db, r) {
    const n = r.notes || {};
    const url = link(r.caption || "");
    return (n.products || []).reduce((c, name) => c + store(db, { name, link: (n.products.length === 1 && url) || "" }, r.code, "reel"), 0);
  }

  /** Products containing every word you typed, most matching first. */
  function find(db, query) {
    const list = db.products || [];
    const q = fold(query).split(" ").filter(Boolean);
    if (!q.length) return list;
    return list.filter((x) => { const t = fold([x.name, x.brand, x.online && x.online.name, x.online && x.online.brand].join(" ")); return q.every((w) => t.includes(w)); });
  }

  function unchecked(db, now = Date.now()) {
    return (db.products || []).filter((p) => !p.online || (!p.online.found && now - (p.online.at || 0) > 30 * 864e5));
  }

  /** Does the database's answer {name, brand} fit what was read? Its brand must be in what was read, and one more word. */
  function agrees(p, r) {
    const read = new Set(words(p.name + " " + p.brand));
    const brand = words(r.brand || "").filter((w) => w.length > 2);
    if (!brand.length || !brand.every((w) => read.has(w))) return false;
    return words(r.name).filter((w) => !brand.includes(w) && w.length > 2).some((w) => read.has(w));
  }

  /** Looks products up online (ask(name) -> {results: [{name, brand, url, image, quantity, db}]}), at most `max`. The
   *  first result whose brand and name fit what was read is kept; none fitting means not confirmed. */
  async function checkOnline(db, ask, { max = 30, gap = 1100, stop = () => false, nap = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
    let found = 0;
    for (const p of unchecked(db).slice(0, max)) {
      if (stop()) break;
      let r;
      try { r = JSON.parse(await ask(p.name)); } catch (e) { break; }
      r = ((r && r.results) || []).find((x) => agrees(p, x) && /^https:\/\/world\.open(beauty|food|products)facts\.org\//.test(x.url || ""));
      const ok = !!r;
      p.online = ok ? { found: true, name: String(r.name || "").slice(0, 140), brand: String(r.brand || "").slice(0, 60), url: r.url,
        image: /^https:\/\/images\.open(beauty|food|products)facts\.org\//.test(r.image || "") ? r.image : "", quantity: String(r.quantity || "").slice(0, 40),
        db: String(r.db || "").slice(0, 40), at: Date.now() } : { found: false, at: Date.now() };
      if (ok) found++;
      await nap(gap);
    }
    return found;
  }

  /** A store search for the product, opened in your browser only when you tap it. */
  function searchUrl(p) { return "https://www.google.com/search?tbm=shop&q=" + encodeURIComponent((p.online && p.online.name ? `${p.online.brand} ${p.online.name}` : p.name).trim()); }

  return { pick, link, addFrom, addFromReel, find, unchecked, agrees, checkOnline, searchUrl };
})();
