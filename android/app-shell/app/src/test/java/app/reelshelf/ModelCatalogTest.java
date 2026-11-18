package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import java.io.File;
import java.io.IOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The table of models is the trust anchor of every download, so it is checked like data: pinned addresses, well-formed
 * fingerprints, and agreement with the page that lists the same models (assets/local/local.js, MODELS).
 */
public class ModelCatalogTest {
    private static final Pattern PINNED = Pattern.compile("^https://huggingface\\.co/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/resolve/[0-9a-f]{40}/[A-Za-z0-9._-]+$");
    private static final Pattern HEX64 = Pattern.compile("^[0-9a-f]{64}$");

    @Test
    public void everyAddressIsPinnedToACommitAndNeverMain() throws Exception {
        for (ModelCatalog.Entry e : ModelCatalog.ALL) {
            assertTrue(e.id + ": " + e.url, PINNED.matcher(e.url).matches());
            assertFalse(e.id + " must not follow main", e.url.contains("/main/"));
            assertTrue(e.id + " must end with its file name", e.url.endsWith("/" + e.file));
            URL u = new URL(e.url);
            assertEquals("https", u.getProtocol());
            assertTrue(e.id + " host must pass the redirect rule too", ModelVerifier.allowedHost(u.getHost()));
        }
    }

    @Test
    public void everyFingerprintAndSizeIsWellFormed() {
        Set<String> ids = new HashSet<>();
        Set<String> files = new HashSet<>();
        assertEquals(3, ModelCatalog.ALL.size());
        for (ModelCatalog.Entry e : ModelCatalog.ALL) {
            assertTrue(e.id + " sha256 must be 64 lowercase hex digits: " + e.sha256, HEX64.matcher(e.sha256).matches());
            assertTrue(e.id + " size must be positive", e.bytes > 0);
            assertTrue(e.file.endsWith(".litertlm"));
            assertEquals("a file name only", new File(e.file).getName(), e.file);
            assertTrue("unique id " + e.id, ids.add(e.id));
            assertTrue("unique file " + e.file, files.add(e.file));
            assertTrue("older fingerprints are empty in this release (a new download is always the pinned file)", e.accepted.isEmpty());
            for (String a : e.accepted) {
                assertTrue(HEX64.matcher(a).matches());
                assertFalse(a.equals(e.sha256));
            }
        }
    }

    @Test
    public void theThreePageModelsAreTheThreeRows() {
        assertEquals("qwen", ModelCatalog.QWEN.id);
        assertEquals("gemma4", ModelCatalog.GEMMA4.id);
        assertEquals("gemma4e4", ModelCatalog.GEMMA4_E4.id);
        assertSame(ModelCatalog.QWEN, ModelCatalog.DEFAULT);
    }

    @Test
    public void javaPicksTheModelByName_andAnUnknownNameIsRefused() {
        for (ModelCatalog.Entry e : ModelCatalog.ALL) assertSame(e, ModelCatalog.lookup(e.file));
        assertSame("no name is the default model, as LocalModel.file does", ModelCatalog.DEFAULT, ModelCatalog.lookup(""));
        assertSame(ModelCatalog.DEFAULT, ModelCatalog.lookup(null));
        assertSame("only the last part of a name counts", ModelCatalog.GEMMA4, ModelCatalog.lookup("../../x/" + ModelCatalog.GEMMA4.file));
        assertNull(ModelCatalog.lookup("evil.litertlm"));
        assertNull("a catalog name in another case is another file", ModelCatalog.lookup(ModelCatalog.GEMMA4.file.toUpperCase()));
        assertNull(ModelCatalog.lookup(ModelCatalog.GEMMA4.file + ".part"));
        assertNull("an id is not a file name", ModelCatalog.lookup("gemma4"));
        assertNull(ModelCatalog.lookup("https://example.com/other.litertlm"));
        assertEquals("Only the models listed in Settings can be downloaded. Use 'Use my own model file (.litertlm)' for others.", ModelCatalog.UNKNOWN);
    }

