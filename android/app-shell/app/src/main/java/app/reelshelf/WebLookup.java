package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * "Look it up online" for the phone AI (off unless you switch it on). Only your question is sent, to two free services
 * that need no key and no account and are not AI: Wikipedia (its search API, the opening part of the best articles) and
 * DuckDuckGo's Instant Answers. Nothing from your library is sent. The answers come back as short texts with their
 * links, so every answer the AI writes from them can show where it came from. Pure Java, tested with a fake network.
 */
final class WebLookup {
    static final int MAX_TEXT = 1200;

    private final TitleVerifier.Http http;

    WebLookup(TitleVerifier.Http http) {
        this.http = http;
    }

    /** [{title, url, text, source}], best first; empty when nothing was found. Throws only when no service answered. */
    JSONArray search(String question) throws IOException {
        String q = clean(question);
        JSONArray out = new JSONArray();
        if (q.isEmpty()) return out;
        int failed = 0;
        List<JSONObject> got = new ArrayList<>();
        try {
            got.addAll(duck(q));
        } catch (Exception e) {
            failed++;
        }
        try {
            got.addAll(wikipedia(q));
        } catch (Exception e) {
            failed++;
        }
        if (failed == 2) throw new IOException("No internet, or the search services did not answer");
        List<String> seen = new ArrayList<>();
        for (JSONObject o : got) {
            String u = o.optString("url");
            if (seen.contains(u) || o.optString("text").isEmpty()) continue;
            seen.add(u);
            out.put(o);
            if (out.length() >= 5) break;
        }
        return out;
    }

    /**
     * Is this quote really said somewhere? Its first words (at most 12, as one exact phrase) go to Wikiquote's search
     * (free, no key, not AI). {found, page, url, snippet}: page is the Wikiquote page it is on (the film, show or person).
     */
    JSONObject quote(String text) throws IOException, JSONException {
        String[] w = clean(text).replaceAll("[^\\p{L}\\p{N}' ]+", " ").trim().split("\\s+");
        JSONObject out = new JSONObject().put("found", false);
        if (w.length < 3) return out;
        String phrase = String.join(" ", java.util.Arrays.copyOf(w, Math.min(12, w.length)));
        String body = get("https://en.wikiquote.org/w/api.php?action=query&format=json&list=search&srlimit=3&srprop=snippet&srsearch="
                + enc("\"" + phrase + "\""));
        JSONObject q = body.isEmpty() ? null : new JSONObject(body).optJSONObject("query");
        JSONArray hits = q == null ? null : q.optJSONArray("search");
        JSONObject top = hits == null || hits.length() == 0 ? null : hits.optJSONObject(0);
        if (top == null || top.optString("title").isEmpty()) return out;
        String page = top.optString("title");
        return out.put("found", true).put("page", page).put("url", "https://en.wikiquote.org/wiki/" + page.replace(' ', '_'))
                .put("snippet", cut(top.optString("snippet").replaceAll("<[^>]*>", "").replace("&quot;", "\"").replace("&amp;", "&")));
    }

    private static final String[][] PRODUCT_DBS = {
            {"Open Beauty Facts", "https://world.openbeautyfacts.org"},
            {"Open Food Facts", "https://world.openfoodfacts.org"},
            {"Open Products Facts", "https://world.openproductsfacts.org"}};

    /**
     * A product's name (as read from a label or a store page) to the open product databases: Open Beauty Facts, then
     * Open Food Facts, then Open Products Facts (free, no key, not AI), until one has matches.
     * {results: [{name, brand, url, image, quantity, db}]}, at most 3; the page decides which one fits what was read.
     */
    JSONObject product(String name) throws IOException, JSONException {
        String q = clean(name);
        JSONArray out = new JSONArray();
        if (q.length() >= 3) for (String[] d : PRODUCT_DBS) {
            String body = get(d[1] + "/cgi/search.pl?search_simple=1&action=process&json=1&page_size=3"
                    + "&fields=code,product_name,brands,image_front_small_url,quantity&search_terms=" + enc(q));
            JSONArray ps = body.isEmpty() ? null : new JSONObject(body).optJSONArray("products");
            if (ps != null) for (int i = 0; i < ps.length() && out.length() < 3; i++) {
                JSONObject p = ps.optJSONObject(i);
                if (p == null || p.optString("product_name").isEmpty() || !p.optString("code").matches("\\d{6,14}")) continue;
                out.put(new JSONObject().put("name", clean(p.optString("product_name"))).put("brand", clean(p.optString("brands").split(",")[0]))
                        .put("url", d[1] + "/product/" + p.optString("code")).put("image", p.optString("image_front_small_url"))
                        .put("quantity", clean(p.optString("quantity"))).put("db", d[0]));
            }
            if (out.length() > 0) break;
        }
        return new JSONObject().put("results", out);
    }

