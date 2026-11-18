package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.TimeZone;

/** The parts of "Back up now" that need no phone. LocalBridge.backupLibrary itself cannot be tested here: it needs Android. */
public class BackupNowTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final long MB = 1024L * 1024;

    // ------------------------------------------------------------------ the name

    @Test
    public void theNameHasTheDateAndTimeInTheGivenZone() {
        long t = 1_700_000_000_000L;  // 2023-11-14 22:13:20 UTC
        assertEquals("ReelShelf-backup-20231114-221320.zip", BackupNow.fileName(t, TimeZone.getTimeZone("UTC")));
        assertEquals("ReelShelf-backup-20231115-001320.zip", BackupNow.fileName(t, TimeZone.getTimeZone("Europe/Athens")));
    }

    @Test
    public void twoBackupsNeverGetTheSameName() {
        long t = 1_700_000_000_000L;
        assertEquals("the first is the clock", t, BackupNow.nameTime(t, 0));
        assertEquals("a second later is the clock", t + 1000, BackupNow.nameTime(t + 1000, t));
        assertEquals("the same second moves on to the next", t + 1000, BackupNow.nameTime(t, t));
        assertEquals("half a second later moves on too", t + 1000, BackupNow.nameTime(t + 500, t));
        assertEquals("a clock that went back moves on", t + 1000, BackupNow.nameTime(t - 5000, t));
        TimeZone utc = TimeZone.getTimeZone("UTC");
        long last = 0;
        java.util.Set<String> names = new java.util.HashSet<>();
        for (int i = 0; i < 20; i++) {
            last = BackupNow.nameTime(t + i * 10L, last);  // twenty taps within a fifth of a second
            assertTrue("name " + i + " is new", names.add(BackupNow.fileName(last, utc)));
        }
    }

    // ------------------------------------------------------------------ free space

    @Test
    public void theSpaceNeededIsTheZipPlusTheReadBackCopyPlusTheReserve() {
        long reserve = 100 * MB;
        assertEquals(100 * MB + 2 * (30 * MB + 5 * MB), BackupNow.neededBytes(30 * MB, 5 * MB, reserve));
        assertEquals("no shots", 100 * MB + 2 * 30 * MB, BackupNow.neededBytes(30 * MB, 0, reserve));
        assertEquals("an empty file still needs the reserve", reserve, BackupNow.neededBytes(0, 0, reserve));
        assertEquals("a negative size counts as nothing", reserve + 2 * MB, BackupNow.neededBytes(-5, MB, reserve));
    }

    @Test
    public void theSpaceNeededNeverWrapsRoundToSmall() {
        assertEquals(Long.MAX_VALUE, BackupNow.neededBytes(Long.MAX_VALUE, Long.MAX_VALUE, 100 * MB));
        assertEquals(Long.MAX_VALUE, BackupNow.neededBytes(Long.MAX_VALUE / 2, 0, 100 * MB));
        assertTrue(BackupNow.neededBytes(Long.MAX_VALUE / 4, 0, 100 * MB) > Long.MAX_VALUE / 4);
    }

    @Test
    public void theSpaceSentenceSaysHowMuchIsNeededAndFreeAndNothingElse() {
        String s = BackupNow.notEnoughSpace(220 * MB + 1, 150 * MB + 12345);
        assertTrue(s, s.contains("221 MB are needed and 150 MB are free"));
        assertTrue(s, s.endsWith("Your library was not changed."));
        assertPlain(s);
        assertTrue("a negative free space is shown as 0", BackupNow.notEnoughSpace(MB, -1).contains("0 MB are free"));
    }

    // ------------------------------------------------------------------ the counts in the manifest

    @Test
    public void theCountsAreTheThreeNumbersThePageSent() throws Exception {
        JSONObject c = BackupNow.counts("{\"reels\":1204,\"titles\":88,\"screenshots\":15000}", true);
        assertEquals(1204, c.getLong("reels"));
        assertEquals(88, c.getLong("titles"));
        assertEquals(15000, c.getLong("screenshots"));
        assertEquals(3, c.length());
    }

    @Test
    public void nothingElseOfWhatThePageSentGoesIntoTheManifest() throws Exception {
        JSONObject c = BackupNow.counts("{\"reels\":2,\"titles\":1,\"screenshots\":0,\"apiKey\":\"secret\",\"notes\":{\"a\":1},\"x\":[1]}", true);
        assertEquals(3, c.length());
        assertFalse(c.toString().contains("secret"));
    }

    @Test
    public void aHostileOrBrokenCountIsZeroOrCapped() throws Exception {
        JSONObject c = BackupNow.counts("{\"reels\":\"many\",\"titles\":-4,\"screenshots\":1e30}", true);
        assertEquals("a string is not a number", 0, c.getLong("reels"));
        assertEquals("negative", 0, c.getLong("titles"));
        assertEquals("capped", BackupNow.MAX_COUNT, c.getLong("screenshots"));
        assertEquals(0, BackupNow.counts("{\"reels\":0.4}", true).getLong("reels"));
        assertEquals(7, BackupNow.counts("{\"reels\":7.9}", true).getLong("reels"));
        for (String bad : new String[]{null, "", "not json", "[1,2]", "{", "null"}) {
            JSONObject z = BackupNow.counts(bad, true);
            assertEquals(bad, 3, z.length());
            assertEquals(bad, 0, z.getLong("reels") + z.getLong("titles") + z.getLong("screenshots"));
        }
    }

    @Test
    public void screenshotsAreCountedAsZeroWhenTheListIsNotInTheBackup() throws Exception {
        JSONObject c = BackupNow.counts("{\"reels\":3,\"titles\":2,\"screenshots\":500}", false);
        assertEquals(0, c.getLong("screenshots"));
        assertEquals(3, c.getLong("reels"));
    }

    // ------------------------------------------------------------------ what the page is told

    @Test
    public void theAnswerForThePageHasTheNameThePlaceTheSizeAndTheCounts() throws Exception {
        JSONObject counts = BackupNow.counts("{\"reels\":5,\"titles\":2,\"screenshots\":9}", true);
        BackupNow.Outcome o = BackupNow.ok("ReelShelf-backup-20231114-221320.zip", "Downloads/ReelShelf/ReelShelf-backup-20231114-221320.zip", 123456, counts, false, true);
        assertTrue(o.ok);
        JSONObject j = new JSONObject(o.text);
        assertEquals("ReelShelf-backup-20231114-221320.zip", j.getString("name"));
        assertEquals("Downloads/ReelShelf/ReelShelf-backup-20231114-221320.zip", j.getString("where"));
        assertEquals(123456, j.getLong("bytes"));
        assertEquals(5, j.getJSONObject("counts").getInt("reels"));
        assertFalse(j.getBoolean("uninstall_warning"));
        assertTrue(j.getBoolean("shots_skipped"));
        assertEquals("these fields and no others", 6, j.length());
    }

    @Test
    public void onAndroid8And9ThePlaceIsTheAppsOwnFolderAndTheAnswerWarnsAboutUninstalling() throws Exception {
        String where = BackupNow.where(true, "app.reelshelf", "b.zip");
        assertEquals("Android/data/app.reelshelf/files/Download/ReelShelf/b.zip", where);
        assertFalse("no full internal path", where.startsWith("/"));
        assertEquals("Downloads/ReelShelf/b.zip", BackupNow.where(false, "app.reelshelf", "b.zip"));
        assertTrue(new JSONObject(BackupNow.ok("b.zip", where, 1, new JSONObject(), true, false).text).getBoolean("uninstall_warning"));
    }

    @Test
    public void aFailureIsOneSentenceAndNotOk() {
        BackupNow.Outcome o = BackupNow.fail(BackupNow.LOCKED);
        assertFalse(o.ok);
        assertEquals(BackupNow.LOCKED, o.text);
    }

    // ------------------------------------------------------------------ the sentences

    private static void assertPlain(String s) {
        assertFalse("no path in: " + s, s.contains("/") || s.contains("\\"));
        assertFalse("no exception text in: " + s, s.contains("Exception") || s.contains("java.") || s.contains("errno") || s.contains("ENOSPC"));
        assertTrue("a sentence: " + s, s.endsWith("."));
    }

    @Test
    public void everySentenceIsPlainLanguageWithNoPathAndNoExceptionText() {
        for (String s : new String[]{BackupNow.BUSY, BackupNow.LOCKED, BackupNow.NOTHING, BackupNow.READ_BACK, BackupNow.OUT_OF_MEMORY,
                BackupNow.DISK_FULL, BackupNow.GENERIC, BackupNow.notEnoughSpace(MB, 0)}) assertPlain(s);
    }

    @Test
    public void theLockedSentencePointsToSavingTheUnreadableFile() {
        assertTrue(BackupNow.LOCKED.contains("Save the unreadable file"));
    }

    @Test
    public void aFailureWithItsOwnSentenceIsPassedOnAsItIs() {
        assertEquals(BackupNow.READ_BACK, BackupNow.sentenceFor(new BackupNow.Failure(BackupNow.READ_BACK)));
        assertEquals(BackupNow.OUT_OF_MEMORY, BackupNow.sentenceFor(new BackupNow.Failure(BackupNow.OUT_OF_MEMORY)));
    }

    @Test
    public void aFullDiskIsToldApartEvenWhenItIsWrappedInAnotherException() {
        assertEquals(BackupNow.DISK_FULL, BackupNow.sentenceFor(new IOException("write failed: ENOSPC (No space left on device)")));
        assertEquals(BackupNow.DISK_FULL, BackupNow.sentenceFor(new IOException("failed", new IOException("No space left on device"))));
        assertEquals(BackupNow.DISK_FULL, BackupNow.sentenceFor(new RuntimeException(new IOException("x", new IOException("ENOSPC")))));
    }

    @Test
    public void anyOtherExceptionGivesTheGeneralSentenceAndNeverItsOwnText() {
        String secret = "open failed: ENOENT /data/user/0/app.reelshelf/files/backup-work/reels.json (my private note)";
        for (Throwable t : new Throwable[]{new IOException(secret), new RuntimeException(secret), new IOException("a", new IOException(secret)),
                new IOException((String) null), new SecurityException(secret)}) {
            String s = BackupNow.sentenceFor(t);
            assertEquals(BackupNow.GENERIC, s);
            assertFalse(s.contains("/data"));
            assertFalse(s.contains("private note"));
        }
    }

    @Test
    public void aCauseChainThatLoopsDoesNotHangTheSentence() {
        IOException a = new IOException("a");
        IOException b = new IOException("b", a);
        a.initCause(b);
        assertEquals(BackupNow.GENERIC, BackupNow.sentenceFor(b));
    }

    // ------------------------------------------------------------------ the byte counter

    @Test
    public void theCounterCountsEveryByteAndLeavesTheStreamOpen() throws Exception {
        final boolean[] closed = {false};
        ByteArrayOutputStream sink = new ByteArrayOutputStream() {
            @Override
            public void close() throws IOException {
                closed[0] = true;
                super.close();
            }
        };
        BackupNow.Counter c = new BackupNow.Counter(sink);
        c.write(7);
        c.write(new byte[]{1, 2, 3, 4, 5}, 1, 3);
        c.write(new byte[]{9, 9});
        c.flush();
        assertEquals(6, c.count());
        assertArrayEquals(new byte[]{7, 2, 3, 4, 9, 9}, sink.toByteArray());
        assertFalse("the stream stays the caller's", closed[0]);
    }

    // ------------------------------------------------------------------ the bridge's sequence, on real files

    private static final String REELS = "{\"schema_version\":1,\"reels\":[{\"code\":\"AAAAA1\",\"note\":\"café ☃\"}],\"media\":[{\"title\":\"Dune\"}],\"inbox\":[]}";
    private static final String SHOTS = "{\"v\":1,\"seen\":{\"a\":{\"st\":\"done\"}},\"reels\":{}}";

    /**
     * What LocalBridge.makeBackup does, without Android: snapshots into backup-work, the ZIP through the counter and a
     * 64 KB buffer into a file, the read-back with the limit the bridge uses (the raw sizes plus the manifest allowance),
     * then clean-up. The limit must be enough for a correct backup (or the bridge would refuse its own file).
     */
    @Test
    public void theBridgesSequenceMakesABackupThatReadsBackAndLeavesNothingBehind() throws Exception {
        File dir = tmp.newFolder();
        Files.write(new File(dir, "reels.json").toPath(), REELS.getBytes(StandardCharsets.UTF_8));
        Files.write(new File(dir, "shots.json").toPath(), SHOTS.getBytes(StandardCharsets.UTF_8));
        LibraryFile reels = LibraryFile.reels(dir), shots = LibraryFile.shots(dir);
        File snaps = new File(dir, "backup-work"), staging = new File(dir, "restore-staging");
        File rs = new File(snaps, "reels.json"), ss = new File(snaps, "shots.json");
        LibraryBackup.clear(snaps);
        boolean haveReels, haveShots;
        synchronized (reels) {
            haveReels = reels.snapshotTo(rs);
            synchronized (shots) {
                haveShots = shots.snapshotTo(ss);
            }
        }
        assertTrue(haveReels && haveShots);
        long raw = rs.length() + ss.length();
        // a save while the backup is made does not change what is backed up
        assertTrue(reels.write(REELS.replace("Dune", "Other"), reels.revision()).ok);

        File zip = new File(dir, "out.zip");
        long size;
        try (OutputStream file = new FileOutputStream(zip)) {
            BackupNow.Counter counter = new BackupNow.Counter(file);
            BufferedOutputStream buffered = new BufferedOutputStream(counter, 64 * 1024);
            LibraryBackup.write(buffered, rs, reels.supported(), ss, shots.supported(), BackupNow.counts("{\"reels\":1,\"titles\":1,\"screenshots\":1}", true), "1.3.20", 27, 1_700_000_000_000L);
            buffered.flush();
            size = counter.count();
        }
        assertEquals("the size told to the page is the size of the file", zip.length(), size);

        LibraryBackup.Checked c;
        try (InputStream in = new BufferedInputStream(new FileInputStream(zip), 64 * 1024)) {
            c = LibraryBackup.check(in, staging, raw + LibraryBackup.MANIFEST_MAX_BYTES);
        }
        assertTrue(c.message, c.ok());
        assertEquals("the backup holds the library as it was when the snapshot was taken", REELS, new String(Files.readAllBytes(c.reels.toPath()), StandardCharsets.UTF_8));
        assertEquals(SHOTS, new String(Files.readAllBytes(c.shots.toPath()), StandardCharsets.UTF_8));
        assertEquals("1.3.20", c.appVersionName);
        assertEquals(27, c.appVersionCode);
        assertEquals(1, c.counts.getInt("titles"));

        LibraryBackup.clear(snaps);
        LibraryBackup.clear(staging);
        assertEquals(0, snaps.list().length);
        assertEquals(0, staging.list().length);
        assertTrue("the library files are untouched by the clean-up", new File(dir, "reels.json").isFile() && new File(dir, "shots.json").isFile());
    }

    @Test
    public void theReadBackLimitIsTightEnoughToRefuseAFileBiggerThanWhatWasBackedUp() throws Exception {
        File dir = tmp.newFolder();
        Files.write(new File(dir, "reels.json").toPath(), REELS.getBytes(StandardCharsets.UTF_8));
        File rs = new File(dir, "snap-reels.json");
        Files.copy(new File(dir, "reels.json").toPath(), rs.toPath());
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        LibraryBackup.write(out, rs, 1, null, 1, new JSONObject(), "t", 1, 0L);
        File staging = tmp.newFolder();
        LibraryBackup.Checked c = LibraryBackup.check(new java.io.ByteArrayInputStream(out.toByteArray()), staging, rs.length() - 1);
        assertFalse("a limit below the file's size refuses it", c.ok());
        assertEquals(0, staging.list().length);
    }

    @Test
    public void aLockedLibraryGivesNoSnapshot() throws Exception {
        File dir = tmp.newFolder();
        Files.write(new File(dir, "reels.json").toPath(), "{\"reels\": [".getBytes(StandardCharsets.UTF_8));  // damaged
        LibraryFile reels = LibraryFile.reels(dir);
        reels.read();
        assertTrue(reels.locked());
        File snap = new File(tmp.newFolder(), "reels.json");
        try {
            reels.snapshotTo(snap);
            org.junit.Assert.fail("a locked library must not be snapshotted");
        } catch (IOException expected) {
            assertTrue("the bridge turns this into the 'cannot be backed up' sentence by looking at locked()", reels.locked());
        }
        assertFalse(snap.exists());
    }
}