    @Test
    public void everyRowCarriesTheAddressOfItsOwnModelOnly() {
        // a copy-and-paste slip between rows would send one model's bytes to another model's name
        assertTrue(ModelCatalog.QWEN.url.contains("/Qwen2.5-1.5B-Instruct/"));
        assertTrue(ModelCatalog.GEMMA4.url.contains("/gemma-4-E2B-it-litert-lm/"));
        assertTrue(ModelCatalog.GEMMA4_E4.url.contains("/gemma-4-E4B-it-litert-lm/"));
        Set<String> shas = new HashSet<>();
        Set<String> urls = new HashSet<>();
        for (ModelCatalog.Entry e : ModelCatalog.ALL) {
            assertTrue("each row has its own fingerprint", shas.add(e.sha256));
            assertTrue("each row has its own address", urls.add(e.url));
        }
    }

    // ------------------------------------------------------------------ the page lists the same models

    private static File repoFile(String relative) {
        File d = new File("").getAbsoluteFile();
        for (File up = d; up != null; up = up.getParentFile()) {
            File f = new File(up, relative);
            if (f.exists()) return f;
        }
        fail(relative + " was not found in or above " + d + ": run Gradle from the repository (the page code is read from it)");
        return null;
    }

    private static String localJs() throws IOException {
        return new String(Files.readAllBytes(repoFile("android/app-shell/app/src/main/assets/local/local.js").toPath()), StandardCharsets.UTF_8);
    }

    /** The text of the page's MODELS array. */
    private static String modelsBlock(String js) {
        int from = js.indexOf("const MODELS = [");
        assertTrue("local.js has no MODELS array", from >= 0);
        int to = js.indexOf("\n];", from);
        assertTrue(to > from);
        return js.substring(from, to);
    }

    @Test
    public void everyPageModelHasACatalogRow_andItsDisplaySizeIsWithinOnePercent() throws Exception {
        String block = modelsBlock(localJs());
        List<String> ids = new ArrayList<>(), files = new ArrayList<>(), sizes = new ArrayList<>();
        for (Matcher m = Pattern.compile("\\bid: \"([^\"]+)\"").matcher(block); m.find(); ) ids.add(m.group(1));
        for (Matcher m = Pattern.compile("\\bfile: \"([^\"]+)\"").matcher(block); m.find(); ) files.add(m.group(1));
        for (Matcher m = Pattern.compile("\\bsize: ([0-9.e+]+)").matcher(block); m.find(); ) sizes.add(m.group(1));
        assertEquals("the page lists the same models as the catalog", ModelCatalog.ALL.size(), files.size());
        assertEquals(files.size(), ids.size());
        assertEquals(files.size(), sizes.size());
        for (int i = 0; i < files.size(); i++) {
            ModelCatalog.Entry e = ModelCatalog.lookup(files.get(i));
            assertNotNull("the page model " + files.get(i) + " has no catalog row", e);
            assertEquals(e.file, files.get(i));
            assertEquals(e.id, ids.get(i));
            double shown = Double.parseDouble(sizes.get(i));
            assertTrue(e.id + ": the page shows " + shown + " bytes, the catalog says " + e.bytes, Math.abs(shown - e.bytes) <= e.bytes * 0.01);
        }
        assertEquals("the page's first model is the default", ModelCatalog.DEFAULT.file, files.get(0));
    }

    @Test
    public void theMessagesNameButtonsThePageReallyHas() throws Exception {
        String js = localJs();
        assertTrue("the page has the button the unknown-name message points to", js.contains("Use my own model file (.litertlm)"));
        assertTrue(ModelCatalog.UNKNOWN, ModelCatalog.UNKNOWN.contains("Use my own model file (.litertlm)"));
        assertTrue("a part is continued with this button", js.contains("\"Continue download\""));
        assertTrue(ModelVerifier.STOPPED_EARLY, ModelVerifier.STOPPED_EARLY.contains("Continue download"));
    }

