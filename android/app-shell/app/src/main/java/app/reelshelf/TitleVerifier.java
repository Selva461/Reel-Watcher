package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Checks watchlist titles against free online databases and fills in year, language, genres and poster.
 * Movies and series: TMDB (with your own free key) or Wikidata (no key). Anime: AniList and Jikan (MyAnimeList).
 * Manga: AniList and MangaDex. Matching is plain maths (TitleMatch), no AI.
 * A title is "verified" only when the match is strong and a second source agrees (or the name is an exact,
 * unique match). Close calls (remakes, an anime and its manga) become "conflict" with choices for you to pick.
 * Pure Java (no Android classes) so it is tested on a computer; the network is behind {@link Http}.
 */
final class TitleVerifier {
    static final double VERIFIED = 0.85;
    static final double REVIEW = 0.55;

    // ------------------------------------------------------------------ network

    static final class Res {
        final int code;
        final String body;
        final long retryAfterMs;

        Res(int code, String body, long retryAfterMs) {
            this.code = code;
            this.body = body == null ? "" : body;
            this.retryAfterMs = retryAfterMs;
        }
    }

    interface Http {
        /** body null for GET. */
        Res send(String url, String body, Map<String, String> headers) throws IOException;
    }

    /** The real network: plain HTTPS, no cookies, no account. */
    static final Http NET = (url, body, headers) -> {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            c.setRequestProperty("User-Agent", "ReelShelf/0.5 (personal watchlist app)");
            c.setRequestProperty("Accept", "application/json");
            for (Map.Entry<String, String> h : headers.entrySet()) c.setRequestProperty(h.getKey(), h.getValue());
            if (body != null) {
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                try (OutputStream out = c.getOutputStream()) {
                    out.write(body.getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = c.getResponseCode();
            long retry = 0;
            String ra = c.getHeaderField("Retry-After");
            if (ra != null) try {
                retry = Long.parseLong(ra.trim()) * 1000;
            } catch (NumberFormatException ignored) {
                retry = 5000;
            }
            InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            if (in != null) try (InputStream s = in) {
                byte[] buf = new byte[16384];
                int n;
                while ((n = s.read(buf)) > 0 && b.size() < 2_000_000) b.write(buf, 0, n);
            }
            return new Res(code, b.toString("UTF-8"), retry);
        } finally {
            c.disconnect();
        }
    };

    /** Sleeping, replaceable in tests so they run instantly. */
    interface Clock {
        long now();

        void sleep(long ms) throws InterruptedException;
    }

    static final Clock REAL_CLOCK = new Clock() {
        public long now() {
            return System.currentTimeMillis();
        }

        public void sleep(long ms) throws InterruptedException {
            Thread.sleep(ms);
        }
    };

    /** Polite gaps between calls to each service (their published limits, with room to spare). */
    private static final Map<String, Long> GAP = new HashMap<>();

    static {
        GAP.put("api.jikan.moe", 1200L);
        GAP.put("graphql.anilist.co", 2100L);
        GAP.put("api.mangadex.org", 300L);
        GAP.put("www.wikidata.org", 300L);
        GAP.put("api.themoviedb.org", 120L);
    }

    private final Http http;
    private final Clock clock;
    private final String tmdbKey;
    private final AtomicBoolean stop;
    private final Map<String, Long> lastCall = new HashMap<>();
    /** Services that failed for network reasons in this run (so one title's failure is not a "not found"). */
    int networkFailures;

    TitleVerifier(Http http, Clock clock, String tmdbKey, AtomicBoolean stop) {
        this.http = http;
        this.clock = clock;
        this.tmdbKey = tmdbKey == null ? "" : tmdbKey.trim();
        this.stop = stop == null ? new AtomicBoolean(false) : stop;
    }

    static final class Stopped extends IOException {
        Stopped() {
            super("stopped");
        }
    }

    private String call(String url, String body, Map<String, String> headers) throws IOException {
        String host = url.replaceFirst("^https?://", "").split("[/?:]", 2)[0];
        for (int attempt = 0; attempt < 3; attempt++) {
            if (stop.get()) throw new Stopped();
            long gap = GAP.containsKey(host) ? GAP.get(host) : 300L;
            Long last = lastCall.get(host);
            long wait = last == null ? 0 : last + gap - clock.now();
            try {
                if (wait > 0) clock.sleep(wait);
            } catch (InterruptedException e) {
                throw new Stopped();
            }
            lastCall.put(host, clock.now());
            Res r = http.send(url, body, headers == null ? new HashMap<>() : headers);
            if (r.code == 200) return r.body;
            if (r.code == 404) return "";
            if (r.code == 429 || r.code >= 500) {  // busy: wait as asked (at most 30 s) and try again
                try {
                    clock.sleep(Math.min(30000, Math.max(r.retryAfterMs, 2000L * (attempt + 1))));
                } catch (InterruptedException e) {
                    throw new Stopped();
                }
                continue;
            }
            throw new IOException(host + " answered " + r.code);
        }
        throw new IOException(host + " is busy");
    }

    private static String q(String s) {
        try {
            return URLEncoder.encode(s, "UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            return s;
        }
    }

    // ------------------------------------------------------------------ what a source says

    /** One possible title from one source. */
    static final class Match {
        String source = "";
        String id = "";
        String type = "";     // a watchlist category id (movie, series, kdrama, anime, manga, ...)
        String title = "";
        String original = "";
        List<String> names = new ArrayList<>();
        int year;
        String lang = "";
        String country = "";
        List<String> genres = new ArrayList<>();
        String poster = "";
        String overview = "";
        String url = "";
        Map<String, String> ext = new HashMap<>();
        int rank;             // position in the source's own answer (0 = its best guess)
        boolean adult;
        double score;
        double titleScore;

        String group() {
            return groupOf(type);
        }

        JSONObject facts() throws JSONException {
            JSONObject f = new JSONObject();
            f.put("title", title);
            if (!original.isEmpty() && !TitleMatch.norm(original).equals(TitleMatch.norm(title))) f.put("original_title", original);
            f.put("type", type);
            if (year > 0) f.put("year", year);
            if (!lang.isEmpty()) f.put("language", lang);
            if (!country.isEmpty()) f.put("country", country);
            if (!genres.isEmpty()) f.put("genres", new JSONArray(genres));
            if (!poster.isEmpty()) f.put("poster", poster);
            if (!overview.isEmpty()) f.put("overview", overview.length() > 1500 ? overview.substring(0, 1500) : overview);
            JSONArray aka = new JSONArray();
            for (String n : names) if (!TitleMatch.norm(n).equals(TitleMatch.norm(title)) && aka.length() < 8) aka.put(n);
            if (aka.length() > 0) f.put("aka", aka);
            JSONObject e = new JSONObject();
            for (Map.Entry<String, String> x : ext.entrySet()) if (x.getValue() != null && !x.getValue().isEmpty()) e.put(x.getKey(), x.getValue());
            f.put("ext", e);
            return f;
        }

        JSONObject choice() throws JSONException {
            JSONObject c = new JSONObject();
            c.put("source", source);
            c.put("title", title);
            c.put("type", type);
            c.put("year", year);
            c.put("language", lang);
            c.put("poster", poster);
            c.put("url", url);
            c.put("score", Math.round(score * 100) / 100.0);
            c.put("facts", facts());
            return c;
        }
    }

    static String groupOf(String type) {
        switch (type == null ? "" : type) {
            case "manga": case "manhwa": case "manhua": case "webtoon": case "comic": case "light_novel": case "book":
                return "read";
            case "game": case "other": case "":
                return "other";
            default:
                return "watch";
        }
    }

    // ------------------------------------------------------------------ TMDB (movies and series; needs your free key)

    private static final Map<Integer, String> TMDB_GENRES = new HashMap<>();

    static {
        Object[][] g = {{28, "Action"}, {12, "Adventure"}, {16, "Animation"}, {35, "Comedy"}, {80, "Crime"}, {99, "Documentary"},
                {18, "Drama"}, {10751, "Family"}, {14, "Fantasy"}, {36, "History"}, {27, "Horror"}, {10402, "Music"}, {9648, "Mystery"},
                {10749, "Romance"}, {878, "Science fiction"}, {10770, "TV movie"}, {53, "Thriller"}, {10752, "War"}, {37, "Western"},
                {10759, "Action and adventure"}, {10762, "Kids"}, {10763, "News"}, {10764, "Reality"}, {10765, "Science fiction"},
                {10766, "Soap"}, {10767, "Talk"}, {10768, "War and politics"}};
        for (Object[] x : g) TMDB_GENRES.put((Integer) x[0], (String) x[1]);
    }

    static String tmdbType(boolean tv, String lang, Set<Integer> genres) {
        boolean anim = genres.contains(16);
        if (anim && "ja".equals(lang)) return tv ? "anime" : "anime_movie";
        if (anim) return "animation";
        if (genres.contains(99)) return "documentary";
        if (tv && genres.contains(10764)) return "reality";
        if (tv && "ko".equals(lang)) return "kdrama";
        if (tv && Arrays.asList("zh", "ja", "th", "tr", "cn").contains(lang)) return "drama";
        return tv ? "series" : "movie";
    }

    List<Match> tmdb(String query) throws IOException, JSONException {
        List<Match> out = new ArrayList<>();
        if (tmdbKey.isEmpty()) return out;
        Map<String, String> h = new HashMap<>();
        String url = "https://api.themoviedb.org/3/search/multi?include_adult=false&language=en-US&page=1&query=" + q(query);
        if (tmdbKey.startsWith("eyJ")) h.put("Authorization", "Bearer " + tmdbKey);  // a "read access token"
        else url += "&api_key=" + q(tmdbKey);                                        // a short "API key"
        String body = call(url, null, h);
        if (body.isEmpty()) return out;
        JSONArray a = new JSONObject(body).optJSONArray("results");
        if (a == null) return out;
        int rank = 0;
        for (int i = 0; i < a.length() && out.size() < 6; i++) {
            JSONObject o = a.getJSONObject(i);
            String mt = o.optString("media_type");
            if (!mt.equals("movie") && !mt.equals("tv")) continue;
            boolean tv = mt.equals("tv");
            Match m = new Match();
            m.source = "tmdb";
            m.id = String.valueOf(o.optLong("id"));
            m.title = o.optString(tv ? "name" : "title");
            m.original = o.optString(tv ? "original_name" : "original_title");
            m.names.add(m.title);
            if (!m.original.isEmpty()) m.names.add(m.original);
            m.year = TitleMatch.yearIn(o.optString(tv ? "first_air_date" : "release_date"));
            m.lang = o.optString("original_language");
            JSONArray oc = o.optJSONArray("origin_country");
            if (oc != null && oc.length() > 0) m.country = oc.optString(0);
            Set<Integer> gids = new LinkedHashSet<>();
            JSONArray gi = o.optJSONArray("genre_ids");
            if (gi != null) for (int j = 0; j < gi.length(); j++) gids.add(gi.optInt(j));
            for (int gid : gids) if (TMDB_GENRES.containsKey(gid) && !m.genres.contains(TMDB_GENRES.get(gid))) m.genres.add(TMDB_GENRES.get(gid));
            m.type = tmdbType(tv, m.lang, gids);
            String pp = o.optString("poster_path");
            if (!pp.isEmpty() && !pp.equals("null")) m.poster = "https://image.tmdb.org/t/p/w342" + pp;
            m.overview = o.optString("overview");
            m.url = "https://www.themoviedb.org/" + mt + "/" + m.id;
            m.ext.put("tmdb", mt + "/" + m.id);
            m.adult = o.optBoolean("adult");
            m.rank = rank++;
            out.add(m);
        }
        return out;
    }

    // ------------------------------------------------------------------ Wikidata (movies and series without a key)

    /** Wikidata "instance of" ids that mean a title, as a watchlist category. */
    private static final Map<String, String> WD_KIND = new HashMap<>();
    /** Wikidata language ids to ISO 639-1. */
    private static final Map<String, String> WD_LANG = new HashMap<>();

    static {
        String[][] k = {{"Q11424", "movie"}, {"Q24869", "movie"}, {"Q506240", "movie"}, {"Q229390", "movie"}, {"Q93204", "documentary"},
                {"Q5398426", "series"}, {"Q1259759", "series"}, {"Q526877", "series"}, {"Q15416", "series"}, {"Q21191270", "series"},
                {"Q202866", "animation"}, {"Q581714", "animation"}, {"Q117467246", "animation"},
                {"Q63952888", "anime"}, {"Q1107", "anime"}, {"Q20650540", "anime_movie"}, {"Q220898", "anime"},
                {"Q21198342", "manga"}, {"Q8274", "manga"}, {"Q74262765", "manhwa"}, {"Q562214", "manhwa"}, {"Q754669", "manhua"},
                {"Q105543609", "series"}, {"Q7725634", "book"}, {"Q8261", "book"}, {"Q747381", "light_novel"}, {"Q7889", "game"}};
        for (String[] x : k) WD_KIND.put(x[0], x[1]);
        String[][] l = {{"Q1860", "en"}, {"Q5287", "ja"}, {"Q9176", "ko"}, {"Q7850", "zh"}, {"Q727694", "zh"}, {"Q9186", "zh"},
                {"Q1568", "hi"}, {"Q5885", "ta"}, {"Q8097", "te"}, {"Q36236", "ml"}, {"Q33673", "kn"}, {"Q9610", "bn"}, {"Q1571", "mr"},
                {"Q58635", "pa"}, {"Q5137", "gu"}, {"Q1617", "ur"}, {"Q1321", "es"}, {"Q150", "fr"}, {"Q188", "de"}, {"Q652", "it"},
                {"Q5146", "pt"}, {"Q7737", "ru"}, {"Q256", "tr"}, {"Q13955", "ar"}, {"Q9168", "fa"}, {"Q9217", "th"}, {"Q9240", "id"},
                {"Q9237", "ms"}, {"Q34057", "tl"}, {"Q9199", "vi"}, {"Q809", "pl"}, {"Q7411", "nl"}, {"Q9027", "sv"}, {"Q9035", "da"},
                {"Q9043", "no"}, {"Q1412", "fi"}, {"Q9288", "he"}, {"Q9129", "el"}, {"Q9056", "cs"}, {"Q9067", "hu"}, {"Q7913", "ro"},
                {"Q8798", "uk"}};
        for (String[] x : l) WD_LANG.put(x[0], x[1]);
    }

    private static String wdFirstId(JSONObject claims, String prop) {
        JSONArray a = claims.optJSONArray(prop);
        if (a == null) return "";
        for (int i = 0; i < a.length(); i++) {
            JSONObject v = a.optJSONObject(i).optJSONObject("mainsnak");
            if (v == null) continue;
            JSONObject dv = v.optJSONObject("datavalue");
            if (dv == null) continue;
            Object val = dv.opt("value");
            if (val instanceof JSONObject) {
                JSONObject vo = (JSONObject) val;
                if (vo.has("id")) return vo.optString("id");
                if (vo.has("time")) return vo.optString("time");
            } else if (val != null) return String.valueOf(val);
        }
        return "";
    }

    private static List<String> wdIds(JSONObject claims, String prop) {
        List<String> out = new ArrayList<>();
        JSONArray a = claims.optJSONArray(prop);
        if (a == null) return out;
        for (int i = 0; i < a.length(); i++) {
            JSONObject v = a.optJSONObject(i).optJSONObject("mainsnak");
            JSONObject dv = v == null ? null : v.optJSONObject("datavalue");
            JSONObject vo = dv == null ? null : dv.optJSONObject("value");
            if (vo != null && vo.has("id")) out.add(vo.optString("id"));
        }
        return out;
    }

    List<Match> wikidata(String query) throws IOException, JSONException {
        List<Match> out = new ArrayList<>();
        String s = call("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&type=item&language=en&uselang=en&limit=8&search="
                + q(query), null, null);
        JSONArray hits = s.isEmpty() ? null : new JSONObject(s).optJSONArray("search");
        if (hits == null || hits.length() == 0) return out;
        List<String> ids = new ArrayList<>();
        for (int i = 0; i < hits.length(); i++) ids.add(hits.getJSONObject(i).optString("id"));
        String e = call("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=labels|aliases|claims&languages=en&ids="
                + q(String.join("|", ids)), null, null);
        JSONObject ents = e.isEmpty() ? null : new JSONObject(e).optJSONObject("entities");
        if (ents == null) return out;
        int rank = 0;
        for (String id : ids) {
            JSONObject en = ents.optJSONObject(id);
            if (en == null) continue;
            JSONObject claims = en.optJSONObject("claims");
            if (claims == null) continue;
            String kind = "";
            for (String inst : wdIds(claims, "P31")) if (WD_KIND.containsKey(inst)) { kind = WD_KIND.get(inst); break; }
            if (kind.isEmpty()) continue;  // a person, a song, a city...: not a title
            Match m = new Match();
            m.source = "wikidata";
            m.id = id;
            m.type = kind;
            JSONObject lab = en.optJSONObject("labels");
            m.title = lab != null && lab.optJSONObject("en") != null ? lab.optJSONObject("en").optString("value") : query;
            m.names.add(m.title);
            JSONObject al = en.optJSONObject("aliases");
            JSONArray ae = al == null ? null : al.optJSONArray("en");
            if (ae != null) for (int i = 0; i < ae.length() && i < 6; i++) m.names.add(ae.getJSONObject(i).optString("value"));
            String date = wdFirstId(claims, "P577");
            if (date.isEmpty()) date = wdFirstId(claims, "P580");
            m.year = TitleMatch.yearIn(date);
            String lang = wdFirstId(claims, "P364");
            if (lang.isEmpty()) lang = wdFirstId(claims, "P407");
            m.lang = WD_LANG.containsKey(lang) ? WD_LANG.get(lang) : "";
            if (m.type.equals("series") && "ko".equals(m.lang)) m.type = "kdrama";
            m.ext.put("wikidata", id);
            String tm = wdFirstId(claims, "P4947");
            if (!tm.isEmpty()) m.ext.put("tmdb", "movie/" + tm);
            String tt = wdFirstId(claims, "P4983");
            if (!tt.isEmpty()) m.ext.put("tmdb", "tv/" + tt);
            String imdb = wdFirstId(claims, "P345");
            if (!imdb.isEmpty()) m.ext.put("imdb", imdb);
            String an = wdFirstId(claims, "P8729");
            if (!an.isEmpty()) m.ext.put("anilist", an);
            String mal = wdFirstId(claims, "P4086");
            if (mal.isEmpty()) mal = wdFirstId(claims, "P4087");
            if (!mal.isEmpty()) m.ext.put("mal", mal);
            m.url = "https://www.wikidata.org/wiki/" + id;
            m.rank = rank++;
            List<String> g = wdIds(claims, "P136");
            m.ext.put("_genres", String.join("|", g.subList(0, Math.min(5, g.size()))));
            out.add(m);
        }
        return out;
    }

    /** Wikidata genres are ids; their names are fetched only for the title that was picked. */
    private void wikidataGenres(Match m) {
        String ids = m.ext.remove("_genres");
        if (ids == null || ids.isEmpty() || !m.genres.isEmpty()) return;
        try {
            String e = call("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=labels&languages=en&ids=" + q(ids), null, null);
            JSONObject ents = new JSONObject(e).optJSONObject("entities");
            if (ents == null) return;
            for (String id : ids.split("\\|")) {
                JSONObject en = ents.optJSONObject(id);
                JSONObject l = en == null ? null : en.optJSONObject("labels");
                JSONObject l2 = l == null ? null : l.optJSONObject("en");
                if (l2 == null) continue;
                String name = l2.optString("value").replaceAll("(?i)\\s*(film|television series|anime|manga)$", "").trim();
                if (!name.isEmpty()) m.genres.add(name.substring(0, 1).toUpperCase(Locale.ROOT) + name.substring(1));
            }
        } catch (Exception ignored) {
            // genres are a nice extra
        }
    }

    // ------------------------------------------------------------------ AniList (anime and manga, no key)

    private static final String ANILIST_QUERY = "query($s:String){"
            + "anime:Page(perPage:5){media(search:$s,type:ANIME,sort:SEARCH_MATCH){...f}}"
            + "manga:Page(perPage:5){media(search:$s,type:MANGA,sort:SEARCH_MATCH){...f}}}"
            + "fragment f on Media{id idMal type format title{romaji english native} synonyms startDate{year} countryOfOrigin "
            + "genres coverImage{large} description(asHtml:false) siteUrl isAdult}";

    static String anilistType(String type, String format, String country) {
        if ("ANIME".equals(type)) {
            if (!"JP".equals(country) && !country.isEmpty()) return "animation";  // donghua and others
            return "MOVIE".equals(format) ? "anime_movie" : "anime";
        }
        if ("NOVEL".equals(format)) return "light_novel";
        if ("KR".equals(country)) return "manhwa";
        if ("CN".equals(country) || "TW".equals(country)) return "manhua";
        return "manga";
    }

    private static String countryLang(String c) {
        switch (c) {
            case "JP": return "ja";
            case "KR": return "ko";
            case "CN": case "TW": return "zh";
            default: return "";
        }
    }

    /** which: "anime", "manga" or "both" (one call either way). */
    List<Match> anilist(String query, String which) throws IOException, JSONException {
        List<Match> out = new ArrayList<>();
        JSONObject body = new JSONObject();
        body.put("query", ANILIST_QUERY);
        body.put("variables", new JSONObject().put("s", query));
        String s = call("https://graphql.anilist.co", body.toString(), null);
        if (s.isEmpty()) return out;
        JSONObject data = new JSONObject(s).optJSONObject("data");
        if (data == null) return out;
        for (String part : new String[]{"anime", "manga"}) {
            if (!which.equals("both") && !which.equals(part)) continue;
            JSONObject page = data.optJSONObject(part);
            JSONArray media = page == null ? null : page.optJSONArray("media");
            if (media == null) continue;
            for (int i = 0; i < media.length(); i++) {
                JSONObject o = media.getJSONObject(i);
                Match m = new Match();
                m.source = "anilist";
                m.id = String.valueOf(o.optLong("id"));
                JSONObject t = o.optJSONObject("title");
                String en = t == null ? "" : t.optString("english");
                String ro = t == null ? "" : t.optString("romaji");
                String na = t == null ? "" : t.optString("native");
                if (en.equals("null")) en = "";
                if (na.equals("null")) na = "";
                m.title = !en.isEmpty() ? en : ro;
                m.original = !na.isEmpty() ? na : ro;
                for (String n : new String[]{en, ro, na}) if (n != null && !n.isEmpty() && !n.equals("null")) m.names.add(n);
                JSONArray syn = o.optJSONArray("synonyms");
                if (syn != null) for (int j = 0; j < syn.length() && j < 6; j++) m.names.add(syn.optString(j));
                JSONObject sd = o.optJSONObject("startDate");
                m.year = sd == null ? 0 : sd.optInt("year", 0);
                m.country = o.optString("countryOfOrigin");
                if (m.country.equals("null")) m.country = "";
                m.lang = countryLang(m.country);
                m.type = anilistType(o.optString("type"), o.optString("format"), m.country);
                JSONArray g = o.optJSONArray("genres");
                if (g != null) for (int j = 0; j < g.length(); j++) m.genres.add(g.optString(j));
                JSONObject cov = o.optJSONObject("coverImage");
                if (cov != null && !cov.optString("large").isEmpty() && !cov.optString("large").equals("null")) m.poster = cov.optString("large");
                String d = o.optString("description");
                m.overview = d.equals("null") ? "" : d.replaceAll("<[^>]+>", "").trim();
                m.url = o.optString("siteUrl");
                m.adult = o.optBoolean("isAdult");
                m.ext.put("anilist", m.id);
                long mal = o.optLong("idMal", 0);
                if (mal > 0) m.ext.put("mal", String.valueOf(mal));
                m.rank = i;
                out.add(m);
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ Jikan (MyAnimeList, no key)

    List<Match> jikan(String query, String which) throws IOException, JSONException {
        List<Match> out = new ArrayList<>();
        boolean manga = which.equals("manga");
        String s = call("https://api.jikan.moe/v4/" + (manga ? "manga" : "anime") + "?sfw=true&limit=5&q=" + q(query), null, null);
        JSONArray a = s.isEmpty() ? null : new JSONObject(s).optJSONArray("data");
        if (a == null) return out;
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.getJSONObject(i);
            Match m = new Match();
            m.source = "jikan";
            m.id = String.valueOf(o.optLong("mal_id"));
            String en = o.optString("title_english");
            m.title = !en.isEmpty() && !en.equals("null") ? en : o.optString("title");
            m.original = o.optString("title_japanese").equals("null") ? "" : o.optString("title_japanese");
            m.names.add(o.optString("title"));
            if (!en.isEmpty() && !en.equals("null")) m.names.add(en);
            if (!m.original.isEmpty()) m.names.add(m.original);
            JSONArray ts = o.optJSONArray("titles");
            if (ts != null) for (int j = 0; j < ts.length() && j < 8; j++) m.names.add(ts.getJSONObject(j).optString("title"));
            m.year = o.optInt("year", 0);
            if (m.year == 0) {
                JSONObject when = o.optJSONObject(manga ? "published" : "aired");
                JSONObject prop = when == null ? null : when.optJSONObject("prop");
                JSONObject from = prop == null ? null : prop.optJSONObject("from");
                if (from != null) m.year = from.optInt("year", 0);
            }
            String fmt = o.optString("type");
            if (manga) m.type = fmt.equalsIgnoreCase("Manhwa") ? "manhwa" : fmt.equalsIgnoreCase("Manhua") ? "manhua"
                    : fmt.toLowerCase(Locale.ROOT).contains("novel") ? "light_novel" : "manga";
            else m.type = fmt.equalsIgnoreCase("Movie") ? "anime_movie" : "anime";
            m.lang = m.type.equals("manhwa") ? "ko" : m.type.equals("manhua") ? "zh" : "ja";
            JSONArray g = o.optJSONArray("genres");
            if (g != null) for (int j = 0; j < g.length(); j++) m.genres.add(g.getJSONObject(j).optString("name"));
            JSONObject img = o.optJSONObject("images");
            JSONObject jpg = img == null ? null : img.optJSONObject("jpg");
            if (jpg != null) m.poster = jpg.optString("large_image_url", jpg.optString("image_url"));
            if (m.poster.equals("null")) m.poster = "";
            m.overview = o.optString("synopsis").equals("null") ? "" : o.optString("synopsis");
            m.url = o.optString("url");
            m.ext.put("mal", m.id);
            m.rank = i;
            out.add(m);
        }
        return out;
    }

    // ------------------------------------------------------------------ MangaDex (manga, manhwa, manhua; no key)

    List<Match> mangadex(String query) throws IOException, JSONException {
        List<Match> out = new ArrayList<>();
        String s = call("https://api.mangadex.org/manga?limit=5&includes[]=cover_art&order[relevance]=desc"
                + "&contentRating[]=safe&contentRating[]=suggestive&title=" + q(query), null, null);
        JSONArray a = s.isEmpty() ? null : new JSONObject(s).optJSONArray("data");
        if (a == null) return out;
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.getJSONObject(i);
            JSONObject at = o.optJSONObject("attributes");
            if (at == null) continue;
            Match m = new Match();
            m.source = "mangadex";
            m.id = o.optString("id");
            JSONObject t = at.optJSONObject("title");
            if (t != null) {
                m.title = t.optString("en", "");
                java.util.Iterator<String> it = t.keys();
                while (m.title.isEmpty() && it.hasNext()) m.title = t.optString(it.next());
                m.names.add(m.title);
            }
            JSONArray alt = at.optJSONArray("altTitles");
            String origLang = at.optString("originalLanguage");
            if (alt != null) for (int j = 0; j < alt.length() && m.names.size() < 10; j++) {
                JSONObject x = alt.getJSONObject(j);
                java.util.Iterator<String> it = x.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    String v = x.optString(k);
                    m.names.add(v);
                    if (m.original.isEmpty() && k.equals(origLang)) m.original = v;
                }
            }
            m.year = at.optInt("year", 0);
            m.lang = origLang.startsWith("zh") ? "zh" : origLang.length() >= 2 ? origLang.substring(0, 2) : "";
            m.type = m.lang.equals("ko") ? "manhwa" : m.lang.equals("zh") ? "manhua" : "manga";
            JSONArray tags = at.optJSONArray("tags");
            if (tags != null) for (int j = 0; j < tags.length(); j++) {
                JSONObject ta = tags.getJSONObject(j).optJSONObject("attributes");
                if (ta == null || !"genre".equals(ta.optString("group"))) continue;
                JSONObject nm = ta.optJSONObject("name");
                if (nm != null && !nm.optString("en").isEmpty()) m.genres.add(nm.optString("en"));
            }
            JSONObject desc = at.optJSONObject("description");
            if (desc != null) m.overview = desc.optString("en", "");
            JSONArray rel = o.optJSONArray("relationships");
            if (rel != null) for (int j = 0; j < rel.length(); j++) {
                JSONObject r = rel.getJSONObject(j);
                JSONObject ra = r.optJSONObject("attributes");
                if ("cover_art".equals(r.optString("type")) && ra != null && !ra.optString("fileName").isEmpty())
                    m.poster = "https://uploads.mangadex.org/covers/" + m.id + "/" + ra.optString("fileName") + ".256.jpg";
            }
            JSONObject links = at.optJSONObject("links");
            if (links != null) {
                if (!links.optString("al").isEmpty()) m.ext.put("anilist", links.optString("al"));
                if (!links.optString("mal").isEmpty()) m.ext.put("mal", links.optString("mal"));
            }
            m.ext.put("mangadex", m.id);
            m.url = "https://mangadex.org/title/" + m.id;
            m.rank = i;
            out.add(m);
        }
        return out;
    }

    // ------------------------------------------------------------------ scoring

    /** What was read for one watchlist entry. */
    static final class Candidate {
        String id = "";
        long updatedAt;
        String title = "";
        List<String> aka = new ArrayList<>();
        String type = "";
        int year;
        String lang = "";

        static Candidate from(JSONObject o) {
            Candidate c = new Candidate();
            c.id = o.optString("id");
            c.updatedAt = o.optLong("updated_at", 0);
            c.title = o.optString("title");
            JSONArray a = o.optJSONArray("aka");
            if (a != null) for (int i = 0; i < a.length() && i < 6; i++) c.aka.add(a.optString(i));
            c.type = o.optString("type");
            c.year = o.optInt("year", 0);
            if (c.year == 0) c.year = TitleMatch.yearIn(c.title);
            c.lang = o.optString("language");
            return c;
        }

        List<String> queries() {
            LinkedHashSet<String> s = new LinkedHashSet<>();
            for (String t : new ArrayList<String>() {{ add(title); addAll(aka); }}) {
                String c = TitleMatch.clean(t);
                if (c.length() >= 2) s.add(c);
            }
            return new ArrayList<>(s);
        }

        /** "anime", "manga", "screen" (movies and series) or "any", from the category the reading guessed. */
        String plan() {
            switch (type) {
                case "anime": case "anime_movie": return "anime";
                case "manga": case "manhwa": case "manhua": case "webtoon": case "light_novel": return "manga";
                case "series": case "kdrama": case "drama": case "documentary": case "reality": case "animation": case "short":
                case "standup": return "screen";
                case "movie": return "screen+anime";   // "movie" is also the default when nothing was known
                default: return "any";
            }
        }
    }

    static double score(Candidate c, Match m) {
        double s = TitleMatch.bestSimilarity(c.queries(), m.names.isEmpty() ? Arrays.asList(m.title) : m.names);
        m.titleScore = s;
        if (c.year > 0 && m.year > 0) {
            int d = Math.abs(c.year - m.year);
            s += d == 0 ? 0.05 : d == 1 ? 0.02 : -Math.min(0.3, 0.06 * d);
        }
        if (!c.lang.isEmpty() && !m.lang.isEmpty()) s += c.lang.equals(m.lang) ? 0.03 : -0.05;
        String cg = groupOf(c.type);
        if (!cg.equals("other") && !m.group().equals("other") && !cg.equals(m.group())) s -= 0.2;  // a manga when a show was seen
        else if (c.type.equals(m.type)) s += 0.02;
        if (m.adult) s -= 0.1;
        s += 0.02 * Math.max(0, 5 - m.rank) / 5.0;  // the source's own ranking breaks ties
        m.score = Math.max(0, Math.min(1, s));
        return m.score;
    }

    /** Two sources describe the same title: a shared database id, or the same name, a close year and the same kind. */
    static boolean sameTitle(Match a, Match b) {
        for (String k : new String[]{"tmdb", "imdb", "anilist", "mal", "wikidata"}) {
            String x = a.ext.get(k);
            String y = b.ext.get(k);
            if (x != null && y != null && !x.isEmpty() && !y.isEmpty()) return x.equals(y);
        }
        if (!a.group().equals(b.group())) return false;
        if (a.year > 0 && b.year > 0 && Math.abs(a.year - b.year) > 1) return false;
        return TitleMatch.bestSimilarity(a.names.isEmpty() ? Arrays.asList(a.title) : a.names,
                b.names.isEmpty() ? Arrays.asList(b.title) : b.names) >= 0.9;
    }

    private List<Match> ask(String source, String query) throws IOException, JSONException {
        switch (source) {
            case "tmdb": return tmdb(query);
            case "wikidata": return wikidata(query);
            case "anilist-anime": return anilist(query, "anime");
            case "anilist-manga": return anilist(query, "manga");
            case "anilist": return anilist(query, "both");
            case "jikan-anime": return jikan(query, "anime");
            case "jikan-manga": return jikan(query, "manga");
            case "mangadex": return mangadex(query);
            default: return new ArrayList<>();
        }
    }

    private String screenSource() {
        return tmdbKey.isEmpty() ? "wikidata" : "tmdb";
    }

    /** The services to ask first, from what the reading guessed. */
    List<String> firstSources(Candidate c) {
        switch (c.plan()) {
            case "anime": return Arrays.asList("anilist-anime", "jikan-anime");
            case "manga": return Arrays.asList("anilist-manga", "mangadex");
            case "screen": return Arrays.asList(screenSource());
            case "screen+anime": return Arrays.asList(screenSource(), "anilist-anime");
            default: return Arrays.asList(screenSource(), "anilist");
        }
    }

    /** A second service that can confirm a title of this kind. */
    String confirmer(Match best) {
        switch (best.source) {
            case "tmdb": return "wikidata";
            case "wikidata":
                if (best.group().equals("read")) return "anilist-manga";
                if (best.type.startsWith("anime")) return "anilist-anime";
                return tmdbKey.isEmpty() ? "" : "tmdb";
            case "anilist": return best.group().equals("read") ? "mangadex" : "jikan-anime";
            case "jikan": return "anilist";
            case "mangadex": return "anilist-manga";
            default: return "";
        }
    }

    /**
     * Checks one entry. Returns {id, updated_at, verdict, confidence, by, facts, choices, note} or null when no
     * service could be reached (so it is tried again later rather than marked as not found).
     */
    JSONObject verify(Candidate c) throws IOException, JSONException {
        List<String> queries = c.queries();
        JSONObject r = new JSONObject();
        r.put("id", c.id);
        r.put("updated_at", c.updatedAt);
        r.put("checked_at", clock.now());
        if (queries.isEmpty()) return verdict(r, "not_found", 0, "", null, new ArrayList<>(), "No readable title");
        if (Arrays.asList("book", "comic", "game").contains(c.type))
            return verdict(r, "not_found", 0, "", null, new ArrayList<>(), "No free database is used for this category yet");
        List<Match> all = new ArrayList<>();
        Set<String> asked = new LinkedHashSet<>();
        int failed = 0;
        int tried = 0;
        for (String src : firstSources(c)) {
            for (String qy : queries.subList(0, Math.min(2, queries.size()))) {
                tried++;
                try {
                    for (Match m : ask(src, qy)) { score(c, m); all.add(m); }
                    asked.add(src);
                } catch (Stopped e) {
                    throw e;
                } catch (Exception e) {  // offline, refused or an answer we could not read
                    failed++;
                }
            }
        }
        if (tried > 0 && failed == tried) {
            networkFailures++;
            return null;
        }
        all.sort((a, b) -> Double.compare(b.score, a.score));
        Match best = all.isEmpty() ? null : all.get(0);
        if (best != null && best.score >= REVIEW) {
            String conf = confirmer(best);
            String key = conf.replace("-anime", "").replace("-manga", "");
            boolean have = false;
            for (Match m : all) if (!m.source.equals(best.source) && sameTitle(best, m)) { have = true; break; }
            if (!have && !conf.isEmpty() && !asked.contains(conf) && !asked.contains(key)) {
                String qy = best.title.isEmpty() ? queries.get(0) : best.title;
                try {
                    for (Match m : ask(conf, qy)) { score(c, m); all.add(m); }
                } catch (Stopped e) {
                    throw e;
                } catch (Exception ignored) {
                    // one confirming source down: the strict rules below still apply
                }
                all.sort((a, b) -> Double.compare(b.score, a.score));
                best = all.get(0);
            }
        }
        if (best == null || best.score < REVIEW) {
            return verdict(r, "not_found", best == null ? 0 : best.score, String.join("+", asked), null, top(all, null, 3),
                    "Nothing online matched well enough");
        }
        // the best title, with what the agreeing sources add
        List<Match> agree = new ArrayList<>();
        for (Match m : all) if (m != best && !m.source.equals(best.source) && sameTitle(best, m)) agree.add(m);
        Match rival = null;
        for (Match m : all) {
            if (m == best || agree.contains(m) || sameTitle(best, m)) continue;
            if (m.score >= best.score - 0.05 && m.score >= 0.7) { rival = m; break; }
        }
        double conf = Math.min(1, best.score + (agree.isEmpty() ? 0 : 0.08));
        Match merged = combine(best, agree);
        if (merged.source.equals("wikidata") || merged.genres.isEmpty()) wikidataGenres(merged);
        Set<String> by = new LinkedHashSet<>();
        by.add(best.source);
        for (Match m : agree) by.add(m.source);
        String verdict;
        String note;
        if (rival != null) {
            verdict = "conflict";
            note = "More than one title fits: pick the right one";
        } else if (conf >= VERIFIED && (!agree.isEmpty() || best.titleScore >= 0.97)) {
            verdict = "verified";
            note = agree.isEmpty() ? "Exact name match on " + best.source : "Confirmed by " + String.join(" and ", by);
        } else {
            verdict = "conflict";
            note = conf >= VERIFIED ? "Only one source found it: check it is right" : "Close but not certain: check it is right";
        }
        return verdict(r, verdict, conf, String.join("+", by), merged, top(all, best, 4), note);
    }

    /** The best match, with year, language, genres, poster and ids filled in from the sources that agree. */
    static Match combine(Match best, List<Match> agree) {
        Match m = new Match();
        m.source = best.source;
        m.id = best.id;
        m.type = best.type;
        m.title = best.title;
        m.original = best.original;
        m.names = new ArrayList<>(best.names);
        m.year = best.year;
        m.lang = best.lang;
        m.country = best.country;
        m.genres = new ArrayList<>(best.genres);
        m.poster = best.poster;
        m.overview = best.overview;
        m.url = best.url;
        m.ext = new HashMap<>(best.ext);
        m.score = best.score;
        m.titleScore = best.titleScore;
        for (Match a : agree) {
            if (m.year == 0) m.year = a.year;
            if (m.lang.isEmpty()) m.lang = a.lang;
            if (m.country.isEmpty()) m.country = a.country;
            if (m.poster.isEmpty()) m.poster = a.poster;
            if (m.overview.isEmpty()) m.overview = a.overview;
            if (m.original.isEmpty()) m.original = a.original;
            for (String g : a.genres) if (m.genres.size() < 8 && !m.genres.contains(g)) m.genres.add(g);
            for (Map.Entry<String, String> e : a.ext.entrySet()) if (!e.getKey().startsWith("_")) m.ext.putIfAbsent(e.getKey(), e.getValue());
            // Wikidata knows "film" or "series"; the movie databases know "anime" or "K-drama": keep the finer one
            if (m.source.equals("wikidata") && !a.type.isEmpty()) m.type = a.type;
        }
        if (!m.ext.containsKey("_genres") && best.ext.containsKey("_genres")) m.ext.put("_genres", best.ext.get("_genres"));
        return m;
    }

    private static List<Match> top(List<Match> all, Match best, int n) {
        List<Match> out = new ArrayList<>();
        if (best != null) out.add(best);
        for (Match m : all) {
            if (out.size() >= n) break;
            boolean dup = false;
            for (Match o : out) if (o == m || (o.source.equals(m.source) && o.id.equals(m.id)) || sameTitle(o, m)) { dup = true; break; }
            if (!dup && m.score >= 0.4) out.add(m);
        }
        return out;
    }

    private static JSONObject verdict(JSONObject r, String verdict, double conf, String by, Match facts, List<Match> choices, String note)
            throws JSONException {
        r.put("verdict", verdict);
        r.put("confidence", Math.round(conf * 100) / 100.0);
        r.put("by", by);
        if (facts != null) {
            facts.ext.remove("_genres");
            r.put("facts", facts.facts());
        }
        JSONArray ch = new JSONArray();
        for (Match m : choices) {
            m.ext.remove("_genres");
            ch.put(m.choice());
        }
        r.put("choices", ch);
        r.put("note", note);
        return r;
    }
}
