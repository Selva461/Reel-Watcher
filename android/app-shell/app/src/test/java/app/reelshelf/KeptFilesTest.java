package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Assume;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "Files kept for safety" without a phone: which names are listed (every name LibraryFile makes, and nothing else), the order, the
 * sizes, and a delete that needs a one-use token, never follows a link, never touches anything but that file, and is refused while
 * work, a backup or a restore runs or the library cannot be trusted.
 */
public class KeptFilesTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final TimeZone UTC = TimeZone.getTimeZone("UTC");
    private static final String V1 = "{\"schema_version\":1,\"reels\":[{\"code\":\"AAAAA1\"}],\"media\":[]}";
    private static final String V2 = "{\"schema_version\":1,\"reels\":[{\"code\":\"AAAAA1\"},{\"code\":\"BBBBB2\"}],\"media\":[]}";
    private static final String SHOTS1 = "{\"v\":1,\"seen\":{\"a\":1},\"reels\":{}}";
    private static final String SHOTS2 = "{\"v\":1,\"seen\":{\"a\":1,\"b\":2},\"reels\":{}}";
    private static final String NEWER = "{\"schema_version\":99,\"reels\":[]}";
    private static final String GARBAGE = "{\"reels\":[{\"code\":\"CUT";
    private static final long MB = 1024 * 1024;

    private static void put(File f, String s) throws IOException {
        f.getParentFile().mkdirs();
        Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8));
    }

    private static String get(File f) throws IOException {
        return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
    }

    private static String[] names(File dir) {
        String[] n = dir.list();
        Arrays.sort(n);
        return n;
    }

    /** Every file under dir (recursively) with its bytes and every link with its target: to show that nothing at all changed. */
    private static String fingerprint(File dir) throws IOException {
        StringBuilder s = new StringBuilder();
        walk(dir.toPath(), dir.toPath(), s);
        return s.toString();
    }

    private static void walk(Path root, Path p, StringBuilder s) throws IOException {
        String[] kids = p.toFile().list();
        if (kids == null) return;
        Arrays.sort(kids);
        for (String k : kids) {
            Path c = p.resolve(k);
            String rel = root.relativize(c).toString();
            if (Files.isSymbolicLink(c)) s.append(rel).append(" -> ").append(Files.readSymbolicLink(c)).append('\n');
            else if (Files.isDirectory(c)) {
                s.append(rel).append("/\n");
                walk(root, c, s);
            } else s.append(rel).append('=').append(get(c.toFile())).append('\n');
        }
    }

    private static void link(File link, File target) throws IOException {
        try {
            Files.createSymbolicLink(link.toPath(), target.toPath());
        } catch (UnsupportedOperationException | IOException e) {
            Assume.assumeNoException("this file system cannot make symbolic links", e);
        }
    }

    /** The stamp LibraryFile puts in a name: in the default time zone, like its own SimpleDateFormat. */
    private static String stamp(long millis) {
        return new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new java.util.Date(millis));
    }

    private static long at(String stamp, TimeZone tz) throws Exception {
        SimpleDateFormat f = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT);
        f.setTimeZone(tz);
        return f.parse(stamp).getTime();
    }

    // ------------------------------------------------------------------ the phone, as a delete sees it

    /** The folder, the one-at-a-time flag, "work is going", the two library files, the waiting restore and the confirmation, with a clock the test moves. */
    private final class Rig {
        final File dir;
        final AtomicBoolean job = new AtomicBoolean();
        final AtomicBoolean working = new AtomicBoolean();
        final LibraryFile reels, shots;
        final RestoreNow.Stage stage = new RestoreNow.Stage();
        final long[] clock = {1_000_000L};
        final AtomicInteger issued = new AtomicInteger();
        final KeptFiles.Confirm confirm = new KeptFiles.Confirm(() -> "tok-" + issued.incrementAndGet(), () -> clock[0]);
        java.util.function.BooleanSupplier workingNow = working::get;

        /** The phone after the page has opened the library and Screenshots: both library files have been read in this process. */
        Rig() throws IOException {
            this(true);
        }

        /** read false: the library files have not been read in this process (a delete then cannot know their state). */
        Rig(boolean read) throws IOException {
            this(tmp.newFolder(), read);
        }

        Rig(File dir, boolean read) {
            this.dir = dir;
            this.reels = LibraryFile.reels(dir);
            this.shots = LibraryFile.shots(dir);
            if (read) readLibraries();
        }

        KeptFiles.Env env() {
            return new KeptFiles.Env(dir, job, workingNow, reels, shots, stage, confirm, UTC);
        }

        /** The answer of ask as JSON. */
        JSONObject ask(String name) throws Exception {
            return new JSONObject(KeptFiles.ask(env(), name));
        }

        /** The token of a successful ask (the test fails when it was refused). */
        String token(String name) throws Exception {
            JSONObject a = ask(name);
            assertTrue(a.toString(), a.getBoolean("ok"));
            assertEquals(name, a.getJSONObject("item").getString("name"));
            return a.getString("token");
        }

        BackupNow.Outcome delete(String name, String token) {
            return KeptFiles.delete(env(), name, token);
        }

        /** Reads the library files the way the page's first load does (a library nobody trusts is then locked). */
        void readLibraries() {
            reels.read();
            shots.read();
        }
    }

    private File kept(Rig r, String name, String content) throws IOException {
        File f = new File(r.dir, name);
        put(f, content);
        return f;
    }

    private static final String S1 = "20261118-103000", S2 = "20261119-090000", S3 = "20261120-235959";

    // ------------------------------------------------------------------ the names

    @Test
    public void everyNameLibraryFileMakesIsListedAndNothingElseIsIncludingTheTwoVariants() throws Exception {
        long now = System.currentTimeMillis();
        Set<String> made = new HashSet<>();
        List<File> dirs = new ArrayList<>();
        for (String lib : new String[]{"reels", "shots"}) {
            boolean r = lib.equals("reels");
            String good1 = r ? V1 : SHOTS1, good2 = r ? V2 : SHOTS2;
            // a) recovery from the backup sets the damaged file aside (NAME.bad-STAMP), twice in a row: the second is NAME.bad-STAMP-2
            File dir = tmp.newFolder();
            dirs.add(dir);
            for (long t : new long[]{now, now + 1000}) put(new File(dir, lib + ".json.bad-" + stamp(t)), "an older damaged file");  // so a "-2" is certain
            LibraryFile f = r ? LibraryFile.reels(dir) : LibraryFile.shots(dir);
            f.read();
            assertTrue(f.write(good1));
            assertTrue(f.write(good2));
            put(f.main, GARBAGE);
            assertEquals(good1, f.read());  // recovered from the backup
            put(f.main, GARBAGE);
            f.read();
            // b) a restore keeps the library it replaced (NAME.before-restore-STAMP), twice
            File staged = tmp.newFile();
            put(staged, good2);
            for (long t : new long[]{now, now + 1000}) put(new File(dir, lib + ".json.before-restore-" + stamp(t)), "an older one");
            File aside1 = f.replaceWith(staged);
            put(staged, good1);
            File aside2 = f.replaceWith(staged);
            assertNotNull(aside1);
            assertNotNull(aside2);
            // c) "Start a new library" sets an unreadable file and an unreadable backup aside (NAME.bad-STAMP and NAME.bak.bad-STAMP)
            File dir2 = tmp.newFolder();
            dirs.add(dir2);
            put(new File(dir2, lib + ".json"), GARBAGE);
            put(new File(dir2, lib + ".json.bak"), GARBAGE);
            LibraryFile g = r ? LibraryFile.reels(dir2) : LibraryFile.shots(dir2);
            g.read();
            assertTrue(g.locked());
            g.startNew();
            // d) a restore over an unreadable library with an unreadable backup sets that backup aside too (NAME.bak.bad-STAMP)
            File dir3 = tmp.newFolder();
            dirs.add(dir3);
            put(new File(dir3, lib + ".json"), GARBAGE);
            put(new File(dir3, lib + ".json.bak"), GARBAGE + " too");
            LibraryFile h = r ? LibraryFile.reels(dir3) : LibraryFile.shots(dir3);
            h.read();
            assertTrue(h.locked());
            put(staged, good1);
            h.replaceWith(staged);
        }
        Set<KeptFiles.Kind> kinds = new HashSet<>();
        boolean sawDash2 = false;
        for (File dir : dirs) {
            Set<String> expected = new HashSet<>();
            for (String n : names(dir)) {
                if (n.equals("reels.json") || n.equals("shots.json") || n.equals("reels.json.bak") || n.equals("shots.json.bak")) continue;
                assertNotNull("LibraryFile made " + n + " but it is not a kept name", KeptFiles.kindOf(n));
                expected.add(n);
                made.add(n);
                kinds.add(KeptFiles.kindOf(n));
                sawDash2 |= n.matches(".*-2");
            }
            Set<String> listed = new HashSet<>();
            for (KeptFiles.Item it : KeptFiles.list(dir, UTC)) listed.add(it.name);
            assertEquals(expected, listed);
        }
        assertTrue("the three kinds were all made: " + kinds, kinds.containsAll(Arrays.asList(KeptFiles.Kind.BAD, KeptFiles.Kind.BAD_BACKUP, KeptFiles.Kind.BEFORE_RESTORE)));
        assertTrue("a name with the -2 suffix was made and matched: " + made, sawDash2);
        assertTrue(made.stream().anyMatch(n -> n.startsWith("shots.json.bak.bad-")));
        assertTrue(made.stream().anyMatch(n -> n.startsWith("reels.json.bak.bad-")));
    }

    @Test
    public void libraryFileMakesNoSetAsideNameThisClassDoesNotKnow() throws Exception {
        // the suffixes LibraryFile puts on a name (".bad-", ".before-restore-"), and the time format of the stamp, are the only ones: a new kind of
        // set-aside file made there must be taught to KeptFiles (and to the page) before it can be listed, saved or deleted
        String src = get(repoFile("android/app-shell/app/src/main/java/app/reelshelf/LibraryFile.java"));
        Set<String> suffixes = new HashSet<>();
        Matcher m = Pattern.compile("\"(\\.[a-z]+(?:-[a-z]+)*-)\"").matcher(src);
        while (m.find()) suffixes.add(m.group(1));
        assertEquals(new HashSet<>(Arrays.asList(".bad-", ".before-restore-")), suffixes);
        Set<String> formats = new HashSet<>();
        Matcher f = Pattern.compile("new SimpleDateFormat\\(\"([^\"]+)\"").matcher(src);
        while (f.find()) formats.add(f.group(1));
        assertEquals(new HashSet<>(Arrays.asList(KeptFiles.STAMP_FORMAT)), formats);
    }

    private static File repoFile(String relative) {
        File d = new File("").getAbsoluteFile();
        for (File up = d; up != null; up = up.getParentFile()) {
            File f = new File(up, relative);
            if (f.exists()) return f;
        }
        fail(relative + " was not found in or above " + d);
        return null;
    }

    @Test
    public void everyRealShapeOfAKeptNameMatchesWithTheRightKindAndSaveName() {
        for (String lib : new String[]{"reels", "shots"}) {
            for (String tail : new String[]{"", "-2", "-3", "-9", "-10", "-99", "-100", "-999999"}) {
                String bad = lib + ".json.bad-" + S1 + tail, badBak = lib + ".json.bak.bad-" + S1 + tail, before = lib + ".json.before-restore-" + S1 + tail;
                assertEquals(bad, KeptFiles.Kind.BAD, KeptFiles.kindOf(bad));
                assertEquals(badBak, KeptFiles.Kind.BAD_BACKUP, KeptFiles.kindOf(badBak));
                assertEquals(before, KeptFiles.Kind.BEFORE_RESTORE, KeptFiles.kindOf(before));
                assertEquals(lib + "-unreadable-" + S1 + tail + ".txt", KeptFiles.saveName(item(bad)));
                assertEquals(lib + "-backup-unreadable-" + S1 + tail + ".txt", KeptFiles.saveName(item(badBak)));
                assertEquals(lib + "-before-restore-" + S1 + tail + ".txt", KeptFiles.saveName(item(before)));
            }
        }
        assertEquals(KeptFiles.Kind.TEMP, KeptFiles.kindOf(KeptFiles.TEMP_NAME));
        assertNull(KeptFiles.saveName(item(KeptFiles.TEMP_NAME)));
    }

    private static KeptFiles.Item item(String name) {
        KeptFiles.Kind k = KeptFiles.kindOf(name);
        return new KeptFiles.Item(name, k, name.startsWith("shots") ? "shots" : name.startsWith("reels") ? "reels" : "", 1, 1, 1, 1);
    }

    @Test
    public void theCurrentLibraryItsBackupTempFilesModelsAndOddNamesAreNeverKeptNames() {
        String longName = "reels.json.bad-" + S1 + "-" + new String(new char[5000]).replace('\0', '9');
        String[] no = {
                "", " ", ".", "..", "reels.json", "shots.json", "reels.json.bak", "shots.json.bak", "reels.json.tmp", "shots.json.tmp", "reels.json.part",
                "reels.json.bad", "reels.json.bad-", "reels.json.bad-x", "reels.json.bad-2026", "reels.json.bad-20261118", "reels.json.bad-20261118-10300",
                "reels.json.bad-" + S1 + ".part", "reels.json.bad-" + S1 + ".tmp", "reels.json.bad-" + S1 + ".bak", "reels.json.bad-" + S1 + "-",
                "reels.json.bad-" + S1 + "-0", "reels.json.bad-" + S1 + "-1", "reels.json.bad-" + S1 + "-02", "reels.json.bad-" + S1 + "-1234567",
                "reels.json.bad-" + S1 + "-2-3", "reels.json.bad-" + S1 + " ", "reels.json.bad-" + S1 + "\n", "reels.json.bad-" + S1 + "\u0000",
                "xreels.json.bad-" + S1, "REELS.JSON.bad-" + S1, "reels.json.BAD-" + S1, "reels_json.bad-" + S1, "reelsXjson.bad-" + S1,
                "other.json.bad-" + S1, "verify-results.json.bad-" + S1, "verify-results.json.before-restore-" + S1, "reels.json.bak.bad", "reels.json.bak.bad-x",
                "reels.json.bak.bak.bad-" + S1, "reels.json.bak.before-restore-" + S1, "reels.json.before-restore", "reels.json.before-restore-x",
                "reels.json.before-restore-" + S1 + ".part", "shots.json.before-restore-" + S1 + ".part", "reels.json.before-restore-" + S1 + "-1",
                "../reels.json.bad-" + S1, "../x", "a/reels.json.bad-" + S1, "/reels.json.bad-" + S1, "reels.json.bad-" + S1 + "/..", "reels.json.bad-" + S1 + "/../reels.json",
                "..\\reels.json.bad-" + S1, "reels.json.bad-" + S1 + "%2e%2e",
                "reels.json.bad-٢٠٢٦١١١٨-١٠٣٠٠٠",  // Arabic-Indic digits
                "models", "x.litertlm", "x.litertlm.part", "shot-inbox", "video-inbox", "share-staging", "backup-work", "backup-check", "restore-staging",
                "manifest.json", "unknown.bin", "temporary-restore-files.bak", "Temporary-Restore-Files", "temporary-restore-files ", " temporary-restore-files",
                longName,
        };
        for (String n : no) assertNull("[" + n.substring(0, Math.min(n.length(), 70)) + "] must not be a kept name", KeptFiles.kindOf(n));
        assertNull(KeptFiles.kindOf(null));
    }

    @Test
    public void aStampThatIsNotARealDateIsStillListedByItsModifiedTime() throws Exception {
        File dir = tmp.newFolder();
        File f = new File(dir, "reels.json.bad-99999999-999999");
        put(f, "x");
        assertTrue(f.setLastModified(1_700_000_000_000L));
        List<KeptFiles.Item> l = KeptFiles.list(dir, UTC);
        assertEquals(1, l.size());
        assertEquals(1_700_000_000_000L, l.get(0).at);
        assertEquals(KeptFiles.stampMillis("reels.json.bad-99999999-999999", KeptFiles.Kind.BAD, UTC), -1);
    }

    // ------------------------------------------------------------------ listing: what, in what order, how big

    @Test
    public void theListHasOnlyKeptFilesNewestFirstWithSizeAndMomentAndTheTemporaryRowLast() throws Exception {
        Rig r = new Rig();
        kept(r, "reels.json.bad-" + S1, "1234567");
        kept(r, "reels.json.before-restore-" + S3, "12");
        kept(r, "shots.json.bad-" + S2, "123");
        kept(r, "reels.json.bad-" + S2 + "-2", "12345");
        kept(r, "reels.json.bad-" + S2, "1234");
        kept(r, "reels.json.bak.bad-" + S1, "");
        kept(r, "shots.json.before-restore-" + S3 + "-3", "x");
        kept(r, "reels.json", V1);
        kept(r, "shots.json", SHOTS1);
        kept(r, "reels.json.bak", V1);
        kept(r, "reels.json.tmp", "temp of a write that runs");
        kept(r, "verify-results.json", "{}");
        kept(r, "restore-staging/reels.json", "abcdefghij");
        kept(r, "backup-check/shots.json", "abcde");
        kept(r, "models/x.litertlm", "model");
        kept(r, "shot-inbox/shot_1_1.jpg", "pic");
        List<KeptFiles.Item> l = KeptFiles.list(r.dir, UTC);
        List<String> order = new ArrayList<>();
        for (KeptFiles.Item it : l) order.add(it.name);
        assertEquals(Arrays.asList(
                "shots.json.before-restore-" + S3 + "-3", "reels.json.before-restore-" + S3,
                "shots.json.bad-" + S2, "reels.json.bad-" + S2 + "-2", "reels.json.bad-" + S2,
                "reels.json.bak.bad-" + S1, "reels.json.bad-" + S1,
                KeptFiles.TEMP_NAME), order);
        KeptFiles.Item a = l.get(3), z = l.get(6), empty = l.get(5), temp = l.get(7);
        assertEquals(5, a.size);
        assertEquals(KeptFiles.Kind.BAD, a.kind);
        assertEquals("reels", a.library);
        assertEquals(at(S2, UTC), a.at);
        assertEquals(7, z.size);
        assertEquals(0, empty.size);
        assertEquals("shots", l.get(0).library);
        assertEquals(KeptFiles.Kind.BEFORE_RESTORE, l.get(0).kind);
        assertEquals(KeptFiles.Kind.TEMP, temp.kind);
        assertEquals(15, temp.size);
        assertEquals(2, temp.files);
        assertEquals("", temp.library);
        for (KeptFiles.Item it : l.subList(0, 7)) assertEquals(1, it.files);
    }

    @Test
    public void theMomentIsReadInThePhonesOwnTimeZone() throws Exception {
        Rig r = new Rig();
        kept(r, "reels.json.bad-" + S1, "x");
        TimeZone india = TimeZone.getTimeZone("Asia/Kolkata");
        long utc = KeptFiles.list(r.dir, UTC).get(0).at, ist = KeptFiles.list(r.dir, india).get(0).at;
        assertEquals(5.5 * 3600 * 1000, utc - ist, 0);
    }

    @Test
    public void nothingIsListedWhenNothingIsKeptAndAMissingFolderIsAnErrorSentenceNotAnEmptyList() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), V1);
        assertTrue(KeptFiles.list(dir, UTC).isEmpty());
        JSONObject empty = new JSONObject(KeptFiles.listJson(dir, UTC));
        assertEquals(0, empty.getJSONArray("items").length());
        assertEquals("", empty.getString("error"));
        JSONObject gone = new JSONObject(KeptFiles.listJson(new File(dir, "no-such-folder"), UTC));
        assertEquals(0, gone.getJSONArray("items").length());
        assertEquals(KeptFiles.LIST_FAILED, gone.getString("error"));
    }

    @Test
    public void theListJsonHasExactlyTheFieldsThePageReadsAndNoPath() throws Exception {
        Rig r = new Rig();
        kept(r, "reels.json.bad-" + S1, "1234567");
        kept(r, "restore-staging/reels.json", "abc");
        String json = KeptFiles.listJson(r.dir, UTC);
        assertFalse("no path: " + json, json.contains(r.dir.getPath()) || json.contains("restore-staging") || json.contains("backup-check"));
        JSONArray items = new JSONObject(json).getJSONArray("items");
        assertEquals(2, items.length());
        JSONObject one = items.getJSONObject(0);
        Set<String> keys = new HashSet<>();
        for (java.util.Iterator<String> it = one.keys(); it.hasNext(); ) keys.add(it.next());
        assertEquals(new HashSet<>(Arrays.asList("name", "kind", "library", "size", "at", "files")), keys);
        assertEquals("bad", one.getString("kind"));
        assertEquals("reels", one.getString("library"));
        assertEquals(7, one.getLong("size"));
        assertEquals("temp", items.getJSONObject(1).getString("kind"));
        assertEquals(KeptFiles.TEMP_NAME, items.getJSONObject(1).getString("name"));
    }

    @Test
    public void aLinkAFolderAndAnythingThatIsNotARegularFileIsNotListedOrFoundWhateverItIsCalled() throws Exception {
        File dir = tmp.newFolder();
        File precious = tmp.newFile("precious.json");
        put(precious, "my only copy");
        link(new File(dir, "reels.json.bad-" + S1), precious);
        File realDir = tmp.newFolder("real");
        link(new File(dir, "shots.json.bad-" + S2), realDir);
        assertTrue(new File(dir, "reels.json.before-restore-" + S3).mkdir());
        put(new File(dir, "reels.json.before-restore-" + S3 + "/inner.txt"), "inside a folder");
        assertTrue(KeptFiles.list(dir, UTC).isEmpty());
        for (String n : new String[]{"reels.json.bad-" + S1, "shots.json.bad-" + S2, "reels.json.before-restore-" + S3}) assertNull(n, KeptFiles.find(dir, n, UTC));
    }

    @Test
    public void findLooksTheFileUpAgainAndOnlyDirectlyInTheFolder() throws Exception {
        Rig r = new Rig();
        File f = kept(r, "reels.json.bad-" + S1, "hello");
        KeptFiles.Item it = KeptFiles.find(r.dir, f.getName(), UTC);
        assertNotNull(it);
        assertEquals(5, it.size);
        assertEquals(f.lastModified(), it.modified);
        assertTrue(f.delete());
        assertNull("gone: not found", KeptFiles.find(r.dir, f.getName(), UTC));
        // a kept-looking file in another folder is not found by a name that reaches it
        File sub = new File(r.dir, "sub");
        put(new File(sub, "reels.json.bad-" + S1), "elsewhere");
        for (String n : new String[]{"sub/reels.json.bad-" + S1, "../reels.json.bad-" + S1, "./reels.json.bad-" + S1, r.dir.getPath() + "/reels.json.bad-" + S1, "reels.json", "reels.json.bak", "../x"}) {
            assertNull(n, KeptFiles.find(r.dir, n, UTC));
        }
        assertNull(KeptFiles.find(r.dir, null, UTC));
    }

    @Test
    public void theTemporaryRowCountsOnlyPlainFilesDirectlyInTheTwoFolders() throws Exception {
        Rig r = new Rig();
        assertTrue(KeptFiles.list(r.dir, UTC).isEmpty());
        new File(r.dir, "restore-staging").mkdirs();
        new File(r.dir, "backup-check").mkdirs();
        assertTrue("empty folders are no row", KeptFiles.list(r.dir, UTC).isEmpty());
        kept(r, "restore-staging/reels.json", "12345");
        kept(r, "restore-staging/reels.json.part", "123");
        kept(r, "restore-staging/manifest.json", "1");
        kept(r, "backup-check/shots.json", "12");
        kept(r, "restore-staging/deeper/other.txt", "not counted: a sub-folder");
        File outside = tmp.newFile("outside.txt");
        put(outside, "a link is not counted");
        link(new File(r.dir, "backup-check/link.txt"), outside);
        kept(r, "backup-work/reels.json", "backup-work is not one of the two folders");
        List<KeptFiles.Item> l = KeptFiles.list(r.dir, UTC);
        assertEquals(1, l.size());
        assertEquals(KeptFiles.TEMP_NAME, l.get(0).name);
        assertEquals(11, l.get(0).size);
        assertEquals(4, l.get(0).files);
    }

    @Test
    public void aTemporaryFolderThatIsALinkIsNeverEntered() throws Exception {
        File dir = tmp.newFolder();
        File elsewhere = tmp.newFolder("elsewhere");
        put(new File(elsewhere, "reels.json"), "somebody else's folder");
        link(new File(dir, "restore-staging"), elsewhere);
        assertTrue(KeptFiles.list(dir, UTC).isEmpty());
        assertNull(KeptFiles.find(dir, KeptFiles.TEMP_NAME, UTC));
    }

    // ------------------------------------------------------------------ deleting: the confirmation token

    @Test
    public void askThenDeleteRemovesExactlyThatFileAndNothingElse() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.before-restore-" + S1;
        kept(r, "reels.json", V2);
        kept(r, "reels.json.bak", V1);
        kept(r, "shots.json", SHOTS1);
        String content = "the library before the restore";
        kept(r, name, content);
        kept(r, "reels.json.bad-" + S2, "another kept file");
        kept(r, "shots.json.bad-" + S3, "and another");
        kept(r, "reels.json.tmp", "temp of a write");
        kept(r, "restore-staging/reels.json", "staged");
        kept(r, "backup-check/shots.json", "checked");
        kept(r, "models/m.litertlm", "model");
        kept(r, "models/m.litertlm.part", "model part");
        kept(r, "shot-inbox/shot_1_1.jpg", "picture");
        kept(r, "video-inbox/video_1_1.mp4", "video");
        kept(r, "share-staging/copy-1.part", "half copied");
        kept(r, "verify-results.json", "{}");
        String before = fingerprint(r.dir);
        JSONObject a = r.ask(name);
        assertTrue(a.getBoolean("ok"));
        assertEquals("tok-1", a.getString("token"));
        assertEquals(content.length(), a.getJSONObject("item").getLong("size"));
        assertEquals("before_restore", a.getJSONObject("item").getString("kind"));
        assertEquals("asking changes nothing", before, fingerprint(r.dir));
        BackupNow.Outcome o = r.delete(name, "tok-1");
        assertTrue(o.text, o.ok);
        JSONObject res = new JSONObject(o.text);
        assertEquals(name, res.getString("deleted"));
        assertEquals(content.length(), res.getLong("bytes"));
        assertFalse(new File(r.dir, name).exists());
        assertEquals("everything else is byte for byte as it was", before.replace(name + "=" + content + "\n", ""), fingerprint(r.dir));
        assertFalse("the flag is free again", r.job.get());
    }

    @Test
    public void aDeleteWithoutTheRightTokenDeletesNothing() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1, other = "shots.json.bad-" + S2;
        kept(r, name, "keep me");
        kept(r, other, "keep me too");
        String before = fingerprint(r.dir);
        assertEquals("no ask was made at all", KeptFiles.NOT_CONFIRMED, r.delete(name, "tok-1").text);
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, null).text);
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, "").text);
        String token = r.token(name);
        assertEquals("a wrong token", KeptFiles.NOT_CONFIRMED, r.delete(name, token + "x").text);
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, "tok-0").text);
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, token.toUpperCase(Locale.ROOT)).text);
        assertEquals("a stray call with a wrong token does not use up the real one", before, fingerprint(r.dir));
        String forOther = r.token(other);  // a newer ask replaces the pending one
        assertEquals("the token of the first ask no longer works", KeptFiles.NOT_CONFIRMED, r.delete(name, token).text);
        assertEquals("a token is for one name: this one is for the other file, and is used up by the attempt", KeptFiles.NOT_CONFIRMED, r.delete(name, forOther).text);
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(other, forOther).text);
        assertEquals(before, fingerprint(r.dir));
    }

    @Test
    public void aTokenWorksOnceAndTheSameCallAgainDeletesNothing() throws Exception {
        Rig r = new Rig();
        String a = "reels.json.bad-" + S1, b = "reels.json.bad-" + S2;
        kept(r, a, "a");
        kept(r, b, "b");
        String token = r.token(a);
        assertTrue(r.delete(a, token).ok);
        assertFalse(new File(r.dir, a).exists());
        assertEquals("a token is single use", KeptFiles.NOT_CONFIRMED, r.delete(a, token).text);
        assertEquals("not for another file either", KeptFiles.NOT_CONFIRMED, r.delete(b, token).text);
        assertTrue(new File(r.dir, b).exists());
    }

    @Test
    public void aTokenExpiresAfterTwoMinutesAndIsUsedUpByTheLateCall() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        kept(r, name, "x");
        String t1 = r.token(name);
        r.clock[0] += KeptFiles.TOKEN_TTL_MS;
        assertTrue("still good at exactly the limit", r.delete(name, t1).ok);
        kept(r, name, "x");
        String t2 = r.token(name);
        r.clock[0] += KeptFiles.TOKEN_TTL_MS + 1;
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, t2).text);
        assertTrue(new File(r.dir, name).exists());
        assertEquals("and it is gone, not just late", KeptFiles.NOT_CONFIRMED, r.delete(name, t2).text);
        r.clock[0] -= 10 * KeptFiles.TOKEN_TTL_MS;  // a clock that went backwards is no reason to trust it
        String t3 = r.token(name);
        r.clock[0] -= 5;
        assertEquals(KeptFiles.NOT_CONFIRMED, r.delete(name, t3).text);
        assertTrue(new File(r.dir, name).exists());
    }

    @Test
    public void onlyNamesFromTheKeptListCanBeAskedOrDeletedAndNothingIsIssuedForTheOthers() throws Exception {
        Rig r = new Rig();
        kept(r, "reels.json", V2);
        kept(r, "reels.json.bak", V1);
        kept(r, "shots.json", SHOTS1);
        kept(r, "reels.json.tmp", "x");
        kept(r, "models/m.litertlm", "model");
        File outside = tmp.newFile("outside.txt");
        put(outside, "outside");
        String real = "reels.json.bad-" + S1;
        kept(r, real, "x");
        String good = r.token(real);  // a real token is pending, and must not open another file
        String before = fingerprint(r.dir);
        for (String n : new String[]{"reels.json", "shots.json", "reels.json.bak", "reels.json.tmp", "models/m.litertlm", "models", "../x", "../outside.txt", outside.getPath(),
                "", "reels.json.bad-", "reels.json.bak.", null}) {
            JSONObject a = r.ask(n);
            assertFalse(String.valueOf(n), a.getBoolean("ok"));
            assertEquals(KeptFiles.NOT_KEPT, a.getString("text"));
            BackupNow.Outcome o = r.delete(n, good);
            assertFalse(String.valueOf(n), o.ok);
            assertEquals(KeptFiles.NOT_KEPT, o.text);
        }
        assertEquals(before, fingerprint(r.dir));
        assertTrue("and the real token is still good", r.delete(real, good).ok);
        assertTrue(outside.exists());
    }

    // ------------------------------------------------------------------ deleting: when it is refused

    @Test
    public void aDeleteIsRefusedWhileWorkOrTheNightlyRunGoesAndTheTokenSurvivesForLater() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        kept(r, name, "x");
        String token = r.token(name);
        String before = fingerprint(r.dir);
        r.working.set(true);
        JSONObject a = r.ask(name);
        assertFalse(a.getBoolean("ok"));
        assertEquals(KeptFiles.WORK, a.getString("text"));
        BackupNow.Outcome o = r.delete(name, token);
        assertFalse(o.ok);
        assertEquals(KeptFiles.WORK, o.text);
        assertEquals(before, fingerprint(r.dir));
        assertFalse("the flag was taken and given back", r.job.get());
        r.working.set(false);
        assertTrue("when the work is over the same confirmation still deletes", r.delete(name, token).ok);
    }

    @Test
    public void aDeleteIsRefusedWhileABackupOrARestoreRunsAndThatJobsFlagIsNotReleased() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.before-restore-" + S1;
        kept(r, name, "x");
        String token = r.token(name);
        String before = fingerprint(r.dir);
        r.job.set(true);  // LocalBridge's flag: a backup or a restore holds it
        JSONObject a = r.ask(name);
        assertFalse(a.getBoolean("ok"));
        assertEquals(KeptFiles.BUSY, a.getString("text"));
        assertEquals(KeptFiles.BUSY, r.delete(name, token).text);
        assertEquals(before, fingerprint(r.dir));
        assertTrue("it is still that job's flag, not ours to release", r.job.get());
        r.job.set(false);
        assertTrue(r.delete(name, token).ok);
    }

    @Test
    public void theFlagIsHeldWhileTheChecksRunAndAlwaysReleasedAfterwards() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        kept(r, name, "x");
        boolean[] held = new boolean[1];
        r.workingNow = () -> {
            held[0] = r.job.get();
            return false;
        };
        assertTrue(r.delete(name, r.token(name)).ok);
        assertTrue("held while it works: no backup or restore can start meanwhile", held[0]);
        assertFalse(r.job.get());
        kept(r, name, "x");
        r.workingNow = () -> {
            throw new IllegalStateException("boom: /data/user/0/app.reelshelf/files secret");
        };
        BackupNow.Outcome o = r.delete(name, "tok-2");
        assertFalse(o.ok);
        assertEquals("an exception is a sentence of ours, not its text", KeptFiles.NOT_DELETED, o.text);
        assertFalse("released after an exception too", r.job.get());
        assertTrue(new File(r.dir, name).exists());
    }

    @Test
    public void aDeleteIsRefusedWhileTheLibraryIsUnreadableOrFromANewerReelShelfButListingAndSavingStayAllowed() throws Exception {
        for (String which : new String[]{"reels", "shots", "reels-newer", "shots-newer"}) {
            Rig r = new Rig();
            String name = "reels.json.before-restore-" + S1;
            kept(r, name, "the only copy of the old library");
            boolean newer = which.endsWith("newer");
            put(new File(r.dir, which.startsWith("reels") ? "reels.json" : "shots.json"), newer ? (which.startsWith("reels") ? NEWER : "{\"v\":99,\"seen\":{},\"reels\":{}}") : GARBAGE);
            r.readLibraries();
            assertTrue(which, which.startsWith("reels") ? r.reels.locked() : r.shots.locked());
            String token = r.confirm.put(KeptFiles.find(r.dir, name, UTC));  // as if it was asked before the library locked
            String before = fingerprint(r.dir);
            JSONObject a = r.ask(name);
            assertFalse(which, a.getBoolean("ok"));
            assertEquals(KeptFiles.LOCKED, a.getString("text"));
            assertEquals(which, KeptFiles.LOCKED, r.delete(name, token).text);
            assertEquals(which, before, fingerprint(r.dir));
            // listing and copying are not refused by anything
            List<KeptFiles.Item> l = KeptFiles.list(r.dir, UTC);
            assertEquals(1, l.size());
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            assertEquals(l.get(0).size, KeptFiles.copy(r.dir, l.get(0), out, KeptFiles.sha256()));
            assertEquals("the only copy of the old library", new String(out.toByteArray(), StandardCharsets.UTF_8));
        }
    }

    @Test
    public void askingAndDeletingNeverReadTheLibraryAndSoNeverRecoverOrSetAnythingAside() throws Exception {
        Rig r = new Rig(false);
        put(new File(r.dir, "reels.json"), GARBAGE);  // damaged, with a good backup: reading it would set it aside and restore the backup
        put(new File(r.dir, "reels.json.bak"), V1);
        put(new File(r.dir, "shots.json"), GARBAGE);
        put(new File(r.dir, "shots.json.bak"), SHOTS1);
        for (String name : new String[]{"reels.json.bad-" + S1, "shots.json.before-restore-" + S2, "reels.json.bak.bad-" + S3}) kept(r, name, "x");
        String before = fingerprint(r.dir);
        for (String name : new String[]{"reels.json.bad-" + S1, "shots.json.before-restore-" + S2, "reels.json.bak.bad-" + S3}) {
            String forced = r.confirm.put(KeptFiles.find(r.dir, name, UTC));  // as if it was asked: the delete must refuse by itself
            JSONObject a = r.ask(name);
            assertFalse(name, a.getBoolean("ok"));
            assertEquals(name, name.startsWith("shots") ? KeptFiles.NOT_LOADED_SHOTS : KeptFiles.NOT_LOADED_REELS, a.getString("text"));
            assertEquals(name, a.getString("text"), r.delete(name, forced).text);
        }
        assertEquals("not read, so not recovered, nothing set aside and nothing deleted", before, fingerprint(r.dir));
        assertFalse("and still not read", r.reels.loaded() || r.shots.loaded());
    }

    @Test
    public void aSetAsideFileOfAShotsListFromANewerReelShelfIsNotDeletedEvenIfScreenshotsWasNeverOpened() throws Exception {
        Rig r = new Rig(false);
        r.reels.read();  // the page read reels.json when it started; shots.json is read only when Screenshots is opened
        String name = "shots.json.before-restore-" + S1;
        kept(r, name, "the list before a restore");
        put(new File(r.dir, "shots.json"), "{\"v\":99,\"seen\":{},\"reels\":{}}");  // saved by a newer Reel Shelf after a downgrade
        String before = fingerprint(r.dir);
        String forced = r.confirm.put(KeptFiles.find(r.dir, name, UTC));
        assertEquals(KeptFiles.NOT_LOADED_SHOTS, r.ask(name).getString("text"));
        assertEquals(KeptFiles.NOT_LOADED_SHOTS, r.delete(name, forced).text);
        assertFalse("nothing read it to find out", r.shots.loaded());
        assertEquals(before, fingerprint(r.dir));
        r.shots.read();  // Screenshots is opened: the newer list locks it
        assertTrue(r.shots.locked());
        String again = r.confirm.put(KeptFiles.find(r.dir, name, UTC));
        assertEquals(KeptFiles.LOCKED, r.ask(name).getString("text"));
        assertEquals(KeptFiles.LOCKED, r.delete(name, again).text);
        assertEquals(before, fingerprint(r.dir));
    }

    @Test
    public void aKeptFileCanBeDeletedOnceItsOwnLibraryFileHasBeenReadAndIsFine() throws Exception {
        Rig r = new Rig(false);
        put(new File(r.dir, "shots.json"), SHOTS1);
        String shotsKept = "shots.json.bad-" + S1, reelsKept = "reels.json.bad-" + S2;
        kept(r, shotsKept, "a");
        kept(r, reelsKept, "b");
        assertEquals(KeptFiles.NOT_LOADED_SHOTS, r.ask(shotsKept).getString("text"));
        assertEquals(KeptFiles.NOT_LOADED_REELS, r.ask(reelsKept).getString("text"));
        r.shots.read();
        assertEquals(LibraryFile.State.OK, r.shots.state());
        assertTrue("it is the file's own library that counts", r.delete(shotsKept, r.token(shotsKept)).ok);
        assertFalse(new File(r.dir, shotsKept).exists());
        assertEquals("the other library was not read: its kept file is still refused", KeptFiles.NOT_LOADED_REELS, r.ask(reelsKept).getString("text"));
        assertTrue(new File(r.dir, reelsKept).exists());
        r.reels.read();  // no reels.json yet: a new library is fine
        assertTrue(r.delete(reelsKept, r.token(reelsKept)).ok);
    }

    @Test
    public void theTemporaryFilesAreNotAskedAboutTheLibraryFiles() throws Exception {
        Rig r = new Rig(false);
        kept(r, "restore-staging/reels.json", "staged");
        assertTrue(r.delete(KeptFiles.TEMP_NAME, r.token(KeptFiles.TEMP_NAME)).ok);
        assertFalse(r.reels.loaded() || r.shots.loaded());
    }

    @Test
    public void theDeletePathNeverCallsAnythingThatReadsOrChangesALibrary() throws Exception {
        String src = get(repoFile("android/app-shell/app/src/main/java/app/reelshelf/KeptFiles.java")).replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("//[^\\n]*", "");  // the code, not the comments
        for (String forbidden : new String[]{".read()", ".load()", "savedByNewer", "ensureRead", "replaceWith", "startNew", "dropBackup", "snapshotTo"}) {
            assertFalse("KeptFiles must not call " + forbidden, src.contains(forbidden));
        }
        assertTrue("it asks only what the library already knows", src.contains(".loaded()") && src.contains(".locked()"));
    }

    @Test
    public void theTemporaryFilesAreNotDeletedWhileABackupWaitsToBeRestoredFromThem() throws Exception {
        Rig r = new Rig();
        File reelsSrc = tmp.newFile();
        put(reelsSrc, V1);
        ByteArrayOutputStream zip = new ByteArrayOutputStream();
        LibraryBackup.write(zip, reelsSrc, 1, null, 1, new JSONObject().put("reels", 1).put("titles", 0).put("screenshots", 0), "1.3.25", 32, 1_700_000_000_000L);
        LibraryBackup.Checked c = LibraryBackup.check(new ByteArrayInputStream(zip.toByteArray()), new File(r.dir, "restore-staging"), 50 * MB);
        assertTrue(c.ok());
        r.stage.put(c);
        assertTrue(new File(r.dir, "restore-staging/reels.json").isFile());
        kept(r, "reels.json.bad-" + S1, "a kept file is not wanted by that restore");
        JSONObject a = r.ask(KeptFiles.TEMP_NAME);
        assertFalse(a.getBoolean("ok"));
        assertEquals(KeptFiles.WAITING, a.getString("text"));
        String token = r.confirm.put(KeptFiles.find(r.dir, KeptFiles.TEMP_NAME, UTC));
        assertEquals(KeptFiles.WAITING, r.delete(KeptFiles.TEMP_NAME, token).text);
        assertTrue("the staged files are still there", new File(r.dir, "restore-staging/reels.json").isFile());
        assertTrue("a kept file can still be deleted", r.delete("reels.json.bad-" + S1, r.token("reels.json.bad-" + S1)).ok);
        r.stage.clear();  // cancelled: the files are only leftovers now
        assertTrue(r.delete(KeptFiles.TEMP_NAME, r.token(KeptFiles.TEMP_NAME)).ok);
        assertFalse(new File(r.dir, "restore-staging/reels.json").exists());
        assertTrue("the folder itself stays", new File(r.dir, "restore-staging").isDirectory());
    }

    // ------------------------------------------------------------------ deleting: a file that changed, a link, a folder

    @Test
    public void aFileThatChangedAfterTheConfirmScreenIsNotDeleted() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        File f = kept(r, name, "as shown");
        String token = r.token(name);
        put(f, "a longer content than the one shown");
        assertEquals("another size", KeptFiles.CHANGED, r.delete(name, token).text);
        assertTrue(f.exists());
        put(f, "as shown");
        String t2 = r.token(name);
        assertTrue(f.setLastModified(f.lastModified() + 5000));
        assertEquals("the same size, another time", KeptFiles.CHANGED, r.delete(name, t2).text);
        assertEquals("as shown", get(f));
        assertFalse(r.job.get());
    }

    @Test
    public void aFileThatIsGoneByTheTimeOfTheDeleteIsReportedAndNothingElseGoes() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        File f = kept(r, name, "x");
        kept(r, "reels.json.bad-" + S2, "other");
        String token = r.token(name);
        assertTrue(f.delete());
        String before = fingerprint(r.dir);
        assertEquals(KeptFiles.GONE, r.delete(name, token).text);
        assertEquals(before, fingerprint(r.dir));
        assertEquals("asking for a file that is gone says so", KeptFiles.GONE, r.ask(name).getString("text"));
    }

    @Test
    public void aDeleteNeverFollowsOrRemovesALinkOrAFolderEvenWithAToken() throws Exception {
        Rig r = new Rig();
        File precious = tmp.newFile("precious.json");
        put(precious, "my only copy");
        String linkName = "reels.json.bad-" + S1, dirName = "shots.json.before-restore-" + S2, swapped = "reels.json.before-restore-" + S3;
        link(new File(r.dir, linkName), precious);
        assertTrue(new File(r.dir, dirName).mkdir());
        put(new File(r.dir, dirName + "/inside.txt"), "inside");
        File real = kept(r, swapped, "a real file when it was shown");
        String swappedToken = r.token(swapped);
        // the real file is swapped for a link to a precious file after the confirm screen
        assertTrue(real.delete());
        link(real, precious);
        String before = fingerprint(r.dir);
        assertEquals(swapped, KeptFiles.GONE, r.delete(swapped, swappedToken).text);
        for (String n : new String[]{linkName, dirName}) {
            String forced = r.confirm.put(new KeptFiles.Item(n, KeptFiles.kindOf(n), "x", 12, 1, precious.lastModified(), 1));  // a token as if the list had shown it
            assertEquals(n, KeptFiles.GONE, r.delete(n, forced).text);
            assertFalse(r.ask(n).getBoolean("ok"));
        }
        assertEquals(before, fingerprint(r.dir));
        assertEquals("my only copy", get(precious));
    }

    @Test
    public void deletingTheTemporaryFilesRemovesOnlyPlainFilesInTheTwoFolders() throws Exception {
        Rig r = new Rig();
        kept(r, "restore-staging/reels.json", "12345");
        kept(r, "restore-staging/reels.json.part", "123");
        kept(r, "restore-staging/manifest.json", "1");
        kept(r, "backup-check/shots.json", "12");
        kept(r, "restore-staging/deeper/other.txt", "a sub-folder is not ours to empty");
        File outside = tmp.newFile("outside.txt");
        put(outside, "a link target");
        link(new File(r.dir, "backup-check/link.txt"), outside);
        kept(r, "backup-work/reels.json", "not one of the two folders");
        kept(r, "reels.json", V2);
        kept(r, "reels.json.bak", V1);
        kept(r, "reels.json.bad-" + S1, "a kept file");
        kept(r, "models/m.litertlm", "model");
        String token = r.token(KeptFiles.TEMP_NAME);
        BackupNow.Outcome o = r.delete(KeptFiles.TEMP_NAME, token);
        assertTrue(o.text, o.ok);
        assertEquals(11, new JSONObject(o.text).getLong("bytes"));
        for (String gone : new String[]{"restore-staging/reels.json", "restore-staging/reels.json.part", "restore-staging/manifest.json", "backup-check/shots.json"}) {
            assertFalse(gone, new File(r.dir, gone).exists());
        }
        assertTrue(new File(r.dir, "restore-staging").isDirectory() && new File(r.dir, "backup-check").isDirectory());
        assertEquals("a sub-folder and its file", "a sub-folder is not ours to empty", get(new File(r.dir, "restore-staging/deeper/other.txt")));
        assertTrue("the link is not ours", Files.isSymbolicLink(new File(r.dir, "backup-check/link.txt").toPath()));
        assertEquals("a link target", get(outside));
        assertEquals(V2, get(new File(r.dir, "reels.json")));
        assertEquals(V1, get(new File(r.dir, "reels.json.bak")));
        assertEquals("a kept file", get(new File(r.dir, "reels.json.bad-" + S1)));
        assertEquals("not one of the two folders", get(new File(r.dir, "backup-work/reels.json")));
        assertEquals("model", get(new File(r.dir, "models/m.litertlm")));
        assertTrue("nothing is listed any more", KeptFiles.list(r.dir, UTC).stream().noneMatch(i -> i.kind == KeptFiles.Kind.TEMP));
    }

    @Test
    public void temporaryFilesThatChangedAfterTheConfirmScreenAreNotDeleted() throws Exception {
        Rig r = new Rig();
        kept(r, "restore-staging/reels.json", "12345");
        String token = r.token(KeptFiles.TEMP_NAME);
        kept(r, "restore-staging/manifest.json", "a file that was not there when the user was shown the list");
        assertEquals(KeptFiles.CHANGED, r.delete(KeptFiles.TEMP_NAME, token).text);
        assertTrue(new File(r.dir, "restore-staging/reels.json").exists() && new File(r.dir, "restore-staging/manifest.json").exists());
    }

    @Test
    public void aTemporaryDeleteThatCannotRemoveAFileSaysSoAndGoesOnWithTheRest() throws Exception {
        Rig r = new Rig();
        kept(r, "restore-staging/a.part", "1");
        File locked = kept(r, "backup-check/b.part", "2");
        Assume.assumeTrue(locked.getParentFile().setWritable(false));  // a folder nobody may delete from (not on every file system, and not as root)
        try {
            Assume.assumeFalse("running as a user who may delete anyway", Files.isWritable(locked.getParentFile().toPath()));
            String token = r.token(KeptFiles.TEMP_NAME);
            BackupNow.Outcome o = r.delete(KeptFiles.TEMP_NAME, token);
            assertFalse(o.ok);
            assertEquals(KeptFiles.TEMP_PARTLY, o.text);
            assertFalse(new File(r.dir, "restore-staging/a.part").exists());
            assertTrue(locked.exists());
        } finally {
            locked.getParentFile().setWritable(true);
        }
    }

    // ------------------------------------------------------------------ the sentences

    @Test
    public void everySentenceIsPlainEndsWithAFullStopAndHasNoPathOrExceptionText() throws Exception {
        int n = 0;
        for (Field f : KeptFiles.class.getDeclaredFields()) {
            if (!Modifier.isStatic(f.getModifiers()) || f.getType() != String.class || !Modifier.isFinal(f.getModifiers())) continue;
            f.setAccessible(true);
            String s = (String) f.get(null);
            if (f.getName().equals("TEMP_NAME") || f.getName().equals("STAMP_FORMAT") || f.getName().equals("EMPTY") || f.getName().equals("TAIL")) continue;
            n++;
            assertTrue(f.getName() + ": " + s, s.endsWith("."));
            assertFalse(f.getName(), s.contains("/") || s.contains("\\") || s.contains("Exception") || s.contains("java.") || s.contains("android"));
        }
        assertTrue("the sentences were found: " + n, n >= 15);
        assertTrue(KeptFiles.notEnoughSpace(250 * MB, 150 * MB).endsWith("The kept file was not changed."));
        assertEquals("There is not enough free space on the phone to save this file: about 250 MB are needed and 150 MB are free. Free up some space and try again. The kept file was not changed.",
                KeptFiles.notEnoughSpace(250 * MB, 150 * MB));
    }

    @Test
    public void noAnswerEverHasThePathOfTheFolder() throws Exception {
        Rig r = new Rig();
        String name = "reels.json.bad-" + S1;
        kept(r, name, "x");
        List<String> answers = new ArrayList<>();
        answers.add(KeptFiles.listJson(r.dir, UTC));
        answers.add(KeptFiles.ask(r.env(), name));
        answers.add(KeptFiles.ask(r.env(), "reels.json"));
        answers.add(KeptFiles.ask(r.env(), "../" + r.dir.getName()));
        answers.add(r.delete(name, "nope").text);
        answers.add(r.delete(name, r.token(name)).text);
        answers.add(r.delete(name, "again").text);
        answers.add(KeptFiles.listJson(new File(r.dir, "missing"), UTC));
        for (String a : answers) assertFalse(a, a.contains(r.dir.getPath()) || a.contains(r.dir.getName()));
    }

    // ------------------------------------------------------------------ saving to Downloads (the pure part)

    @Test
    public void aCopyIsByteForByteAndTheReadBackAcceptsItAndRefusesAnythingElse() throws Exception {
        Rig r = new Rig();
        byte[] data = new byte[300_000];
        new java.util.Random(7).nextBytes(data);
        File f = new File(r.dir, "reels.json.bad-" + S1);
        Files.write(f.toPath(), data);
        KeptFiles.Item it = KeptFiles.find(r.dir, f.getName(), UTC);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        MessageDigest md = KeptFiles.sha256();
        assertEquals(data.length, KeptFiles.copy(r.dir, it, out, md));
        assertArrayEquals(data, out.toByteArray());
        byte[] sha = md.digest();
        KeptFiles.verify(new ByteArrayInputStream(out.toByteArray()), sha, data.length);
        byte[] flipped = out.toByteArray();
        flipped[1234] ^= 1;
        for (byte[] bad : new byte[][]{flipped, Arrays.copyOf(data, data.length - 1), Arrays.copyOf(data, data.length + 1), new byte[0]}) {
            try {
                KeptFiles.verify(new ByteArrayInputStream(bad), sha, data.length);
                fail("a copy that is not the file must not pass the read-back");
            } catch (BackupNow.Failure e) {
                assertEquals(KeptFiles.READ_BACK, e.getMessage());
            }
        }
        try {
            KeptFiles.verify(new ByteArrayInputStream(data), null, data.length);
            fail("no digest, no proof");
        } catch (BackupNow.Failure expected) {
            // refused
        }
        assertEquals("the kept file is untouched", data.length, f.length());
    }

    @Test
    public void anEmptyKeptFileCopiesAndProvesAsEmpty() throws Exception {
        Rig r = new Rig();
        kept(r, "reels.json.bad-" + S1, "");
        KeptFiles.Item it = KeptFiles.find(r.dir, "reels.json.bad-" + S1, UTC);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        MessageDigest md = KeptFiles.sha256();
        assertEquals(0, KeptFiles.copy(r.dir, it, out, md));
        KeptFiles.verify(new ByteArrayInputStream(new byte[0]), md.digest(), 0);
    }

    @Test
    public void aCopyOfAFileThatChangedAfterItWasLookedUpIsRefused() throws Exception {
        Rig r = new Rig();
        File f = kept(r, "reels.json.bad-" + S1, "12345");
        KeptFiles.Item it = KeptFiles.find(r.dir, f.getName(), UTC);
        put(f, "1234567890");
        try {
            KeptFiles.copy(r.dir, it, new ByteArrayOutputStream(), KeptFiles.sha256());
            fail("the file is not the one that was looked up");
        } catch (BackupNow.Failure e) {
            assertEquals(KeptFiles.CHANGED, e.getMessage());
        }
    }

    @Test
    public void theTemporaryFilesAreNeverCopiedAndALinkIsNeverFollowedToCopyIt() throws Exception {
        Rig r = new Rig();
        try {
            KeptFiles.copy(r.dir, item(KeptFiles.TEMP_NAME), new ByteArrayOutputStream(), KeptFiles.sha256());
            fail("temporary files are not saved");
        } catch (IOException expected) {
            // refused
        }
        File precious = tmp.newFile("precious.json");
        put(precious, "private");
        link(new File(r.dir, "reels.json.bad-" + S1), precious);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try {
            KeptFiles.copy(r.dir, new KeptFiles.Item("reels.json.bad-" + S1, KeptFiles.Kind.BAD, "reels", 7, 1, 1, 1), out, KeptFiles.sha256());
            fail("a link is not opened");
        } catch (IOException expected) {
            // refused
        }
        assertEquals(0, out.size());
    }

    @Test
    public void theSpaceNeededIsTheFilePlusTheReserveAndNeverWrapsRound() {
        assertEquals(150 * MB, KeptFiles.neededBytes(50 * MB, 100 * MB));
        assertEquals(100 * MB, KeptFiles.neededBytes(0, 100 * MB));
        assertEquals(100 * MB, KeptFiles.neededBytes(-5, 100 * MB));
        assertEquals(Long.MAX_VALUE, KeptFiles.neededBytes(Long.MAX_VALUE, 100 * MB));
        assertEquals(Long.MAX_VALUE, KeptFiles.neededBytes(Long.MAX_VALUE - 5, 100 * MB));
    }

    @Test
    public void aSaveFailureIsOneOfOurSentencesNeverTheExceptionText() {
        assertEquals(KeptFiles.READ_BACK, KeptFiles.sentenceFor(new BackupNow.Failure(KeptFiles.READ_BACK)));
        assertEquals(KeptFiles.CHANGED, KeptFiles.sentenceFor(new IOException("wrapped", new BackupNow.Failure(KeptFiles.CHANGED))));
        assertEquals(KeptFiles.DISK_FULL, KeptFiles.sentenceFor(new IOException("write failed: ENOSPC (No space left on device)")));
        assertEquals(KeptFiles.DISK_FULL, KeptFiles.sentenceFor(new IOException("x", new IOException("No space left on device"))));
        String secret = "open failed: ENOENT /data/user/0/app.reelshelf/files/reels.json.bad-" + S1 + " (my private note)";
        assertEquals(KeptFiles.GENERIC_SAVE, KeptFiles.sentenceFor(new IOException(secret)));
        assertEquals(KeptFiles.GENERIC_SAVE, KeptFiles.sentenceFor(new RuntimeException(secret)));
        assertEquals(KeptFiles.GENERIC_SAVE, KeptFiles.sentenceFor(null));
    }

    @Test
    public void theAnswerToAGoodSaveNamesTheFileAndNeverAFullPath() throws Exception {
        BackupNow.Outcome o = KeptFiles.saved("reels-before-restore-" + S1 + ".txt", BackupNow.where(false, "app.reelshelf", "reels-before-restore-" + S1 + ".txt"), 1234, false);
        assertTrue(o.ok);
        JSONObject j = new JSONObject(o.text);
        assertEquals("Downloads/ReelShelf/reels-before-restore-" + S1 + ".txt", j.getString("where"));
        assertEquals(1234, j.getLong("bytes"));
        assertFalse(j.getBoolean("uninstall_warning"));
        assertTrue(new JSONObject(KeptFiles.saved("a.txt", BackupNow.where(true, "app.reelshelf", "a.txt"), 1, true).text).getBoolean("uninstall_warning"));
    }

    // ------------------------------------------------------------------ the temp sweep never touches any of this

    private static final String[] KEPT_SAMPLES = {
            "reels.json.bad-" + S1, "reels.json.bad-" + S1 + "-2", "shots.json.bad-" + S2, "shots.json.bad-" + S2 + "-17",
            "reels.json.bak.bad-" + S1, "shots.json.bak.bad-" + S3 + "-2", "reels.json.before-restore-" + S1, "reels.json.before-restore-" + S1 + "-2",
            "shots.json.before-restore-" + S3, KeptFiles.TEMP_NAME, "restore-staging", "backup-check",
    };

    @Test
    public void noKeptNameIsOnTheTempSweepsAllowlistInAnyPlace() {
        for (TempSweep.Folder folder : TempSweep.Folder.values()) {
            for (String n : KEPT_SAMPLES) {
                TempSweep.Entry e = new TempSweep.Entry(folder, n, true, false, 0, 7);  // ten times older than anything, a regular file
                TempSweep.Verdict v = TempSweep.decide(e, 1_000_000_000_000L, new TempSweep.Busy(false, 0, true, true));
                assertFalse(n + " in " + folder, v.delete());
                assertEquals(n + " in " + folder, TempSweep.Reason.UNKNOWN_NAME, v.reason);
            }
        }
        for (TempSweep.Rule rule : TempSweep.RULES) for (String n : KEPT_SAMPLES) assertFalse(n, rule.name.matcher(n).matches());
    }

    @Test
    public void theRealSweepLeavesEveryKeptFileAndTheTemporaryFilesAloneEvenWhenVeryOld() throws Exception {
        File files = tmp.newFolder("files"), cache = tmp.newFolder("cache");
        LibraryFile reels = LibraryFile.reels(files), shots = LibraryFile.shots(files);
        put(reels.main, V1);
        put(shots.main, SHOTS1);
        reels.read();
        shots.read();
        long tenYears = System.currentTimeMillis() - 10L * 365 * 24 * 3600 * 1000;
        List<File> keep = new ArrayList<>();
        for (String n : KEPT_SAMPLES) {
            if (n.equals(KeptFiles.TEMP_NAME) || n.equals("restore-staging") || n.equals("backup-check")) continue;
            keep.add(new File(files, n));
            put(keep.get(keep.size() - 1), "kept " + n);
        }
        for (String n : new String[]{"restore-staging/reels.json", "restore-staging/reels.json.part", "restore-staging/manifest.json", "backup-check/shots.json"}) {
            keep.add(new File(files, n));
            put(keep.get(keep.size() - 1), "temporary " + n);
        }
        File tmpFile = new File(files, "reels.json.tmp");  // the one thing the sweep does delete: it proves the sweep ran
        put(tmpFile, "cut-off write");
        for (File f : keep) assertTrue(f.setLastModified(tenYears));
        assertTrue(tmpFile.setLastModified(tenYears));
        String before = KeptFiles.listJson(files, UTC);
        TempSweeper.Result res = TempSweeper.sweep(files, cache, System.currentTimeMillis(), () -> 0);
        assertFalse("the sweep did run: it removed the old temp file of a write", tmpFile.exists());
        assertEquals(1, res.files);
        for (File f : keep) assertTrue(f.getPath(), f.isFile());
        assertEquals("the list is the same after the sweep", before, KeptFiles.listJson(files, UTC));
    }
}