    @Test
    public void thePageNoLongerCarriesAnAddress() throws Exception {
        String js = localJs();
        assertFalse("local.js must not name a /resolve/main/ address", js.contains("resolve/main"));
        assertFalse("the page's MODELS must not carry a url field", Pattern.compile("\\burl:\\s*\"https://huggingface").matcher(modelsBlock(js)).find());
        Matcher m = Pattern.compile("phone\\(\"downloadModel\",\\s*([^,]*),").matcher(js);
        int calls = 0;
        while (m.find()) {
            calls++;
            assertEquals("the page sends no address", "\"\"", m.group(1).trim());
        }
        assertTrue("the page still asks for downloads", calls >= 2);
    }

    // ------------------------------------------------------------------ the speech model's row

    private static final Pattern HEX32 = Pattern.compile("^[0-9a-f]{32}$");

    @Test
    public void theSpeechRowIsPinnedToItsOwnHostWithBothFingerprints() throws Exception {
        ModelCatalog.Entry e = ModelCatalog.SPEECH;
        URL u = new URL(e.url);
        assertEquals("https", u.getProtocol());
        assertEquals("alphacephei.com", u.getHost());
        assertEquals("the row names its one host", "alphacephei.com", e.onlyHost);
        assertEquals("/vosk/models/" + ModelCatalog.SPEECH_FOLDER + ".zip", u.getPath());
        assertEquals(ModelCatalog.SPEECH_FOLDER + ".zip", e.file);
        assertTrue(e.url.endsWith("/" + e.file));
        assertTrue("sha256: " + e.sha256, HEX64.matcher(e.sha256).matches());
        assertTrue("md5: " + e.md5, HEX32.matcher(e.md5).matches());
        assertTrue(e.bytes > 0);
        assertTrue(e.accepted.isEmpty());
        assertEquals("the folder the ZIP unpacks to is the name the app looks for", ModelCatalog.SPEECH_FOLDER, ModelCatalog.SPEECH_ZIP.folder);
        // What was read from alphacephei.com (size = Content-Length, md5 = model-list.json) and measured by one real download
        // on 2026-11-18. A change here is a release step (see the comment on the row): change these three values with it.
        assertEquals(41_205_931L, e.bytes);
        assertEquals("09ab50ccd62b674cbaa231b825f9c1cb", e.md5);
        assertEquals("30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498", e.sha256);
    }

    @Test
    public void theSpeechRowIsNotSomethingThePageCanAskForByName_andTheAiRowsHaveNoSpeechRules() {
        assertFalse(ModelCatalog.ALL.contains(ModelCatalog.SPEECH));
        assertNull(ModelCatalog.lookup(ModelCatalog.SPEECH.file));
        assertNull(ModelCatalog.lookup(ModelCatalog.SPEECH.id));
        assertNull(ModelCatalog.lookup(ModelCatalog.SPEECH_FOLDER));
        for (ModelCatalog.Entry e : ModelCatalog.ALL) {
            assertNull(e.id + " has no md5 to match", e.md5);
            assertNull(e.id + " is fetched from Hugging Face's hosts, not from one host", e.onlyHost);
        }
    }

    @Test
    public void theUnpackLimitsSitJustAboveWhatThePublishedZipHolds() {
        ModelZip.Plan p = ModelCatalog.SPEECH_ZIP;
        assertEquals("the published ZIP holds 20 entries", 20, ModelCatalog.SPEECH_ENTRIES);
        assertEquals("and 70898967 bytes once unpacked", 70_898_967L, ModelCatalog.SPEECH_UNPACKED);
        assertTrue(p.maxEntries >= ModelCatalog.SPEECH_ENTRIES && p.maxEntries <= ModelCatalog.SPEECH_ENTRIES + 4);
        assertTrue(p.maxBytes >= ModelCatalog.SPEECH_UNPACKED && p.maxBytes <= ModelCatalog.SPEECH_UNPACKED * 112 / 100);
        assertTrue("well below the old 400 MB cap", p.maxBytes < 100L * 1024 * 1024);
        assertEquals(Arrays.asList("am", "conf"), p.oneOf);
    }

