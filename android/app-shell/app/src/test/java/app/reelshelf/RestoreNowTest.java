package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/** Restore from a backup, without a phone: the limits, the preview, the token, and the install on real files (backup, check, install). */
public class RestoreNowTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final long MB = 1024 * 1024;
    private static final String CURRENT_REELS = "{\"schema_version\":1,\"reels\":[{\"code\":\"CURRENT1\"},{\"code\":\"CURRENT2\"}],\"media\":[{\"title\":\"Heat\"}],\"inbox\":[]}";
    private static final String CURRENT_SHOTS = "{\"v\":1,\"seen\":{\"now\":1},\"reels\":{}}";
    private static final String BACKED_REELS = "{\"schema_version\":1,\"reels\":[{\"code\":\"BACKED01\",\"note\":\"café\"}],\"media\":[{\"title\":\"Dune\"},{\"title\":\"Alien\"}],\"inbox\":[]}";
    private static final String BACKED_SHOTS = "{\"v\":1,\"seen\":{\"then\":1},\"reels\":{}}";
    private static final String NEWER_REELS = "{\"schema_version\":99,\"reels\":[],\"fieldOfTheFuture\":1}";
    private static final String NEWER_SHOTS = "{\"v\":99,\"seen\":{},\"reels\":{}}";

    private static byte[] b(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    private static void put(File f, String s) throws IOException {
        Files.write(f.toPath(), b(s));
    }

    private static byte[] bytes(File f) throws IOException {
        return Files.readAllBytes(f.toPath());
    }

    private static String get(File f) throws IOException {
        return new String(bytes(f), StandardCharsets.UTF_8);
    }

    /** A "phone" folder with a library in it (shots may be null: no screenshot list). */
    private File phone(String reels, String shots) throws IOException {
        File dir = tmp.newFolder();
        if (reels != null) put(new File(dir, "reels.json"), reels);
        if (shots != null) put(new File(dir, "shots.json"), shots);
        return dir;
    }

    /** A backup ZIP of these library texts, made the way the app makes one (LibraryBackup.write). */
    private byte[] backupOf(String reels, String shots) throws Exception {
        File r = tmp.newFile(), s = tmp.newFile();
        put(r, reels);
        if (shots != null) put(s, shots);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        LibraryBackup.write(out, r, 1, shots == null ? null : s, 1, new JSONObject().put("reels", 1).put("titles", 2).put("screenshots", 3), "1.3.22", 29, 1_700_000_000_000L);
        return out.toByteArray();
    }

    private static LibraryBackup.Checked check(byte[] zip, File staging) {
        return LibraryBackup.check(new ByteArrayInputStream(zip), staging, 50 * MB);
    }

    private static String[] names(File dir) {
        String[] n = dir.list();
        Arrays.sort(n);
        return n;
    }

    /** Every file of dir with its bytes: to show that nothing at all changed. */
    private static String fingerprint(File dir) throws IOException {
        StringBuilder s = new StringBuilder();
        for (String n : names(dir)) {
            File f = new File(dir, n);
            if (f.isFile()) s.append(n).append('=').append(get(f)).append('\n');
        }
        return s.toString();
    }

    private static File[] beforeRestore(File dir, String name) {
        File[] a = dir.listFiles((d, n) -> n.startsWith(name + ".before-restore-"));
        Arrays.sort(a);
        return a;
    }

    private static JSONObject json(BackupNow.Outcome o) throws Exception {
        assertTrue(o.text, o.ok);
        return new JSONObject(o.text);
    }

    // ------------------------------------------------------------------ the limit

    @Test
    public void aBackupMayUnpackToTheFreeSpaceLessTheReserveAndTheLibraryButNeverMoreThanOneGigabyte() {
        assertEquals(300 * MB, RestoreNow.maxBytes(500 * MB, 100 * MB, 100 * MB));
        assertEquals("never more than 1 GB, however much is free", 1024 * MB, RestoreNow.maxBytes(50_000 * MB, 100 * MB, 5 * MB));
        assertEquals(1024 * MB, RestoreNow.maxBytes(1124 * MB + 7, 100 * MB, 0));
        assertEquals(MB, RestoreNow.maxBytes(101 * MB, 100 * MB, 0));
    }

    @Test
    public void noRoomIsZeroOrLessAndNeverWrapsRoundToRoom() {
        assertTrue(RestoreNow.maxBytes(100 * MB, 100 * MB, 0) <= 0);
        assertTrue(RestoreNow.maxBytes(50 * MB, 100 * MB, 0) <= 0);
        assertTrue("the library itself counts: its set-aside copy needs the room", RestoreNow.maxBytes(150 * MB, 100 * MB, 60 * MB) <= 0);
        assertTrue(RestoreNow.maxBytes(-5, 100 * MB, 0) <= 0);
        assertTrue(RestoreNow.maxBytes(Long.MIN_VALUE, Long.MAX_VALUE, Long.MAX_VALUE) <= 0);
        assertTrue(RestoreNow.maxBytes(Long.MAX_VALUE, Long.MAX_VALUE, Long.MAX_VALUE) <= 0);
        assertTrue(RestoreNow.maxBytes(Long.MAX_VALUE, 0, 0) == RestoreNow.MAX_UNPACKED_BYTES);
    }

    @Test
    public void theNoRoomSentenceHasRealNumbersAndSaysNothingWasChanged() {
        String s = RestoreNow.notEnoughSpace(40 * MB, 100 * MB, 10 * MB + 1);
        assertTrue(s, s.contains("more than 111 MB") && s.contains("only 40 MB are free") && s.endsWith("Nothing was changed."));
        assertTrue(RestoreNow.notEnoughSpace(-1, -1, -1).contains("only 0 MB are free"));
    }

    // ------------------------------------------------------------------ the sentences

    @Test
    public void everyRefusalSentenceSaysNothingWasChangedAndHasNoPathOrMarkup() throws Exception {
        for (Field f : RestoreNow.class.getDeclaredFields()) {
            if (f.getType() != String.class || f.getName().startsWith("SHOTS_")) continue;
            f.setAccessible(true);
            String s = (String) f.get(null);
            assertTrue(f.getName() + ": " + s, s.contains("not changed") || s.contains("Nothing was changed") || s.contains("was not changed"));
            assertFalse(f.getName(), s.contains("/") || s.contains("<") || s.contains("\\"));
        }
    }

    @Test
    public void aFullDiskAndNoMemoryAreToldApartAndAnExceptionsTextIsNeverPassedOn() {
        String secret = "open failed: ENOENT /data/user/0/app.reelshelf/files/restore-staging/reels.json (my private note)";
        assertEquals(RestoreNow.GENERIC, RestoreNow.sentenceFor(new IOException(secret)));
        assertEquals(RestoreNow.DISK_FULL, RestoreNow.sentenceFor(new IOException("write failed: ENOSPC (No space left on device)")));
        assertEquals(RestoreNow.DISK_FULL, RestoreNow.sentenceFor(new RuntimeException("wrapped", new IOException("No space left on device"))));
        assertEquals(RestoreNow.OUT_OF_MEMORY, RestoreNow.sentenceFor(new OutOfMemoryError("Java heap space")));
        assertEquals(RestoreNow.OUT_OF_MEMORY, RestoreNow.sentenceFor(new IOException("x", new OutOfMemoryError())));
        assertEquals(RestoreNow.GENERIC, RestoreNow.sentenceFor(null));
        assertFalse(RestoreNow.sentenceFor(new IOException(secret)).contains("private"));
    }

    // ------------------------------------------------------------------ the preview

    @Test
    public void thePreviewHasWhatTheConfirmScreenNeedsAndOnlyThat() throws Exception {
        File dir = tmp.newFolder();
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        assertTrue(c.message, c.ok());
        JSONObject p = json(RestoreNow.preview("tok-1", c, 1234));
        assertEquals("tok-1", p.getString("token"));
        assertEquals("2023-11-14T22:13:20Z", p.getString("created_at"));
        assertEquals("1.3.22", p.getString("app_version"));
        assertEquals(1, p.getLong("reels"));
        assertEquals(2, p.getLong("titles"));
        assertEquals(3, p.getLong("screenshots"));
        assertTrue(p.getBoolean("has_shots"));
        assertEquals(1234, p.getLong("bytes"));
        assertEquals(new java.util.TreeSet<>(Arrays.asList("token", "created_at", "app_version", "reels", "titles", "screenshots", "has_shots", "bytes")),
                new java.util.TreeSet<>(p.keySet()));
        LibraryBackup.Checked noShots = check(backupOf(BACKED_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        assertFalse(json(RestoreNow.preview("t", noShots, 1)).getBoolean("has_shots"));
    }

    @Test
    public void aBackupsOwnCountsAreOnlyEverNumbersInRangeAndTextIsShortened() throws Exception {
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        JSONObject lying = new JSONObject().put("reels", "<b>9</b>").put("titles", -4).put("screenshots", 1e18);
        LibraryBackup.Checked odd = lyingAbout(c, lying, "x".repeat(500));
        JSONObject p = json(RestoreNow.preview("t", odd, -5));
        assertEquals(0, p.getLong("reels"));
        assertEquals(0, p.getLong("titles"));
        assertEquals(BackupNow.MAX_COUNT, p.getLong("screenshots"));
        assertEquals(0, p.getLong("bytes"));
        assertEquals(64, p.getString("created_at").length());
        assertEquals(64, p.getString("app_version").length());
    }

    /** A Checked with other words in it (the manifest's counts, date and version are only labels). */
    @SuppressWarnings("unchecked")
    private static LibraryBackup.Checked lyingAbout(LibraryBackup.Checked c, JSONObject counts, String text) throws Exception {
        java.lang.reflect.Constructor<LibraryBackup.Checked> k = (java.lang.reflect.Constructor<LibraryBackup.Checked>) LibraryBackup.Checked.class.getDeclaredConstructors()[0];
        k.setAccessible(true);
        return k.newInstance(LibraryBackup.Code.OK, "", c.reels, c.shots, text, text, 1L, counts);
    }

    // ------------------------------------------------------------------ the token

    @Test
    public void aTokenWorksOnceAndOnlyForTheFileItWasGivenFor() throws Exception {
        AtomicInteger n = new AtomicInteger();
        RestoreNow.Stage stage = new RestoreNow.Stage(() -> "token-" + n.incrementAndGet());
        LibraryBackup.Checked one = check(backupOf(BACKED_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        LibraryBackup.Checked two = check(backupOf(CURRENT_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        assertFalse(stage.staged());
        assertNull("nothing is staged yet", stage.take("token-1"));
        String t1 = stage.put(one);
        assertEquals("token-1", t1);
        assertTrue(stage.matches(t1));
        assertNull("a token that was never given", stage.take("token-0"));
        assertNull(stage.take(null));
        assertNull(stage.take(""));
        assertTrue("a wrong guess does not use the token up", stage.matches(t1));
        assertSame(one, stage.take(t1));
        assertNull("single use", stage.take(t1));
        assertFalse(stage.matches(t1));
        String t2 = stage.put(two);
        assertNotEquals("a new check, a new token", t1, t2);
        assertSame(two, stage.take(t2));
    }

    @Test
    public void aNewChoiceMakesTheOldTokenUselessAndClearForgetsTheBackup() throws Exception {
        RestoreNow.Stage stage = new RestoreNow.Stage();
        LibraryBackup.Checked one = check(backupOf(BACKED_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        LibraryBackup.Checked two = check(backupOf(CURRENT_REELS, null), new File(tmp.newFolder(), "restore-staging"));
        String t1 = stage.put(one);
        String t2 = stage.put(two);
        assertNotEquals(t1, t2);
        assertNull("the old token is dead", stage.take(t1));
        assertTrue(stage.matches(t2));
        stage.clear();
        assertFalse(stage.staged());
        assertNull(stage.take(t2));
    }

    @Test
    public void onlyABackupThatPassedTheCheckCanBeStaged() throws Exception {
        RestoreNow.Stage stage = new RestoreNow.Stage();
        LibraryBackup.Checked refused = check(b("not a zip"), new File(tmp.newFolder(), "restore-staging"));
        assertFalse(refused.ok());
        try {
            stage.put(refused);
            fail();
        } catch (IllegalArgumentException expected) {
            // refused
        }
        try {
            stage.put(null);
            fail();
        } catch (IllegalArgumentException expected) {
            // refused
        }
        assertFalse(stage.staged());
    }

    // ------------------------------------------------------------------ the install, on real files

    @Test
    public void aBackupRoundTripsByteForByteAndTheLibraryInPlaceIsKeptNotDeleted() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        reels.read();
        shots.read();
        assertTrue(reels.write(CURRENT_REELS.replace("Heat", "Heat 2"), reels.revision()).ok);  // main differs from bak
        String before = get(reels.main), bakBefore = get(reels.bak);
        long rev = reels.revision(), shotsRev = shots.revision();
        File staging = new File(dir, "restore-staging");
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), staging);
        assertTrue(c.message, c.ok());

        JSONObject r = json(RestoreNow.install(reels, shots, c));

        assertEquals("byte for byte what was in the backup", BACKED_REELS, get(reels.main));
        assertEquals(BACKED_SHOTS, get(shots.main));
        assertArrayEquals(b(BACKED_REELS), bytes(reels.main));
        File[] keptReels = beforeRestore(dir, "reels.json");
        assertEquals(1, keptReels.length);
        assertEquals("the library that was in place is kept as it was", before, get(keptReels[0]));
        assertEquals(keptReels[0].getName(), r.getString("set_aside"));
        assertEquals(CURRENT_SHOTS, get(beforeRestore(dir, "shots.json")[0]));
        assertEquals(beforeRestore(dir, "shots.json")[0].getName(), r.getString("shots_set_aside"));
        assertEquals("restored", r.getString("shots"));
        assertEquals("the backup file (reels.json.bak) is not touched", bakBefore, get(reels.bak));
        assertEquals(rev + 1, reels.revision());
        assertEquals(shotsRev + 1, shots.revision());
        assertFalse(reels.locked());
        assertEquals(LibraryFile.State.OK, reels.state());
        // a page that loaded before the restore cannot save over it
        LibraryFile.Result stale = reels.write(CURRENT_REELS, rev);
        assertTrue(stale.stale && !stale.ok);
        assertEquals(BACKED_REELS, get(reels.main));
        // one that loads now can
        assertTrue(reels.write(BACKED_REELS.replace("Dune", "Dune 2"), reels.revision()).ok);
        assertEquals("the restored library became the backup of the next save", BACKED_REELS, get(reels.bak));
        // the staging folder only has what the caller clears: no library file, nothing the library uses
        assertFalse(new File(staging, "reels.json").exists() || new File(staging, "shots.json").exists());
        LibraryBackup.clear(staging);
        assertEquals(0, staging.list().length);
    }

    @Test
    public void aFreshInstallHasNothingToSetAsideAndTakesTheBackup() throws Exception {
        File dir = phone(null, null);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        JSONObject r = json(RestoreNow.install(reels, shots, c));
        assertEquals("", r.getString("set_aside"));
        assertEquals("", r.getString("shots_set_aside"));
        assertEquals(BACKED_REELS, get(reels.main));
        assertEquals(BACKED_SHOTS, get(shots.main));
        assertEquals(0, beforeRestore(dir, "reels.json").length);
    }

    @Test
    public void aBackupWithoutAScreenshotListLeavesTheOneInPlaceAlone() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        long shotsRev = shots.revision();
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, null), new File(dir, "restore-staging"));
        assertFalse(c.hasShots());
        JSONObject r = json(RestoreNow.install(reels, shots, c));
        assertEquals("kept", r.getString("shots"));
        assertEquals("", r.getString("shots_set_aside"));
        assertEquals(CURRENT_SHOTS, get(shots.main));
        assertEquals(0, beforeRestore(dir, "shots.json").length);
        assertEquals(shotsRev, shots.revision());
        assertEquals(BACKED_REELS, get(reels.main));
    }

    @Test
    public void anUnreadableLibraryIsSetAsideNotDeletedAndRestoringUnlocksIt() throws Exception {
        String cut = CURRENT_REELS.substring(0, CURRENT_REELS.length() / 2);
        File dir = phone(cut, null);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        assertEquals("", reels.read());
        assertTrue(reels.locked());
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, null), new File(dir, "restore-staging"));
        JSONObject r = json(RestoreNow.install(reels, shots, c));
        assertEquals(cut, get(new File(dir, r.getString("set_aside"))));
        assertEquals(BACKED_REELS, get(reels.main));
        assertFalse(reels.locked());
        assertEquals(LibraryFile.State.OK, reels.state());
        assertTrue(reels.write(BACKED_REELS.replace("Dune", "Dune 2"), reels.revision()).ok);
    }

    @Test
    public void aNewerLibraryIsNeverReplacedAndNothingChanges() throws Exception {
        File dir = phone(NEWER_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        assertEquals("", reels.read());
        assertEquals(LibraryFile.State.NEWER, reels.state());
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        String before = fingerprint(dir);
        long rev = reels.revision();
        BackupNow.Outcome o = RestoreNow.install(reels, shots, c);
        assertFalse(o.text, o.ok);
        assertEquals(RestoreNow.NEWER_LIBRARY, o.text);
        assertEquals("not a byte changed, nothing renamed or set aside", before, fingerprint(dir));
        assertEquals(rev, reels.revision());
        assertEquals(LibraryFile.State.NEWER, reels.state());
        assertTrue("the staged files are still there: nothing was consumed", c.reels.isFile() && c.shots.isFile());
        assertEquals(CURRENT_SHOTS, get(shots.main));
    }

    @Test
    public void aNewerScreenshotListRefusesTheWholeRestoreBeforeTheReelsAreReplaced() throws Exception {
        File dir = phone(CURRENT_REELS, NEWER_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        reels.read();
        assertEquals(LibraryFile.State.OK, reels.state());
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        String before = fingerprint(dir);
        BackupNow.Outcome o = RestoreNow.install(reels, shots, c);
        assertFalse(o.ok);
        assertEquals(RestoreNow.NEWER_SHOTS, o.text);
        assertEquals("the reels were not replaced either", before, fingerprint(dir));
        assertEquals(0, beforeRestore(dir, "reels.json").length);
        // a backup with no screenshot list does not touch the newer one, so it may go ahead
        LibraryBackup.Checked noShots = check(backupOf(BACKED_REELS, null), new File(dir, "restore-staging"));
        JSONObject r = json(RestoreNow.install(reels, shots, noShots));
        assertEquals("kept", r.getString("shots"));
        assertEquals(NEWER_SHOTS, get(shots.main));
        assertEquals(BACKED_REELS, get(reels.main));
    }

    @Test
    public void ifTheReelsWereRestoredAndTheScreenshotListFailedTheAnswerSaysExactlyThat() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        reels.read();
        shots.read();
        shots.mover = (from, to) -> {
            throw new IOException("disk says no");
        };
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        BackupNow.Outcome o = RestoreNow.install(reels, shots, c);
        JSONObject r = json(o);  // a success for the reels
        assertEquals("failed", r.getString("shots"));
        assertEquals("", r.getString("shots_set_aside"));
        assertFalse("no path or exception text reaches the page", o.text.contains("disk says no"));
        assertEquals(BACKED_REELS, get(reels.main));
        assertEquals("the screenshot list is as it was", CURRENT_SHOTS, get(shots.main));
        assertEquals("no stray set-aside copy of it", 0, beforeRestore(dir, "shots.json").length);
        assertEquals(1, beforeRestore(dir, "reels.json").length);
    }

    @Test
    public void ifTheReelsCannotBeInstalledNothingAtAllChanges() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        reels.read();
        shots.read();
        reels.mover = (from, to) -> {
            throw new IOException("no");
        };
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        String before = fingerprint(dir);
        long rev = reels.revision(), shotsRev = shots.revision();
        BackupNow.Outcome o = RestoreNow.install(reels, shots, c);
        assertFalse(o.ok);
        assertEquals(RestoreNow.NOT_INSTALLED, o.text);
        assertEquals(before, fingerprint(dir));
        assertEquals("the screenshot list was not touched after the reels failed", CURRENT_SHOTS, get(shots.main));
        assertEquals(rev, reels.revision());
        assertEquals(shotsRev, shots.revision());
    }

    @Test
    public void aBackupWhoseStagedFilesAreGoneIsNotInstalled() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        LibraryBackup.clear(new File(dir, "restore-staging"));  // cancelled, or another choice emptied the folder
        String before = fingerprint(dir);
        BackupNow.Outcome o = RestoreNow.install(reels, shots, c);
        assertFalse(o.ok);
        assertEquals(RestoreNow.NOT_READY, o.text);
        assertEquals(before, fingerprint(dir));
        assertEquals(RestoreNow.NOT_READY, RestoreNow.install(reels, shots, null).text);
        assertEquals(RestoreNow.NOT_READY, RestoreNow.install(reels, shots, check(b("nope"), new File(dir, "restore-staging"))).text);
    }

    @Test
    public void theSameBackupCannotBeInstalledTwice() throws Exception {
        File dir = phone(CURRENT_REELS, null);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, null), new File(dir, "restore-staging"));
        assertTrue(RestoreNow.install(reels, shots, c).ok);
        reels.write(BACKED_REELS.replace("Dune", "Dune 2"), reels.revision());  // the user carries on
        String after = fingerprint(dir);
        assertFalse(RestoreNow.install(reels, shots, c).ok);
        assertEquals("a second install of the same staged file changes nothing", after, fingerprint(dir));
    }

    @Test
    public void everyRestoreKeepsItsOwnSetAsideFileSoNothingIsEverOverwritten() throws Exception {
        File dir = phone(CURRENT_REELS, null);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        assertTrue(RestoreNow.install(reels, shots, check(backupOf(BACKED_REELS, null), new File(dir, "restore-staging"))).ok);
        assertTrue(RestoreNow.install(reels, shots, check(backupOf(NEWER_REELS.replace("99", "1"), null), new File(dir, "restore-staging"))).ok);
        File[] kept = beforeRestore(dir, "reels.json");
        assertEquals("two restores, two kept libraries", 2, kept.length);
        List<String> texts = new ArrayList<>();
        for (File f : kept) texts.add(get(f));
        assertTrue(texts.contains(CURRENT_REELS) && texts.contains(BACKED_REELS));
    }

    @Test
    public void theTokenFlowEndToEndGivesOneInstallAndThenNothing() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        RestoreNow.Stage stage = new RestoreNow.Stage();
        File staging = new File(dir, "restore-staging");
        LibraryBackup.Checked c = check(backupOf(BACKED_REELS, BACKED_SHOTS), staging);
        String token = stage.put(c);
        assertNull("a guessed token installs nothing", stage.take("guess"));
        assertEquals(CURRENT_REELS, get(reels.main));
        LibraryBackup.Checked taken = stage.take(token);
        assertNotNull(taken);
        assertTrue(RestoreNow.install(reels, shots, taken).ok);
        assertNull("the token is used up", stage.take(token));
        assertEquals(BACKED_REELS, get(reels.main));
    }

    // ------------------------------------------------------------------ the backup made first must not disturb the one waiting

    @Test
    public void theBackupThePageMakesFirstReadsBackInItsOwnFolderAndLeavesTheStagedRestoreAlone() throws Exception {
        File dir = phone(CURRENT_REELS, CURRENT_SHOTS);
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        LibraryBackup.Checked waiting = check(backupOf(BACKED_REELS, BACKED_SHOTS), new File(dir, "restore-staging"));
        // what backupLibrary does: its read-back unpacks into backup-check (LocalBridge), which is emptied afterwards
        File backupCheck = new File(dir, "backup-check");
        LibraryBackup.Checked readBack = check(backupOf(CURRENT_REELS, CURRENT_SHOTS), backupCheck);
        assertTrue(readBack.ok());
        LibraryBackup.clear(backupCheck);
        assertTrue("the staged restore is still whole", waiting.reels.isFile() && waiting.shots.isFile());
        assertTrue(RestoreNow.install(reels, shots, waiting).ok);
        assertEquals(BACKED_REELS, get(reels.main));
    }

    @Test
    public void unpackingAnotherFileIntoTheSameFolderReplacesTheFilesTheStagedRestorePointsTo() throws Exception {
        // why the two folders are separate, and why LocalBridge forgets the token before it unpacks a new choice: the files of the
        // first check are the same paths as the files of the second one
        File dir = phone(CURRENT_REELS, null);
        File staging = new File(dir, "restore-staging");
        LibraryBackup.Checked waiting = check(backupOf(BACKED_REELS, null), staging);
        assertEquals(BACKED_REELS, get(waiting.reels));
        assertTrue(check(backupOf(CURRENT_REELS, null), staging).ok());
        assertEquals("the first Checked now points at the second backup's bytes", CURRENT_REELS, get(waiting.reels));
    }
}
