package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/** The online check with the network faked: answers shaped like the real services' answers. No real network. */
public class TitleVerifierTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    /** Answers by a piece of the address (first match wins); everything else is "not found". */
    static final class FakeNet implements TitleVerifier.Http {
        final Map<String, String> answers = new LinkedHashMap<>();
        final List<String> calls = new ArrayList<>();
        final List<String> bodies = new ArrayList<>();
        int busyFirst;
        boolean offline;

        FakeNet on(String part, String json) {
            answers.put(part, json);
            return this;
        }

        @Override
        public TitleVerifier.Res send(String url, String body, Map<String, String> headers) throws IOException {
            calls.add(url);
            bodies.add(body == null ? "" : body);
            if (offline) throw new IOException("no network");
            if (busyFirst > 0) {
                busyFirst--;
                return new TitleVerifier.Res(429, "", 1000);
            }
            String key = url + " " + (body == null ? "" : body);
            for (Map.Entry<String, String> e : answers.entrySet()) if (key.contains(e.getKey())) return new TitleVerifier.Res(200, e.getValue(), 0);
            if (url.contains("graphql.anilist.co")) return new TitleVerifier.Res(200, "{\"data\":{\"anime\":{\"media\":[]},\"manga\":{\"media\":[]}}}", 0);
            if (url.contains("wbsearchentities")) return new TitleVerifier.Res(200, "{\"search\":[]}", 0);
            return new TitleVerifier.Res(200, "{\"results\":[],\"data\":[]}", 0);
        }

        int count(String part) {
            int n = 0;
            for (String c : calls) if (c.contains(part)) n++;
            return n;
        }
    }

    static final class FakeClock implements TitleVerifier.Clock {
        long t = 1_800_000_000_000L;
        long slept;

        public long now() {
            return t;
        }

        public void sleep(long ms) {
            t += ms;
            slept += ms;
        }
    }

    static TitleVerifier.Candidate cand(String title, String type, int year) {
        TitleVerifier.Candidate c = new TitleVerifier.Candidate();
        c.id = "m-" + title.toLowerCase().replaceAll("[^a-z0-9]+", "-");
        c.title = title;
        c.type = type;
        c.year = year;
        return c;
    }

    static String tmdbMovie(long id, String title, String date, String lang, String poster, int... genres) throws Exception {
        JSONObject o = new JSONObject().put("media_type", "movie").put("id", id).put("title", title).put("original_title", title)
                .put("release_date", date).put("original_language", lang).put("poster_path", poster).put("overview", "About " + title)
                .put("genre_ids", new JSONArray(genres)).put("adult", false);
        return o.toString();
    }

    static String tmdb(String... results) {
        return "{\"page\":1,\"results\":[" + String.join(",", results) + "]}";
    }

    static String wdSearch(String... ids) throws Exception {
        JSONArray a = new JSONArray();
        for (String id : ids) a.put(new JSONObject().put("id", id));
        return new JSONObject().put("search", a).toString();
    }

    static JSONObject claim(String prop, Object value) throws Exception {
        return new JSONObject().put(prop, new JSONArray().put(new JSONObject().put("mainsnak",
                new JSONObject().put("datavalue", new JSONObject().put("value", value)))));
    }

    static JSONObject wdEntity(String label, String instance, String date, String lang, String tmdbMovieId) throws Exception {
        JSONObject claims = new JSONObject();
        claims.put("P31", claim("P31", new JSONObject().put("id", instance)).getJSONArray("P31"));
        claims.put("P577", claim("P577", new JSONObject().put("time", "+" + date + "-01-01T00:00:00Z")).getJSONArray("P577"));
        if (lang != null) claims.put("P364", claim("P364", new JSONObject().put("id", lang)).getJSONArray("P364"));
        if (tmdbMovieId != null) claims.put("P4947", claim("P4947", tmdbMovieId).getJSONArray("P4947"));
        return new JSONObject().put("labels", new JSONObject().put("en", new JSONObject().put("value", label))).put("claims", claims);
    }

    static String anilistMedia(long id, long mal, String type, String format, String en, String romaji, int year, String country,
                               String... genres) throws Exception {
        return new JSONObject().put("id", id).put("idMal", mal).put("type", type).put("format", format)
                .put("title", new JSONObject().put("english", en).put("romaji", romaji).put("native", "native " + romaji))
                .put("synonyms", new JSONArray()).put("startDate", new JSONObject().put("year", year)).put("countryOfOrigin", country)
                .put("genres", new JSONArray(genres)).put("coverImage", new JSONObject().put("large", "https://s4.anilist.co/c/" + id + ".jpg"))
                .put("description", "<b>Story</b> of " + romaji).put("siteUrl", "https://anilist.co/x/" + id).put("isAdult", false).toString();
    }

    static String anilist(String anime, String manga) {
        return "{\"data\":{\"anime\":{\"media\":[" + anime + "]},\"manga\":{\"media\":[" + manga + "]}}}";
    }

    // ------------------------------------------------------------------ matching maths

    @Test
    public void cleansWhatWasReadOffAScreenshot() {
        assertEquals("the dark knight", TitleMatch.clean("#TheDarkKnight (2008) Official Trailer"));
        assertEquals("rocky 2", TitleMatch.clean("Rocky II"));
        assertEquals("amelie", TitleMatch.clean("Amélie"));
        assertEquals("fast and furious", TitleMatch.clean("Fast & Furious full movie HD"));
        assertEquals(2008, TitleMatch.yearIn("The Dark Knight (2008)"));
        assertEquals(0, TitleMatch.yearIn("Blade Runner 20499"));
    }

    @Test
    public void similarityIsHighForSmallReadingMistakesAndLowForOtherTitles() {
        assertTrue(TitleMatch.similarity("Interstellar", "Interstellar") == 1);
        assertTrue(TitleMatch.similarity("Intersteller", "Interstellar") > 0.85);       // one wrong letter (OCR)
        assertTrue(TitleMatch.similarity("Knight the Dark", "The Dark Knight") > 0.9);  // words out of order
        assertTrue(TitleMatch.similarity("Attack on Titan", "Attack on Titan Final Season") > 0.7);
        assertTrue(TitleMatch.similarity("Attack on Titan", "Attack on Titan Final Season") < 0.97);
        assertTrue(TitleMatch.similarity("Up", "Upgrade") <= 0.5);                     // short names need to be exact
        assertTrue(TitleMatch.similarity("Parasite", "Paradise") < 0.85);
        assertTrue(TitleMatch.similarity("Inception", "The Godfather") < 0.4);
    }

    // ------------------------------------------------------------------ movies

    @Test
    public void movieFoundOnTmdbAndConfirmedByWikidataIsVerifiedWithLanguageGenresAndPoster() throws Exception {
        FakeNet net = new FakeNet()
                .on("themoviedb.org/3/search/multi", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/inc.jpg", 28, 878),
                        tmdbMovie(64956, "Inception: The Cobol Job", "2010-12-07", "en", "/cobol.jpg", 16)))
                .on("wbsearchentities", wdSearch("Q25188"))
                .on("wbgetentities", new JSONObject().put("entities", new JSONObject().put("Q25188",
                        wdEntity("Inception", "Q11424", "2010", "Q1860", "27205"))).toString());
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "abc123", null);
        JSONObject r = v.verify(cand("Inceptoin", "movie", 0));  // read with a typo
        assertEquals("verified", r.getString("verdict"));
        JSONObject f = r.getJSONObject("facts");
        assertEquals("Inception", f.getString("title"));
        assertEquals(2010, f.getInt("year"));
        assertEquals("en", f.getString("language"));
        assertEquals("movie", f.getString("type"));
        assertEquals("https://image.tmdb.org/t/p/w342/inc.jpg", f.getString("poster"));
        assertTrue(f.getJSONArray("genres").toString().contains("Science fiction"));
        assertEquals("movie/27205", f.getJSONObject("ext").getString("tmdb"));
        assertEquals("Q25188", f.getJSONObject("ext").getString("wikidata"));
        assertTrue(r.getString("by").contains("tmdb") && r.getString("by").contains("wikidata"));
        assertTrue(r.getDouble("confidence") >= 0.85);
        // the key goes to TMDB only, never to another service
        for (String c : net.calls) if (!c.contains("themoviedb.org")) assertFalse(c.contains("abc123"));
    }

    @Test
    public void aRemakeWithoutAYearIsAskedNotGuessed() throws Exception {
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(438631, "Dune", "2021-09-15", "en", "/d21.jpg", 878),
                tmdbMovie(841, "Dune", "1984-12-14", "en", "/d84.jpg", 878)));
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("DUNE", "movie", 0));
        assertEquals("conflict", r.getString("verdict"));
        JSONArray ch = r.getJSONArray("choices");
        assertTrue(ch.length() >= 2);
        assertTrue(ch.toString().contains("1984") && ch.toString().contains("2021"));

        // with the year seen on the screenshot it is clear
        FakeNet net2 = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(438631, "Dune", "2021-09-15", "en", "/d21.jpg", 878),
                tmdbMovie(841, "Dune", "1984-12-14", "en", "/d84.jpg", 878)));
        JSONObject r2 = new TitleVerifier(net2, new FakeClock(), "k", null).verify(cand("Dune", "movie", 1984));
        assertEquals("verified", r2.getString("verdict"));
        assertEquals(1984, r2.getJSONObject("facts").getInt("year"));
    }

    @Test
    public void withoutATmdbKeyMoviesAreCheckedOnWikidata() throws Exception {
        FakeNet net = new FakeNet().on("wbsearchentities", wdSearch("Q1", "Q2"))
                .on("wbgetentities&format=json&props=labels|aliases|claims", new JSONObject().put("entities", new JSONObject()
                        .put("Q1", wdEntity("Vikram", "Q11424", "2022", "Q5885", null))
                        .put("Q2", new JSONObject().put("labels", new JSONObject()).put("claims", claim("P31", new JSONObject().put("id", "Q5"))))).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "", null).verify(cand("Vikram", "movie", 2022));
        assertEquals(0, net.count("themoviedb"));
        assertEquals("verified", r.getString("verdict"));  // exact name, right year, nothing else fits
        assertEquals("ta", r.getJSONObject("facts").getString("language"));
    }

    // ------------------------------------------------------------------ anime and manga

    @Test
    public void animeIsConfirmedByAnilistAndMyAnimeList() throws Exception {
        FakeNet net = new FakeNet()
                .on("graphql.anilist.co", anilist(anilistMedia(16498, 16498, "ANIME", "TV", "Attack on Titan", "Shingeki no Kyojin", 2013, "JP", "Action", "Drama"), ""))
                .on("api.jikan.moe/v4/anime", "{\"data\":[{\"mal_id\":16498,\"title\":\"Shingeki no Kyojin\",\"title_english\":\"Attack on Titan\","
                        + "\"type\":\"TV\",\"year\":2013,\"genres\":[{\"name\":\"Action\"}],\"images\":{\"jpg\":{\"large_image_url\":\"https://cdn.myanimelist.net/x.jpg\"}},"
                        + "\"url\":\"https://myanimelist.net/anime/16498\"}]}");
        JSONObject r = new TitleVerifier(net, new FakeClock(), "", null).verify(cand("shingeki no kyojin", "anime", 0));
        assertEquals("verified", r.getString("verdict"));
        JSONObject f = r.getJSONObject("facts");
        assertEquals("Attack on Titan", f.getString("title"));
        assertEquals("anime", f.getString("type"));
        assertEquals("ja", f.getString("language"));
        assertEquals("16498", f.getJSONObject("ext").getString("mal"));
        assertTrue(f.getString("overview").startsWith("Story of"));  // HTML removed
    }

    @Test
    public void manhwaIsFoundOnAnilistAndMangadex() throws Exception {
        FakeNet net = new FakeNet()
                .on("graphql.anilist.co", anilist("", anilistMedia(105398, 121496, "MANGA", "MANGA", "Solo Leveling", "Na Honjaman Level Up", 2018, "KR", "Action")))
                .on("api.mangadex.org", "{\"data\":[{\"id\":\"32d76d19\",\"attributes\":{\"title\":{\"en\":\"Solo Leveling\"},\"altTitles\":[{\"ko\":\"나 혼자만 레벨업\"}],"
                        + "\"year\":2018,\"originalLanguage\":\"ko\",\"links\":{\"al\":\"105398\"},\"tags\":[{\"attributes\":{\"group\":\"genre\",\"name\":{\"en\":\"Action\"}}}]},"
                        + "\"relationships\":[{\"type\":\"cover_art\",\"attributes\":{\"fileName\":\"c.jpg\"}}]}]}");
        JSONObject r = new TitleVerifier(net, new FakeClock(), "", null).verify(cand("Solo Leveling", "manhwa", 0));
        assertEquals("verified", r.getString("verdict"));
        assertEquals("manhwa", r.getJSONObject("facts").getString("type"));
        assertEquals("ko", r.getJSONObject("facts").getString("language"));
        assertTrue(r.getJSONObject("facts").getJSONObject("ext").has("mangadex"));
    }

    @Test
    public void anAnimeAndItsMangaAreNotMixedUpWhenAShowWasSeen() throws Exception {
        FakeNet net = new FakeNet().on("graphql.anilist.co", anilist(
                anilistMedia(1, 33, "ANIME", "TV", "Berserk", "Kenpuu Denki Berserk", 1997, "JP", "Action"),
                anilistMedia(2, 2, "MANGA", "MANGA", "Berserk", "Berserk", 1989, "JP", "Action")));
        JSONObject r = new TitleVerifier(net, new FakeClock(), "", null).verify(cand("Berserk", "anime", 0));
        assertEquals("anime", r.getJSONObject("facts").getString("type"));
    }

    // ------------------------------------------------------------------ the hard cases

    @Test
    public void rubbishIsNotFoundAndNoNetworkIsNotCountedAsNotFound() throws Exception {
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(1, "The Godfather", "1972-03-14", "en", "/g.jpg", 18)));
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("xq zzv", "movie", 0));
        assertEquals("not_found", r.getString("verdict"));

        FakeNet off = new FakeNet();
        off.offline = true;
        TitleVerifier v = new TitleVerifier(off, new FakeClock(), "k", null);
        assertNull(v.verify(cand("Inception", "movie", 0)));
        assertEquals(1, v.networkFailures);
    }

    @Test
    public void aBusyServiceIsWaitedForPolitely() throws Exception {
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28)));
        net.busyFirst = 1;
        FakeClock clock = new FakeClock();
        JSONObject r = new TitleVerifier(net, clock, "k", null).verify(cand("Inception", "movie", 2010));
        assertEquals("verified", r.getString("verdict"));
        assertTrue(clock.slept >= 1000);
    }

    // ------------------------------------------------------------------ the job: cache, results file, nightly rules

    static void writeDb(File dir, JSONArray media) throws Exception {
        VerifyJob.writeJson(new File(dir, "reels.json"), new JSONObject().put("reels", new JSONArray()).put("media", media));
    }

    static JSONObject entry(String id, String title, String verified, long updated) throws Exception {
        return new JSONObject().put("id", id).put("title", title).put("type", "movie").put("verified", verified).put("updated_at", updated);
    }

    @Test
    public void theJobLooksEachTitleUpOnceAndLeavesTheLibraryFileAlone() throws Exception {
        File dir = tmp.newFolder();
        long now = System.currentTimeMillis();
        JSONArray media = new JSONArray()
                .put(entry("m-inception", "Inception", "unverified", now))
                .put(entry("m-inception-2", "inception", "unverified", now - 10))   // the same title from another screenshot
                .put(entry("m-done", "Heat", "verified", now))
                .put(entry("m-no", "Zzqx", "unverified", now - 50).put("checked_at", now - 20));  // looked up lately, nothing found
        writeDb(dir, media);
        String before = new String(java.nio.file.Files.readAllBytes(new File(dir, "reels.json").toPath()), "UTF-8");
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28)));
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "k", null);
        List<int[]> prog = new ArrayList<>();
        JSONObject sum = new VerifyJob(dir, v, new AtomicBoolean()).run(0, 0, (d, t, title) -> prog.add(new int[]{d, t}));
        assertEquals(2, sum.getInt("checked"));
        assertEquals(1, net.count("search/multi"));  // the second sighting came from the cache
        assertEquals(before, new String(java.nio.file.Files.readAllBytes(new File(dir, "reels.json").toPath()), "UTF-8"));
        assertFalse(prog.isEmpty());

        JSONObject taken = new JSONObject(VerifyJob.take(dir));
        assertEquals("verified", taken.getJSONObject("m-inception").getString("verdict"));
        assertTrue(taken.getJSONObject("m-inception-2").getBoolean("cached"));
        assertEquals("{}", VerifyJob.take(dir));  // taken once

        // a run after the page applied nothing new does nothing
        JSONObject again = new VerifyJob(dir, v, new AtomicBoolean()).run(0, 0, null);
        assertEquals(2, again.getInt("checked"));  // still unverified in reels.json (page not opened): answered from the cache
        assertEquals(1, net.count("search/multi"));
    }

    @Test
    public void theJobStopsWhenOfflineOrAskedTo() throws Exception {
        File dir = tmp.newFolder();
        JSONArray media = new JSONArray();
        for (int i = 0; i < 6; i++) media.put(entry("m-" + i, "Title number " + i, "unverified", i));
        writeDb(dir, media);
        FakeNet off = new FakeNet();
        off.offline = true;
        JSONObject sum = new VerifyJob(dir, new TitleVerifier(off, new FakeClock(), "k", null), new AtomicBoolean()).run(0, 0, null);
        assertTrue(sum.getBoolean("offline"));
        assertEquals(0, sum.getInt("checked"));
        assertEquals(6, sum.getInt("left"));

        AtomicBoolean stop = new AtomicBoolean(true);
        JSONObject s2 = new VerifyJob(dir, new TitleVerifier(new FakeNet(), new FakeClock(), "k", stop), stop).run(0, 0, null);
        assertTrue(s2.getBoolean("stopped"));
        assertNotNull(VerifyJob.take(dir));
    }

    @Test
    public void lengthsComeFromEachSource() throws Exception {
        assertEquals(90, TitleVerifier.jikanMinutes("1 hr 30 min"));
        assertEquals(24, TitleVerifier.jikanMinutes("24 min per ep"));
        assertEquals(0, TitleVerifier.jikanMinutes("Unknown"));
        JSONObject claims = new JSONObject().put("P2047", new JSONArray().put(new JSONObject().put("mainsnak", new JSONObject()
                .put("datavalue", new JSONObject().put("value", new JSONObject().put("amount", "+88").put("unit", "http://www.wikidata.org/entity/Q7727"))))));
        assertEquals(88, TitleVerifier.wdMinutes(claims));

        FakeNet net = new FakeNet().on("3/movie/27205?", "{\"runtime\":148}").on("3/tv/1399?", "{\"episode_run_time\":[],\"last_episode_to_air\":{\"runtime\":68},\"number_of_episodes\":73}")
                .on("Media(id:", "{\"data\":{\"Media\":{\"duration\":24,\"episodes\":12}}}");
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "k", null);
        Map<String, String> ext = new java.util.HashMap<>();
        ext.put("tmdb", "movie/27205");
        assertEquals(148, v.details(ext)[0]);
        ext.put("tmdb", "tv/1399");
        int[] got = v.details(ext);
        assertEquals(68, got[0]);
        assertEquals(73, got[1]);
        Map<String, String> an = new java.util.HashMap<>();
        an.put("anilist", "21");
        assertEquals(24, v.details(an)[0]);
        Map<String, String> bad = new java.util.HashMap<>();
        bad.put("tmdb", "movie/1?x=");  // not an id: nothing is asked
        int before = net.calls.size();
        assertEquals(0, v.details(bad)[0]);
        assertEquals(before, net.calls.size());
    }

    @Test
    public void aVerifiedMovieGetsItsLength() throws Exception {
        FakeNet net = new FakeNet().on("3/movie/27205?", "{\"runtime\":148}")
                .on("search/multi", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28)));
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "k", null);
        TitleVerifier.Candidate c = TitleVerifier.Candidate.from(new JSONObject().put("id", "m1").put("title", "Inception").put("type", "movie").put("year", 2010));
        JSONObject r = v.verify(c);
        assertEquals("verified", r.getString("verdict"));
        assertEquals(148, r.getJSONObject("facts").getInt("runtime"));
    }

    @Test
    public void titlesCheckedBeforeGetTheirLengthOnce() throws Exception {
        File dir = tmp.newFolder();
        long now = System.currentTimeMillis();
        JSONArray media = new JSONArray()
                .put(entry("m-old", "Inception", "verified", now).put("ext", new JSONObject().put("tmdb", "movie/27205")))
                .put(entry("m-has", "Heat", "verified", now).put("runtime", 170).put("ext", new JSONObject().put("tmdb", "movie/949")))
                .put(entry("m-tried", "Up", "verified", now).put("runtime_tried", now).put("ext", new JSONObject().put("tmdb", "movie/14160")))
                .put(entry("m-book", "Dune", "verified", now).put("type", "book").put("ext", new JSONObject().put("anilist", "5")));
        writeDb(dir, media);
        FakeNet net = new FakeNet().on("3/movie/27205?", "{\"runtime\":148}");
        JSONObject sum = new VerifyJob(dir, new TitleVerifier(net, new FakeClock(), "k", null), new AtomicBoolean()).run(0, 0, null);
        assertEquals(1, sum.getInt("lengths"));
        assertEquals(1, net.calls.size());
        JSONObject taken = new JSONObject(VerifyJob.take(dir));
        assertEquals("details", taken.getJSONObject("m-old").getString("verdict"));
        assertEquals(148, taken.getJSONObject("m-old").getInt("runtime"));
    }
}