    // ------------------------------------------------------------------ the speech download goes through the same gate as the AI model

    private static String bridge() throws IOException {
        return new String(Files.readAllBytes(repoFile("android/app-shell/app/src/main/java/app/reelshelf/LocalBridge.java").toPath()), StandardCharsets.UTF_8);
    }

    /** The text of one method: from its signature to the brace that closes it. */
    private static String body(String src, String signature) {
        int from = src.indexOf(signature);
        assertTrue(signature + " was not found", from >= 0);
        int open = src.indexOf('{', from);
        int depth = 0;
        for (int i = open; i < src.length(); i++) {
            if (src.charAt(i) == '{') depth++;
            if (src.charAt(i) == '}' && --depth == 0) return src.substring(from, i + 1);
        }
        fail("no end for " + signature);
        return null;
    }

    @Test
    public void downloadSpeechTakesTheSharedFlagBeforeItStartsAndGivesItBackAtTheEnd() throws Exception {
        // A source-text check (the bridge needs Android, so it cannot run here): only one download at a time, AI model or speech model.
        String src = bridge();
        String speech = body(src, "public void downloadSpeech(int id)");
        String model = body(src, "public void downloadModel(int id, String url, String name)");
        for (String m : new String[]{speech, model}) {
            int check = m.indexOf("if (downloading) {");
            int take = m.indexOf("downloading = true;");
            int run = m.indexOf("net.execute(");
            assertTrue("both downloads look at the shared flag first", check >= 0 && check < take);
            assertTrue("and take it before the work is handed to the worker", take < run);
            assertTrue("and give it back in a finally block", m.indexOf("downloading = false;", m.indexOf("finally {")) > 0);
        }
        assertFalse("the speech download is not gated by a flag of its own", speech.contains("if (speechDownloading)"));
        assertTrue(src.contains("private volatile boolean downloading;"));
        assertEquals("one flag for the gate", 1, src.split("private volatile boolean downloading;", -1).length - 1);
        assertTrue("the AI model's card does not show the speech download", body(src, "public String modelInfo(String name)").contains("downloading && !speechDownloading"));
    }

    @Test
    public void downloadSpeechGoesOnlyThroughTheVerifiedPath() throws Exception {
        String src = bridge();
        String speech = body(src, "public void downloadSpeech(int id)");
        assertTrue(speech.contains("ModelZip.fetch("));
        assertTrue(speech.contains("ModelCatalog.SPEECH,"));
        assertTrue(speech.contains("ModelCatalog.SPEECH_ZIP"));
        assertFalse("the ZIP does not go to the cache folder, which Android may empty", speech.contains("getCacheDir"));
        String model = new String(Files.readAllBytes(repoFile("android/app-shell/app/src/main/java/app/reelshelf/LocalModel.java").toPath()), StandardCharsets.UTF_8);
        assertFalse("no download without a check is left", model.contains("download(String"));
        assertFalse(model.contains("HttpURLConnection"));
        String speechModel = new String(Files.readAllBytes(repoFile("android/app-shell/app/src/main/java/app/reelshelf/SpeechModel.java").toPath()), StandardCharsets.UTF_8);
        assertFalse("the old unpack (no checks) is gone", speechModel.contains("unpack("));
        assertFalse("the speech model has no address of its own besides the catalog row", speechModel.contains("https://"));
    }

    @Test
    public void thePageAsksForTheSpeechModelWithoutAnAddress() throws Exception {
        String js = localJs();
        assertFalse("local.js must not name the speech server", js.contains("alphacephei"));
        Matcher m = Pattern.compile("phone\\(\"downloadSpeech\"([^)]*)\\)").matcher(js);
        assertTrue(m.find());
        assertEquals("no argument at all", "", m.group(1).trim());
    }
}
