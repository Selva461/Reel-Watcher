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
        public synchronized TitleVerifier.Res send(String url, String body, Map<String, String> headers) throws IOException {
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

        synchronized int count(String part) {
            int n = 0;
            for (String c : calls) if (c.contains(part)) n++;
            return n;
        }
    }

    static final class FakeClock implements TitleVerifier.Clock {
        long t = 1_800_000_000_000L;
        long slept;

        public synchronized long now() {
            return t;
        }

        public synchronized void sleep(long ms) {
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

    /** Wikidata also has this film (the second, independent source a title needs). */
    static FakeNet withWd(FakeNet net, String qid, String label, String year, String tmdbMovieId) throws Exception {
        return net.on("wbsearchentities", wdSearch(qid)).on("wbgetentities", new JSONObject().put("entities", new JSONObject()
                .put(qid, wdEntity(label, "Q11424", year, "Q1860", tmdbMovieId))).toString());
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
    public void aRemakeWithoutAYearGoesToTheOneMoreSourcesAgreeOn() throws Exception {
        // TMDB alone is one source: nothing is renamed on it
        FakeNet net0 = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(438631, "Dune", "2021-09-15", "en", "/d21.jpg", 878),
                tmdbMovie(841, "Dune", "1984-12-14", "en", "/d84.jpg", 878)));
        JSONObject r0 = new TitleVerifier(net0, new FakeClock(), "k", null).verify(cand("DUNE", "movie", 0));
        assertEquals("not_found", r0.getString("verdict"));  // only TMDB has it: one source is never enough
        assertFalse(r0.has("facts"));
        assertTrue(r0.getString("note"), r0.getString("note").contains("a second source has to agree"));
        assertTrue(r0.getJSONArray("choices").toString().contains("\"sources\":1"));

        // Wikidata knows only the 1984 film by that name: two sources agree, so that one is picked, with no question
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(438631, "Dune", "2021-09-15", "en", "/d21.jpg", 878),
                tmdbMovie(841, "Dune", "1984-12-14", "en", "/d84.jpg", 878)))
                .on("wbsearchentities", wdSearch("Q114819"))
                .on("wbgetentities", new JSONObject().put("entities", new JSONObject().put("Q114819",
                        wdEntity("Dune", "Q11424", "1984", "Q1860", "841"))).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("DUNE", "movie", 0));
        assertEquals("verified", r.getString("verdict"));
        assertEquals(1984, r.getJSONObject("facts").getInt("year"));
        assertEquals("Dune", r.getJSONObject("facts").getString("title"));  // the official name, not "DUNE"
        assertTrue(r.getString("by").contains("wikidata"));

        // with the year seen on the screenshot it is clear, and Wikidata agrees
        FakeNet net2 = withWd(new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(438631, "Dune", "2021-09-15", "en", "/d21.jpg", 878),
                tmdbMovie(841, "Dune", "1984-12-14", "en", "/d84.jpg", 878))), "Q114819", "Dune", "1984", "841");
        JSONObject r2 = new TitleVerifier(net2, new FakeClock(), "k", null).verify(cand("Dune", "movie", 1984));
        assertEquals("verified", r2.getString("verdict"));
        assertEquals(1984, r2.getJSONObject("facts").getInt("year"));
    }

    @Test
    public void withoutATmdbKeyMoviesAreFoundOnWikidataButNotConfirmed() throws Exception {
        FakeNet net = new FakeNet().on("wbsearchentities", wdSearch("Q1", "Q2"))
                .on("wbgetentities&format=json&props=labels|aliases|claims", new JSONObject().put("entities", new JSONObject()
                        .put("Q1", wdEntity("Vikram", "Q11424", "2022", "Q5885", null))
                        .put("Q2", new JSONObject().put("labels", new JSONObject()).put("claims", claim("P31", new JSONObject().put("id", "Q5"))))).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "", null).verify(cand("Vikram", "movie", 2022));
        assertEquals(0, net.count("themoviedb"));
        // Wikidata alone is one source: without a TMDB key there is no second one for films, so it is not renamed
        assertEquals("not_found", r.getString("verdict"));
        assertTrue(r.getString("note").contains("a second source has to agree"));
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
                anilistMedia(2, 2, "MANGA", "MANGA", "Berserk", "Berserk", 1989, "JP", "Action")))
                .on("api.jikan.moe/v4/anime", "{\"data\":[{\"mal_id\":33,\"title\":\"Kenpuu Denki Berserk\",\"title_english\":\"Berserk\",\"type\":\"TV\",\"year\":1997}]}");
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
        FakeNet net = withWd(new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28))),
                "Q25188", "Inception", "2010", "27205");
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
        FakeNet net = withWd(new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28))),
                "Q25188", "Inception", "2010", "27205");
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
        assertEquals(148, v.details(ext, "movie").runtime);
        ext.put("tmdb", "tv/1399");
        TitleVerifier.Details got = v.details(ext, "series");
        assertEquals(68, got.runtime);
        assertEquals(73, got.episodes);
        Map<String, String> an = new java.util.HashMap<>();
        an.put("anilist", "21");
        assertEquals(24, v.details(an, "anime").runtime);
        Map<String, String> bad = new java.util.HashMap<>();
        bad.put("tmdb", "movie/1?x=");  // not an id: nothing is asked
        int before = net.calls.size();
        assertEquals(0, v.details(bad, "movie").runtime);
        assertEquals(before, net.calls.size());
    }

    @Test
    public void aVerifiedMovieGetsItsLength() throws Exception {
        FakeNet net = withWd(new FakeNet().on("3/movie/27205?", "{\"runtime\":148}")
                .on("search/multi", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/i.jpg", 28))), "Q25188", "Inception", "2010", "27205");
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
                .put(entry("m-has", "Heat", "verified", now).put("runtime", 170).put("details_at", now).put("ext", new JSONObject().put("tmdb", "movie/949")))
                .put(entry("m-tried", "Up", "verified", now).put("details_at", now).put("ext", new JSONObject().put("tmdb", "movie/14160")))
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

    @Test
    public void aMisspeltNameIsFoundThroughWikipediaAndTakesItsOfficialName() throws Exception {
        String page = new JSONObject().put("query", new JSONObject().put("pages", new JSONObject()
                .put("41", new JSONObject().put("index", 2).put("title", "Christopher Nolan").put("fullurl", "https://en.wikipedia.org/wiki/Christopher_Nolan")
                        .put("pageprops", new JSONObject().put("wikibase_item", "Q25191")))
                .put("40", new JSONObject().put("index", 1).put("title", "Interstellar (film)").put("fullurl", "https://en.wikipedia.org/wiki/Interstellar_(film)")
                        .put("pageprops", new JSONObject().put("wikibase_item", "Q13417189"))))).toString();
        JSONObject person = new JSONObject().put("labels", new JSONObject().put("en", new JSONObject().put("value", "Christopher Nolan")))
                .put("claims", new JSONObject().put("P31", claim("P31", new JSONObject().put("id", "Q5")).getJSONArray("P31")));
        FakeNet net = new FakeNet()  // neither TMDB nor Wikidata's label search knows the misspelling
                .on("query=Interstellar", tmdb(tmdbMovie(157336, "Interstellar", "2014-11-05", "en", "/s.jpg", 878)))
                .on("en.wikipedia.org", page)
                .on("wbgetentities", new JSONObject().put("entities", new JSONObject()
                        .put("Q13417189", wdEntity("Interstellar", "Q11424", "2014", "Q1860", "157336")).put("Q25191", person)).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("Intersteller", "movie", 0));
        assertEquals("verified", r.getString("verdict"));
        JSONObject f = r.getJSONObject("facts");
        assertEquals("Interstellar", f.getString("title"));
        assertEquals(2014, f.getInt("year"));
        assertEquals("movie/157336", f.getJSONObject("ext").getString("tmdb"));
        assertEquals("https://en.wikipedia.org/wiki/Interstellar_(film)", f.getJSONObject("ext").getString("wikipedia"));
        assertEquals("wikipedia+tmdb", r.getString("by"));  // found on Wikipedia, confirmed by TMDB
        assertEquals(1, net.count("en.wikipedia.org"));  // asked once, only after the others found nothing
    }

    @Test
    public void aWeakMatchOnOneSourceIsNotRenamed() throws Exception {
        FakeNet net = new FakeNet().on("themoviedb.org", tmdb(tmdbMovie(5, "The Garden of Words", "2013-05-31", "ja", "/g.jpg", 16)));
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("Garden Wars", "movie", 0));
        assertEquals("not_found", r.getString("verdict"));
        assertFalse(r.has("facts"));  // nothing to rename it with
    }

    @Test
    public void wikipediaIsNotAskedWhenTheDatabasesAlreadyAgree() throws Exception {
        FakeNet net = new FakeNet()
                .on("themoviedb.org/3/search/multi", tmdb(tmdbMovie(27205, "Inception", "2010-07-15", "en", "/inc.jpg", 28, 878)))
                .on("wbsearchentities", wdSearch("Q25188"))
                .on("wbgetentities", new JSONObject().put("entities", new JSONObject().put("Q25188",
                        wdEntity("Inception", "Q11424", "2010", "Q1860", "27205"))).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("Inception", "movie", 2010));
        assertEquals("verified", r.getString("verdict"));
        assertEquals(0, net.count("en.wikipedia.org"));
    }

    static String alNode(long id, String format, int eps, int year, String en, long prequel, long sequel) throws Exception {
        JSONArray edges = new JSONArray();
        if (prequel > 0) edges.put(new JSONObject().put("relationType", "PREQUEL").put("node", new JSONObject().put("id", prequel).put("type", "ANIME").put("format", "TV")));
        if (sequel > 0) edges.put(new JSONObject().put("relationType", "SEQUEL").put("node", new JSONObject().put("id", sequel).put("type", "ANIME").put("format", "TV")));
        edges.put(new JSONObject().put("relationType", "ADAPTATION").put("node", new JSONObject().put("id", 999).put("type", "MANGA").put("format", "MANGA")));
        return new JSONObject().put("data", new JSONObject().put("Media", new JSONObject().put("id", id).put("format", format).put("episodes", eps)
                .put("duration", 25).put("averageScore", 82).put("seasonYear", year).put("title", new JSONObject().put("english", en).put("romaji", en))
                .put("relations", new JSONObject().put("edges", edges)))).toString();
    }

    @Test
    public void anAnimeShowsEachSeasonAndItsMyAnimeListScore() throws Exception {
        // AniList keeps each season apart: found as season 2, it walks back to season 1 and on to season 3
        FakeNet net = new FakeNet()
                .on("\"i\":21355", alNode(21355, "TV", 25, 2016, "Re:ZERO -Starting Life in Another World-", 0, 108632))
                .on("\"i\":108632", alNode(108632, "TV", 25, 2020, "Re:ZERO Season 2", 21355, 163134))
                .on("\"i\":163134", alNode(163134, "TV", 16, 2024, "Re:ZERO Season 3", 108632, 0))
                .on("api.jikan.moe/v4/anime/31240", "{\"data\":{\"duration\":\"25 min per ep\",\"episodes\":25,\"score\":8.23,\"scored_by\":1234567}}");
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "", null);
        Map<String, String> ext = new java.util.HashMap<>();
        ext.put("anilist", "108632");
        ext.put("mal", "31240");
        TitleVerifier.Details d = v.details(ext, "anime");
        assertEquals(3, d.seasons.length());
        assertEquals(1, d.seasons.getJSONObject(0).getInt("n"));
        assertEquals(25, d.seasons.getJSONObject(0).getInt("episodes"));
        assertEquals(2016, d.seasons.getJSONObject(0).getInt("year"));
        assertEquals(16, d.seasons.getJSONObject(2).getInt("episodes"));
        assertEquals("Re:ZERO Season 3", d.seasons.getJSONObject(2).getString("title"));
        assertEquals(8.2, d.rating, 0.001);
        assertEquals("MyAnimeList", d.ratingBy);
        assertEquals(1234567, d.votes);
        assertEquals(0, net.count("omdbapi"));
        assertEquals("AniList, checked with MyAnimeList", d.seasonsBy);  // both say 25 episodes for this entry
    }

    @Test
    public void aSeriesShowsTmdbSeasonsAndTheImdbRatingWithAnOmdbKey() throws Exception {
        String tv = "{\"episode_run_time\":[50],\"number_of_episodes\":30,\"vote_average\":8.43,\"vote_count\":5000,"
                + "\"external_ids\":{\"imdb_id\":\"tt4574334\"},\"seasons\":[{\"season_number\":0,\"episode_count\":3,\"name\":\"Specials\"},"
                + "{\"season_number\":1,\"episode_count\":8,\"air_date\":\"2016-07-15\",\"name\":\"Season 1\"},"
                + "{\"season_number\":2,\"episode_count\":9,\"air_date\":\"2017-10-27\",\"name\":\"Season 2\"}]}";
        FakeNet net = new FakeNet().on("3/tv/66732?", tv).on("omdbapi.com/?i=tt4574334", "{\"imdbRating\":\"8.6\",\"imdbVotes\":\"1,412,000\"}");
        TitleVerifier v = new TitleVerifier(net, new FakeClock(), "k", null);
        Map<String, String> ext = new java.util.HashMap<>();
        ext.put("tmdb", "tv/66732");
        TitleVerifier.Details noKey = v.details(ext, "series");
        assertEquals(2, noKey.seasons.length());  // "Specials" is not a season
        assertEquals(8, noKey.seasons.getJSONObject(0).getInt("episodes"));
        assertEquals(2017, noKey.seasons.getJSONObject(1).getInt("year"));
        assertEquals("TMDB", noKey.ratingBy);
        assertEquals(8.4, noKey.rating, 0.001);
        assertEquals("tt4574334", noKey.imdb);
        assertEquals(0, net.count("omdbapi"));
        assertEquals("TMDB (one source)", noKey.seasonsBy);

        v.omdbKey = "my-omdb";
        TitleVerifier.Details d = v.details(ext, "series");
        assertEquals("IMDb", d.ratingBy);
        assertEquals(8.6, d.rating, 0.001);
        assertEquals(1412000, d.votes);
        for (String c : net.calls) if (!c.contains("omdbapi.com")) assertFalse(c.contains("my-omdb"));  // the key goes to OMDb only
    }

    private static String wdSeasons(String id, int n) throws Exception {
        JSONObject snak = new JSONObject().put("datavalue", new JSONObject().put("value", new JSONObject().put("amount", "+" + n)));
        return new JSONObject().put("entities", new JSONObject().put(id, new JSONObject().put("claims", new JSONObject()
                .put("P2437", new JSONArray().put(new JSONObject().put("mainsnak", snak)))))).toString();
    }

    @Test
    public void seasonsAreCheckedWithASecondSource() throws Exception {
        String tv = "{\"seasons\":[{\"season_number\":1,\"episode_count\":8},{\"season_number\":2,\"episode_count\":9}]}";
        Map<String, String> ext = new java.util.HashMap<>();
        ext.put("tmdb", "tv/66732");
        ext.put("wikidata", "Q19865210");
        FakeNet same = new FakeNet().on("3/tv/66732?", tv).on("wbgetentities", wdSeasons("Q19865210", 2));
        assertEquals("TMDB, checked with Wikidata", new TitleVerifier(same, new FakeClock(), "k", null).details(ext, "series").seasonsBy);
        FakeNet differs = new FakeNet().on("3/tv/66732?", tv).on("wbgetentities", wdSeasons("Q19865210", 3));
        TitleVerifier.Details d = new TitleVerifier(differs, new FakeClock(), "k", null).details(ext, "series");
        assertEquals("TMDB (Wikidata says 3 seasons)", d.seasonsBy);
        assertEquals(2, d.seasons.length());  // still shown, with the disagreement said out loud

        // Anime on TMDB often lumps every episode into season 1: AniList's first season says otherwise
        String lumped = "{\"seasons\":[{\"season_number\":1,\"episode_count\":66}]}";
        Map<String, String> an = new java.util.HashMap<>();
        an.put("tmdb", "tv/1429");
        an.put("anilist", "16498");
        FakeNet aot = new FakeNet().on("3/tv/1429?", lumped).on("\"i\":16498", alNode(16498, "TV", 25, 2013, "Attack on Titan", 0, 20958));
        assertEquals("TMDB (AniList says 25 episodes in season 1)", new TitleVerifier(aot, new FakeClock(), "k", null).details(an, "anime").seasonsBy);
    }

    @Test
    public void aVerifiedTitleCarriesItsRatingAndSeasons() throws Exception {
        String tv = "{\"episode_run_time\":[50],\"number_of_episodes\":17,\"vote_average\":8.4,\"vote_count\":5000,"
                + "\"seasons\":[{\"season_number\":1,\"episode_count\":8,\"air_date\":\"2016-07-15\"},{\"season_number\":2,\"episode_count\":9,\"air_date\":\"2017-10-27\"}]}";
        JSONObject show = new JSONObject().put("id", 66732).put("media_type", "tv").put("name", "Stranger Things").put("first_air_date", "2016-07-15")
                .put("original_language", "en").put("genre_ids", new JSONArray()).put("poster_path", "/s.jpg");
        FakeNet net = new FakeNet().on("3/tv/66732?", tv).on("search/multi", new JSONObject().put("results", new JSONArray().put(show)).toString())
                .on("wbsearchentities", wdSearch("Q19865210")).on("wbgetentities", new JSONObject().put("entities", new JSONObject()
                        .put("Q19865210", wdEntity("Stranger Things", "Q5398426", "2016", "Q1860", null))).toString());
        JSONObject r = new TitleVerifier(net, new FakeClock(), "k", null).verify(cand("STRANGER THINGS", "series", 0));
        assertEquals("verified", r.getString("verdict"));
        JSONObject f = r.getJSONObject("facts");
        assertEquals("Stranger Things", f.getString("title"));
        assertEquals(8.4, f.getJSONObject("rating").getDouble("score"), 0.001);
        assertEquals(2, f.getJSONArray("seasons").length());
        assertEquals("TMDB (one source)", f.getString("seasons_by"));  // Wikidata has no number of seasons for it here
    }

    @Test
    public void tenTitlesAreCheckedAtOnceButEachServiceKeepsItsPace() throws Exception {
        File dir = tmp.newFolder();
        long now = System.currentTimeMillis();
        JSONArray media = new JSONArray();
        String[] names = {"Arrival", "Heat", "Alien", "Zodiac", "Memento", "Prisoners", "Sicario", "Gravity", "Inception", "Whiplash",
                "Parasite", "Oldboy", "Amelie", "Rocky", "Jaws", "Vertigo", "Psycho", "Fargo", "Se7en", "Up"};
        for (int i = 0; i < 20; i++) media.put(entry("m-" + i, names[i], "unverified", now - i));
        writeDb(dir, media);
        java.util.concurrent.atomic.AtomicInteger inFlight = new java.util.concurrent.atomic.AtomicInteger();
        java.util.concurrent.atomic.AtomicInteger most = new java.util.concurrent.atomic.AtomicInteger();
        Map<String, List<Long>> at = new java.util.concurrent.ConcurrentHashMap<>();
        Map<String, String> qNames = new java.util.concurrent.ConcurrentHashMap<>();
        TitleVerifier.Http slow = (url, body, headers) -> {  // every answer takes 120 ms, like a phone network
            String host = url.replaceFirst("^https?://", "").split("[/?:]", 2)[0];
            at.computeIfAbsent(host, k -> java.util.Collections.synchronizedList(new ArrayList<>())).add(System.nanoTime() / 1_000_000);
            most.accumulateAndGet(inFlight.incrementAndGet(), Math::max);
            try {
                Thread.sleep(120);
            } catch (InterruptedException e) {
                throw new IOException(e);
            } finally {
                inFlight.decrementAndGet();
            }
            if (url.contains("themoviedb.org")) {
                if (!url.contains("query=")) return new TitleVerifier.Res(200, "{\"runtime\":100}", 0);
                String n = java.net.URLDecoder.decode(url.replaceAll(".*query=([^&]*).*", "$1"), java.nio.charset.StandardCharsets.UTF_8);
                try {
                    return new TitleVerifier.Res(200, tmdb(tmdbMovie(100 + Math.abs(n.hashCode() % 1000), n, "2001-01-01", "en", "/p.jpg", 18)), 0);
                } catch (Exception e) {
                    throw new IOException(e);
                }
            }
            try {  // Wikidata has each film too, with the same TMDB id: the second source
                if (url.contains("wbsearchentities")) {
                    String n = java.net.URLDecoder.decode(url.replaceAll(".*search=([^&]*).*", "$1"), java.nio.charset.StandardCharsets.UTF_8);
                    String q = "Q" + (100 + Math.abs(n.hashCode() % 1000));
                    qNames.put(q, n);
                    return new TitleVerifier.Res(200, wdSearch(q), 0);
                }
                if (url.contains("wbgetentities") && url.contains("claims")) {
                    String q = java.net.URLDecoder.decode(url.replaceAll(".*ids=([^&]*).*", "$1"), java.nio.charset.StandardCharsets.UTF_8);
                    return new TitleVerifier.Res(200, new JSONObject().put("entities", new JSONObject()
                            .put(q, wdEntity(qNames.get(q), "Q11424", "2001", "Q1860", q.substring(1)))).toString(), 0);
                }
            } catch (Exception e) {
                throw new IOException(e);
            }
            return new TitleVerifier.Res(200, "{\"search\":[],\"results\":[]}", 0);
        };
        long t0 = System.nanoTime();
        JSONObject sum = new VerifyJob(dir, new TitleVerifier(slow, TitleVerifier.REAL_CLOCK, "k", null), new AtomicBoolean()).run(0, 0, null);
        long ms = (System.nanoTime() - t0) / 1_000_000;
        assertEquals(20, sum.getInt("checked"));
        assertEquals(20, sum.getInt("verified"));
        assertTrue("several at once: " + most.get(), most.get() >= 3);  // as many as the services' paces allow
        assertEquals(0, at.containsKey("graphql.anilist.co") ? at.get("graphql.anilist.co").size() : 0);  // clear matches skip AniList
        // one by one: 4 calls of 120 ms per title = 9.6 s; at once it is bound only by Wikidata's pace (40 x 150 ms)
        assertTrue("faster than one by one: " + ms + " ms", ms < 20 * 4 * 120 * 3 / 4);
        for (Map.Entry<String, List<Long>> e : at.entrySet()) {  // never faster than the service's own pace
            List<Long> t = new ArrayList<>(e.getValue());
            java.util.Collections.sort(t);
            long gap = e.getKey().contains("themoviedb") ? 50 : 150;
            for (int i = 1; i < t.size(); i++) assertTrue(e.getKey() + " " + (t.get(i) - t.get(i - 1)) + " ms", t.get(i) - t.get(i - 1) >= gap - 5);
        }
    }
}
