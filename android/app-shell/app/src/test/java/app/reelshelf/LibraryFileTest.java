package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** The library file's safety net: a damaged file is never replaced by an empty one, and nothing is deleted. */
public class LibraryFileTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final String V1 = "{\"reels\":[{\"code\":\"AAAAA1\"}],\"media\":[]}";
    private static final String V2 = "{\"reels\":[{\"code\":\"AAAAA1\"},{\"code\":\"BBBBB2\"}],\"media\":[]}";

    private static void put(File f, String s) throws IOException {
        Files.write(f.toPath(), s.getBytes(StandardCharsets.UTF_8));
    }

    private static String get(File f) throws IOException {
        return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
    }

    private File[] badFiles(File dir, String name) {
        return dir.listFiles((d, n) -> n.startsWith(name + ".bad-"));
    }

    @Test
    public void aNewInstallHasNoFileAndIsNotLocked() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.MISSING, f.state());
        assertTrue(f.write(V1));
        assertEquals(V1, get(f.main));
        assertFalse("the first save has nothing to back up", f.bak.exists());
    }

    @Test
    public void everyWriteKeepsThePreviousVersionAsTheBackup() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        assertTrue(f.write(V2));
        assertEquals(V2, get(f.main));
        assertEquals(V1, get(f.bak));
        assertFalse(new File(dir, "reels.json.tmp").exists());
    }

    @Test
    public void sameFileGivesTheSameInstanceSoTheLockIsSharedByEveryPage() throws Exception {
        File dir = tmp.newFolder();
        assertSame(LibraryFile.reels(dir), LibraryFile.reels(dir));
    }

    @Test
    public void aFileThatWasReadFineIsReturnedAsIs() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), V2);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals(V2, f.read());
        assertEquals(LibraryFile.State.OK, f.state());
    }

    @Test
    public void aTruncatedFileWithNoBackupLocksAndIsNeverOverwritten() throws Exception {
        File dir = tmp.newFolder();
        String cut = V2.substring(0, V2.length() / 2);
        put(new File(dir, "reels.json"), cut);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.UNREADABLE, f.state());
        assertTrue(f.locked());
        assertFalse("a write is refused while locked", f.write("{\"reels\":[]}"));
        assertEquals("the damaged file is exactly as it was", cut, get(f.main));
        assertFalse(f.bak.exists());
    }

    @Test
    public void anEmptyFileWithNoBackupIsDamagedNotNew() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "");
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.UNREADABLE, f.state());
        assertFalse(f.write(V1));
        assertTrue(new File(dir, "reels.json").exists());
    }

    @Test
    public void aFileWithJunkAfterTheJsonOrTheWrongShapeIsDamaged() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), V1 + "\u0000\u0000garbage");
        assertEquals("", LibraryFile.reels(dir).read());
        assertEquals(LibraryFile.State.UNREADABLE, LibraryFile.reels(dir).state());
        File dir2 = tmp.newFolder();
        put(new File(dir2, "reels.json"), "{\"reels\":{\"not\":\"a list\"}}");
        assertEquals("", LibraryFile.reels(dir2).read());
        assertEquals(LibraryFile.State.UNREADABLE, LibraryFile.reels(dir2).state());
        File dir3 = tmp.newFolder();
        put(new File(dir3, "reels.json"), "[1,2,3]");
        assertEquals("", LibraryFile.reels(dir3).read());
    }

    @Test
    public void aReelsFileFromAnOlderVersionWithExtraOrMissingKeysIsFine() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{\"inbox\":[],\"unknownKey\":{\"a\":1}}");
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("{\"inbox\":[],\"unknownKey\":{\"a\":1}}", f.read());
        assertEquals(LibraryFile.State.OK, f.state());
        File dir2 = tmp.newFolder();
        put(new File(dir2, "reels.json"), "{\"reels\":null,\"media\":[]}");
        assertEquals(LibraryFile.State.OK, readState(LibraryFile.reels(dir2)));
    }

    private static LibraryFile.State readState(LibraryFile f) {
        f.read();
        return f.state();
    }

    @Test
    public void aDamagedFileIsReplacedByTheGoodBackupAndKept() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), V2.substring(0, 20));
        put(new File(dir, "reels.json.bak"), V1);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals(V1, f.read());
        assertEquals(LibraryFile.State.RECOVERED, f.state());
        assertFalse(f.locked());
        assertEquals(V1, get(f.main));
        assertEquals("the backup stays where it was", V1, get(f.bak));
        File[] bad = badFiles(dir, "reels.json");
        assertEquals(1, bad.length);
        assertEquals("the damaged file is kept, not deleted", V2.substring(0, 20), get(bad[0]));
        assertEquals(bad[0].getName(), f.badName());
        assertEquals("recovered", f.takeNotice());
        assertEquals("", f.takeNotice());
        assertTrue(f.write(V2));
        assertEquals(V1, get(f.bak));
    }

    @Test
    public void aMissingFileWithAGoodBackupIsRestoredNotTreatedAsNew() throws Exception {
        File dir = tmp.newFolder();  // the app died between the two renames of a save
        put(new File(dir, "reels.json.bak"), V1);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals(V1, f.read());
        assertEquals(LibraryFile.State.RECOVERED, f.state());
        assertEquals(V1, get(f.main));
        assertEquals(0, badFiles(dir, "reels.json").length);
    }

    @Test
    public void aDamagedBackupIsNeverUsedAndNeverReplacedByTheDamagedFile() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{oops");
        put(new File(dir, "reels.json.bak"), "also {oops");
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.UNREADABLE, f.state());
        assertEquals("{oops", get(f.main));
        assertEquals("also {oops", get(f.bak));
    }

    @Test
    public void startingNewSetsEverythingAsideRenamedNeverDeleted() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{oops");
        put(new File(dir, "reels.json.bak"), "also {oops");
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        File bad = f.startNew();
        assertNotNull(bad);
        assertEquals("{oops", get(bad));
        assertFalse(f.main.exists());
        assertFalse(f.bak.exists());
        File[] all = dir.listFiles((d, n) -> n.startsWith("reels.json.bak.bad-"));
        assertEquals(1, all.length);
        assertEquals("also {oops", get(all[0]));
        assertFalse(f.locked());
        assertEquals("started_new", f.takeNotice());
        assertTrue(f.write(V1));
        assertEquals(V1, get(f.main));
        assertEquals(V1, LibraryFile.reels(dir).read());
    }

    @Test
    public void aFileThatWasNeverVettedIsSetAsideNotReplacedOrBackedUp() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), V1);  // exists, but this process never read it
        LibraryFile f = LibraryFile.reels(dir);
        assertTrue(f.write(V2));
        assertEquals(V2, get(f.main));
        assertFalse("not a vetted file: it does not become the backup", f.bak.exists());
        File[] bad = badFiles(dir, "reels.json");
        assertEquals(1, bad.length);
        assertEquals(V1, get(bad[0]));
    }

    @Test
    public void twoDamagedFilesInTheSameSecondGetDifferentNames() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        put(f.main, "{a");
        f.read();
        f.startNew();
        put(f.main, "{b");
        f.read();
        f.startNew();
        assertEquals(2, badFiles(dir, "reels.json").length);
    }

    @Test
    public void shotsFileHasItsOwnShapeAndItsOwnLock() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "shots.json"), "{\"v\":1,\"seen\":{\"k\":{\"m\":1}},\"reels\":{}}");
        LibraryFile s = LibraryFile.shots(dir);
        assertEquals(LibraryFile.State.OK, readState(s));
        File dir2 = tmp.newFolder();
        put(new File(dir2, "shots.json"), "{\"seen\":[1]}");
        assertEquals(LibraryFile.State.UNREADABLE, readState(LibraryFile.shots(dir2)));
        put(new File(dir2, "reels.json"), V1);
        assertEquals("a locked shots file does not lock the library", LibraryFile.State.OK, readState(LibraryFile.reels(dir2)));
    }

    @Test
    public void theUnreadableFileCanBeCopiedOutWhileLockedAndAfterwards() throws Exception {
        File dir = tmp.newFolder();
        String cut = V2.substring(0, 25);
        put(new File(dir, "reels.json"), cut);
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        assertEquals(cut.length(), f.copyUnreadableTo(out));
        assertArrayEquals(cut.getBytes(StandardCharsets.UTF_8), out.toByteArray());
        f.startNew();
        ByteArrayOutputStream again = new ByteArrayOutputStream();
        assertEquals(cut.length(), f.copyUnreadableTo(again));
        assertArrayEquals(cut.getBytes(StandardCharsets.UTF_8), again.toByteArray());
        assertNotNull(f.unreadableFile());
        File dir2 = tmp.newFolder();
        assertEquals(-1, LibraryFile.reels(dir2).copyUnreadableTo(new ByteArrayOutputStream()));
        assertNull(LibraryFile.reels(dir2).unreadableFile());
    }

    @Test
    public void aFileOnlyThePageFoundUnreadableIsTheOneSavedForTheUser() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json.bad-20200101-000000"), "an older damaged file");
        put(new File(dir, "reels.json"), "{\"reels\":[],\"x\":'looks fine to Java'}");  // Java accepts it, the page does not
        LibraryFile f = LibraryFile.reels(dir);
        assertFalse(f.read().isEmpty());
        assertEquals(f.main, f.unreadableFile());
        f.startNew();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        f.copyUnreadableTo(out);
        assertEquals("{\"reels\":[],\"x\":'looks fine to Java'}", out.toString("UTF-8"));
    }

    @Test
    public void dropBackupRemovesOnlyTheBackup() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        f.write(V1);
        f.write(V2);
        assertTrue(f.bak.exists());
        assertTrue(f.dropBackup());
        assertFalse(f.bak.exists());
        assertEquals(V2, get(f.main));
        assertTrue("nothing to drop is fine", f.dropBackup());
    }

    @Test
    public void aWriteThatCannotBeFinishedChangesNothing() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        f.write(V1);
        assertTrue(new File(dir, "reels.json.tmp").mkdir());  // the temp name is taken by a folder: the write fails
        assertFalse(f.write(V2));
        assertEquals(V1, get(f.main));
        assertEquals(LibraryFile.State.OK, f.state());
    }

    // ------------------------------------------------------------------ revisions: a stale page cannot overwrite newer data

    @Test
    public void theRevisionAdvancesOnEverySaveAndNotOnReads() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        LibraryFile.Loaded l = f.load();
        assertEquals(LibraryFile.State.MISSING, l.state);
        assertEquals("", l.text);
        assertEquals(0, l.revision);
        LibraryFile.Result r = f.write(V1, l.revision);
        assertTrue(r.ok);
        assertEquals(1, r.revision);
        assertEquals(1, f.load().revision);
        assertEquals(1, f.load().revision);
        assertEquals(V1, f.load().text);
        assertEquals(2, f.write(V2, 1).revision);
    }

    @Test
    public void aSaveBasedOnAnOldRevisionIsRefusedAndChangesNothing() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        long pageA = f.load().revision;  // two pages load the same version
        long pageB = pageA;
        LibraryFile.Result a = f.write(V1, pageA);  // page A saves first
        assertTrue(a.ok);
        LibraryFile.Result b = f.write(V2, pageB);  // page B's copy is out of date
        assertFalse(b.ok);
        assertTrue(b.stale);
        assertEquals(a.revision, b.revision);
        assertEquals(V1, get(f.main));
        assertFalse("a refused save leaves no backup or temp file behind", f.bak.exists());
        assertFalse(new File(dir, "reels.json.tmp").exists());
        LibraryFile.Loaded again = f.load();  // page B reloads and can save again
        assertEquals(V1, again.text);
        assertTrue(f.write(V2, again.revision).ok);
        assertEquals(V2, get(f.main));
        assertEquals(V1, get(f.bak));
    }

    @Test
    public void aPageThatNeverLoadedCannotSave() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        LibraryFile.Result r = f.write(V1, -1);
        assertTrue(r.stale);
        assertFalse(f.main.exists());
    }

    @Test
    public void aRefusalForOtherReasonsIsNotStale() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{oops");
        LibraryFile f = LibraryFile.reels(dir);
        LibraryFile.Loaded l = f.load();
        assertEquals(LibraryFile.State.UNREADABLE, l.state);
        LibraryFile.Result r = f.write(V1, l.revision);  // locked: refused, but the page's copy is current
        assertFalse(r.ok);
        assertFalse(r.stale);
        assertEquals(l.revision, f.revision());
    }

    @Test
    public void restoringFromTheBackupAndStartingNewMovePagesOutOfDate() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        long before = f.load().revision;
        put(f.main, V2.substring(0, 10));  // damaged while the other page is open
        put(f.bak, V1);
        LibraryFile.Loaded l = f.load();
        assertEquals(LibraryFile.State.RECOVERED, l.state);
        assertTrue(l.revision > before);
        assertTrue("the page that loaded before is now stale", f.write(V2, before).stale);
        long r2 = f.revision();
        f.startNew();
        assertTrue(f.revision() > r2);
    }

    @Test
    public void screenshotListHasItsOwnRevision() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile reels = LibraryFile.reels(dir);
        LibraryFile shots = LibraryFile.shots(dir);
        long r0 = reels.load().revision;
        long s0 = shots.load().revision;
        assertTrue(shots.write("{\"v\":1,\"seen\":{},\"reels\":{}}", s0).ok);
        assertEquals("a save of the screenshot list does not make the library stale", r0, reels.revision());
        assertTrue(reels.write(V1, r0).ok);
    }

    @Test
    public void severalPagesSavingAtOnceNeverLoseAnUpdate() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        assertTrue(f.write("{\"reels\":[],\"n\":0}", f.load().revision).ok);
        final int pages = 4, each = 25;
        final java.util.concurrent.atomic.AtomicInteger refused = new java.util.concurrent.atomic.AtomicInteger();
        final java.util.concurrent.atomic.AtomicInteger failed = new java.util.concurrent.atomic.AtomicInteger();
        Thread[] ts = new Thread[pages];
        for (int p = 0; p < pages; p++) {
            ts[p] = new Thread(() -> {
                try {
                    for (int i = 0; i < each; i++) {
                        while (true) {  // what a page does: load, change, save; when refused, reload and do it again
                            LibraryFile.Loaded l = f.load();
                            int n = new JSONObject(l.text).getInt("n");
                            LibraryFile.Result r = f.write("{\"reels\":[],\"n\":" + (n + 1) + "}", l.revision);
                            if (r.ok) break;
                            if (!r.stale) {
                                failed.incrementAndGet();
                                return;
                            }
                            refused.incrementAndGet();
                        }
                    }
                } catch (Exception e) {
                    failed.incrementAndGet();
                }
            });
            ts[p].start();
        }
        for (Thread t : ts) t.join();
        assertEquals(0, failed.get());
        assertEquals("no update was lost", pages * each, new JSONObject(get(f.main)).getInt("n"));
        assertEquals(1 + pages * each, f.revision());
        assertTrue(new JSONObject(get(f.bak)).getInt("n") >= pages * each - 1);
    }
}