    /** One line of plain words, at most 200 characters (a question, never notes). */
    static String clean(String s) {
        String t = s == null ? "" : s.replaceAll("[\\r\\n\\t]+", " ").replaceAll("\\s+", " ").trim();
        return t.length() > 200 ? t.substring(0, 200) : t;
    }

    List<JSONObject> wikipedia(String q) throws IOException, JSONException {
        String url = "https://en.wikipedia.org/w/api.php?action=query&format=json&utf8=1&redirects=1&generator=search&gsrlimit=3&gsrsearch="
                + enc(q) + "&prop=extracts%7Cinfo&inprop=url&exintro=1&explaintext=1&exlimit=3";
        String body = get(url);
        List<JSONObject> out = new ArrayList<>();
        JSONObject query = body.isEmpty() ? null : new JSONObject(body).optJSONObject("query");
        JSONObject pages = query == null ? null : query.optJSONObject("pages");
        if (pages == null) return out;
        List<JSONObject> list = new ArrayList<>();
        for (java.util.Iterator<String> it = pages.keys(); it.hasNext(); ) list.add(pages.getJSONObject(it.next()));
        list.sort((a, b) -> Integer.compare(a.optInt("index", 99), b.optInt("index", 99)));
        for (JSONObject p : list) {
            String text = cut(p.optString("extract"));
            String link = p.optString("fullurl");
            if (!link.startsWith("https://en.wikipedia.org/")) link = "https://en.wikipedia.org/wiki/" + p.optString("title").replace(' ', '_');
            out.add(item(p.optString("title"), link, text, "Wikipedia"));
        }
        return out;
    }

    List<JSONObject> duck(String q) throws IOException, JSONException {
        String body = get("https://api.duckduckgo.com/?format=json&no_html=1&skip_disambig=1&no_redirect=1&t=reelshelf&q=" + enc(q));
        List<JSONObject> out = new ArrayList<>();
        if (body.isEmpty()) return out;
        JSONObject o = new JSONObject(body);
        String answer = o.optString("Answer");
        if (!answer.isEmpty() && !answer.startsWith("{")) out.add(item(o.optString("AnswerType", "Answer"), "https://duckduckgo.com/?q=" + enc(q), cut(answer), "DuckDuckGo"));
        String abs = o.optString("AbstractText");
        String absUrl = o.optString("AbstractURL");
        if (!abs.isEmpty() && absUrl.startsWith("https://")) out.add(item(o.optString("Heading"), absUrl, cut(abs), o.optString("AbstractSource", "DuckDuckGo")));
        String def = o.optString("Definition");
        String defUrl = o.optString("DefinitionURL");
        if (!def.isEmpty() && defUrl.startsWith("https://")) out.add(item(o.optString("Heading"), defUrl, cut(def), o.optString("DefinitionSource", "DuckDuckGo")));
        JSONArray rel = o.optJSONArray("RelatedTopics");
        if (out.isEmpty() && rel != null) for (int i = 0; i < rel.length() && out.size() < 2; i++) {
            JSONObject r = rel.optJSONObject(i);
            if (r == null || !r.optString("FirstURL").startsWith("https://")) continue;
            out.add(item(r.optString("Text").split(" - ")[0], r.optString("FirstURL"), cut(r.optString("Text")), "DuckDuckGo"));
        }
        return out;
    }

    private String get(String url) throws IOException {
        Map<String, String> h = new HashMap<>();
        TitleVerifier.Res r = http.send(url, null, h);
        if (r.code == 200) return r.body;
        if (r.code == 404) return "";
        throw new IOException("answered " + r.code);
    }

    private static JSONObject item(String title, String url, String text, String source) throws JSONException {
        return new JSONObject().put("title", clean(title)).put("url", url).put("text", text).put("source", source);
    }

    private static String cut(String s) {
        String t = s == null ? "" : s.replaceAll("\\s+", " ").trim();
        return t.length() > MAX_TEXT ? t.substring(0, MAX_TEXT) + "…" : t;
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s, "UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            return s;
        }
    }
}
