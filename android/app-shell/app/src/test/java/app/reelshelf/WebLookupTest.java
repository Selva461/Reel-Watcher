package app.reelshelf;

import org.json.JSONArray;
import org.junit.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class WebLookupTest {
    static final String WIKI = "{\"query\":{\"pages\":{\"2\":{\"title\":\"Rust (video game)\",\"index\":2,\"extract\":\"Rust is a survival game.\","
            + "\"fullurl\":\"https://en.wikipedia.org/wiki/Rust_(video_game)\"},\"1\":{\"title\":\"Rust (programming language)\",\"index\":1,"
            + "\"extract\":\"Rust is a programming language.\",\"fullurl\":\"https://en.wikipedia.org/wiki/Rust_(programming_language)\"}}}}";
    static final String DDG = "{\"Heading\":\"Rust\",\"AbstractText\":\"Rust is a language.\",\"AbstractURL\":\"https://en.wikipedia.org/wiki/Rust_(programming_language)\","
            + "\"AbstractSource\":\"Wikipedia\",\"Answer\":\"\",\"RelatedTopics\":[]}";

    @Test
    public void onlyTheQuestionGoesToWikipediaAndDuckDuckGoAndSourcesComeBack() throws Exception {
        List<String> urls = new ArrayList<>();
        WebLookup w = new WebLookup((url, body, h) -> {
            urls.add(url);
            assertEquals(null, body);  // nothing is posted
            return new TitleVerifier.Res(200, url.contains("wikipedia") ? WIKI : DDG, 0);
        });
        JSONArray r = w.search("what is rust\n\n(my notes must never be sent)" + "x".repeat(300));
        assertEquals(2, urls.size());
        assertTrue(urls.get(0).startsWith("https://api.duckduckgo.com/?"));
        assertTrue(urls.get(1).startsWith("https://en.wikipedia.org/w/api.php?"));
        for (String u : urls) assertTrue(u.length() < 600);  // the question is cut to 200 characters
        assertEquals(2, r.length());  // the same Wikipedia page from DuckDuckGo is listed once
        assertEquals("https://en.wikipedia.org/wiki/Rust_(programming_language)", r.getJSONObject(0).getString("url"));
        assertEquals("Rust (video game)", r.getJSONObject(1).getString("title"));  // Wikipedia's own order
        assertFalse(r.getJSONObject(0).getString("text").isEmpty());
    }

    @Test
    public void offlineSaysSoAndEmptyQuestionAsksNothing() throws Exception {
        WebLookup down = new WebLookup((url, body, h) -> { throw new IOException("no network"); });
        try {
            down.search("rust");
            fail();
        } catch (IOException e) {
            assertTrue(e.getMessage().contains("No internet"));
        }
        List<String> urls = new ArrayList<>();
        assertEquals(0, new WebLookup((url, body, h) -> { urls.add(url); return null; }).search("  \n ").length());
        assertTrue(urls.isEmpty());
    }

    @Test
    public void aQuoteIsLookedUpOnWikiquoteAsOneExactPhrase() throws Exception {
        List<String> urls = new ArrayList<>();
        WebLookup w = new WebLookup((url, body, h) -> {
            urls.add(url);
            return new TitleVerifier.Res(200, url.contains("Nobody") ? "{\"query\":{\"search\":[]}}"
                    : "{\"query\":{\"search\":[{\"title\":\"The Dark Knight (film)\",\"snippet\":\"<span class=\\\"searchmatch\\\">Why so serious</span>?\"}]}}", 0);
        });
        org.json.JSONObject r = w.quote("Why so serious? Let's put a smile on that face, said the man in the purple suit at the party");
        assertTrue(r.getBoolean("found"));
        assertEquals("The Dark Knight (film)", r.getString("page"));
        assertEquals("https://en.wikiquote.org/wiki/The_Dark_Knight_(film)", r.getString("url"));
        assertEquals("Why so serious?", r.getString("snippet"));
        assertTrue(urls.get(0).startsWith("https://en.wikiquote.org/w/api.php?"));
        assertTrue(urls.get(0).contains("srsearch=%22Why+so+serious+Let%27s+put+a+smile+on+that+face+said+the%22"));  // 12 words, one phrase
        assertFalse(w.quote("Nobody ever said this line anywhere").getBoolean("found"));
    }
}
