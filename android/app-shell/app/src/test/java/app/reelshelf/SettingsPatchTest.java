package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

/** A page saves only the settings it changed: nothing else stored is touched. */
public class SettingsPatchTest {
    private static JSONObject merge(String stored, String patch) throws Exception {
        return new JSONObject(SettingsPatch.merge(stored, patch));
    }

    @Test
    public void onlyThePatchedKeysChange() throws Exception {
        String stored = "{\"tmdbKey\":\"my-key\",\"verifyRunning\":true,\"webLookup\":false,\"nightMax\":200}";
        JSONObject m = merge(stored, "{\"webLookup\":true}");
        assertTrue(m.getBoolean("webLookup"));
        assertEquals("my-key", m.getString("tmdbKey"));
        assertTrue("a key the other page set is not reverted", m.getBoolean("verifyRunning"));
        assertEquals(200, m.getInt("nightMax"));
    }

    @Test
    public void twoPagesChangingDifferentKeysBothSurvive() throws Exception {
        String stored = "{}";
        stored = SettingsPatch.merge(stored, "{\"verifyRunning\":true}");  // the nightly page
        stored = SettingsPatch.merge(stored, "{\"tmdbKey\":\"abc\"}");  // the app screen, which loaded before that
        JSONObject m = new JSONObject(stored);
        assertTrue(m.getBoolean("verifyRunning"));
        assertEquals("abc", m.getString("tmdbKey"));
    }

    @Test
    public void valuesOfEveryKindKeepTheirType() throws Exception {
        JSONObject m = merge("{\"a\":1}", "{\"s\":\"café \\\"q\\\"\",\"n\":0.3,\"b\":false,\"i\":800}");
        assertEquals("café \"q\"", m.getString("s"));
        assertEquals(0.3, m.getDouble("n"), 0.0001);
        assertFalse(m.getBoolean("b"));
        assertEquals(800, m.getInt("i"));
        assertEquals(1, m.getInt("a"));
    }

    @Test
    public void aKeySetToNullIsRemoved() throws Exception {
        JSONObject m = merge("{\"a\":1,\"b\":2}", "{\"a\":null}");
        assertFalse(m.has("a"));
        assertEquals(2, m.getInt("b"));
    }

    @Test
    public void nothingStoredYetOrAnUnreadableStoredValueStartsFromTheNewKeysOnly() throws Exception {
        assertEquals(1, merge(null, "{\"a\":1}").getInt("a"));
        assertEquals(1, merge("", "{\"a\":1}").getInt("a"));
        assertEquals(1, merge("{broken", "{\"a\":1}").getInt("a"));
    }

    @Test
    public void aPatchThatIsNotAnObjectChangesNothing() throws Exception {
        assertEquals("{\"a\":1}", SettingsPatch.merge("{\"a\":1}", "[1,2]"));
        assertEquals("{\"a\":1}", SettingsPatch.merge("{\"a\":1}", "nonsense"));
        assertEquals("{\"a\":1}", SettingsPatch.merge("{\"a\":1}", null));
        assertEquals("{}", SettingsPatch.merge(null, null));
    }
}
