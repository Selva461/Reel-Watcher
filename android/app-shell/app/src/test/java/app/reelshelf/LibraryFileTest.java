package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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

    // ------------------------------------------------------------------ a library saved by a newer Reel Shelf (schema_version / v)

    private static final String NEWER = "{\"schema_version\":2,\"reels\":[{\"code\":\"NEWER1\",\"renamedField\":1}],\"media\":[]}";

    private static String[] names(File dir) {
        String[] n = dir.list();
        Arrays.sort(n);
        return n;
    }

    /** The folder of the repository that holds `relative`: the test may run from the repository or from android/app-shell/app. */
    private static File repoFile(String relative) {
        File d = new File("").getAbsoluteFile();
        for (File up = d; up != null; up = up.getParentFile()) {
            File f = new File(up, relative);
            if (f.exists()) return f;
        }
        fail(relative + " was not found in or above " + d + ": run Gradle from the repository (the fixtures of the upgrade tests and the page code are read from it)");
        return null;
    }

    @Test
    public void aLibraryFromANewerReelShelfIsLockedAndLeftByteForByteAsItIs() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        String[] before = names(dir);
        LibraryFile f = LibraryFile.reels(dir);
        LibraryFile.Loaded l = f.load();
        assertEquals("a locked library gives no content", "", l.text);
        assertEquals(LibraryFile.State.NEWER, l.state);
        assertEquals(LibraryFile.State.NEWER, f.state());
        assertTrue(f.locked());
        assertEquals(2, f.found());
        assertEquals(LibraryFile.REELS_SCHEMA, f.supported());
        LibraryFile.Result r = f.write(V1, l.revision);
        assertFalse("a write is refused while locked", r.ok);
        assertFalse("and it is not a stale copy: the page's copy is current", r.stale);
        assertFalse(f.write(V1));
        try {
            f.startNew();
            fail("startNew must never be possible for a newer library");
        } catch (IOException expected) {
            // refused, nothing changed
        }
        assertFalse("the backup of a newer library is never deleted", f.dropBackup());
        assertEquals(NEWER, get(f.main));
        assertArrayEquals("no .bak, .bad-*, .tmp or other file appears", before, names(dir));
        assertEquals("nothing was announced to the page", "", f.takeNotice());
        assertEquals("", f.badName());
        assertEquals("the same answer every time it is read", LibraryFile.State.NEWER, readState(f));
        assertEquals(NEWER, get(f.main));
        assertEquals(l.revision, f.revision());
    }

    @Test
    public void theNewerFileCanBeCopiedOutWhileLocked() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertEquals(f.main, f.unreadableFile());
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        assertEquals(NEWER.length(), f.copyUnreadableTo(out));
        assertEquals(NEWER, out.toString("UTF-8"));
    }

    @Test
    public void aNewerMainNextToAnOlderValidBackupIsNotRolledBackToTheBackup() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        put(new File(dir, "reels.json.bak"), V2);  // the library before the newer Reel Shelf saved it
        String[] before = names(dir);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.NEWER, f.state());
        assertTrue(f.locked());
        assertEquals("not restored: that would silently roll the library back", NEWER, get(f.main));
        assertEquals("the backup is untouched too", V2, get(f.bak));
        assertArrayEquals("nothing renamed, nothing set aside", before, names(dir));
        assertEquals(0, badFiles(dir, "reels.json").length);
        assertFalse(f.write(V1));
        assertEquals(NEWER, get(f.main));
        assertEquals(V2, get(f.bak));
    }

    @Test
    public void aDamagedMainWithANewerBackupTouchesNothingEither() throws Exception {
        File dir = tmp.newFolder();
        String cut = NEWER.substring(0, 20);
        put(new File(dir, "reels.json"), cut);
        put(new File(dir, "reels.json.bak"), NEWER);  // only the newer Reel Shelf knows how to restore this one
        String[] before = names(dir);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.NEWER, f.state());
        assertEquals(cut, get(f.main));
        assertEquals(NEWER, get(f.bak));
        assertArrayEquals(before, names(dir));
        assertFalse(f.write(V1));
    }

    @Test
    public void saveACopyGivesTheNewerLibraryEvenWhenMainIsACutFileBesideANewerBackup() throws Exception {
        File dir = tmp.newFolder();
        String cut = NEWER.substring(0, 20);
        put(new File(dir, "reels.json"), cut);
        put(new File(dir, "reels.json.bak"), NEWER);
        String[] before = names(dir);
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertEquals(LibraryFile.State.NEWER, f.state());
        assertEquals("the file that made it NEWER, not the cut main", f.bak, f.unreadableFile());
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        assertEquals(NEWER.length(), f.copyUnreadableTo(out));
        assertEquals("the copy is the newer library, byte for byte", NEWER, out.toString("UTF-8"));
        assertEquals(cut, get(f.main));
        assertEquals(NEWER, get(f.bak));
        assertArrayEquals("every file is still there, none added", before, names(dir));
        assertEquals(0, badFiles(dir, "reels.json").length);
        // the normal case: a newer main is the file given out, with an older backup beside it
        File dir2 = tmp.newFolder();
        put(new File(dir2, "reels.json"), NEWER);
        put(new File(dir2, "reels.json.bak"), V2);
        LibraryFile g = LibraryFile.reels(dir2);
        g.read();
        assertEquals(g.main, g.unreadableFile());
        ByteArrayOutputStream out2 = new ByteArrayOutputStream();
        assertEquals(NEWER.length(), g.copyUnreadableTo(out2));
        assertEquals(NEWER, out2.toString("UTF-8"));
        assertEquals(V2, get(g.bak));
    }

    @Test
    public void aNewerFileWhoseShapeChangedIsNewerNotDamaged() throws Exception {
        File dir = tmp.newFolder();
        String changed = "{\"schema_version\":2,\"reels\":{\"AAAAA1\":{\"status\":\"new\"}}}";  // "reels" is a map now: the old shape check would call this damaged
        put(new File(dir, "reels.json"), changed);
        put(new File(dir, "reels.json.bak"), V1);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals("not UNREADABLE: a damaged file may be set aside, a newer one may not", LibraryFile.State.NEWER, f.state());
        assertEquals(changed, get(f.main));
        assertEquals(V1, get(f.bak));
        assertEquals(0, badFiles(dir, "reels.json").length);
        try {
            f.startNew();
            fail("startNew must never be possible for a newer library");
        } catch (IOException expected) {
            // refused
        }
        assertEquals(changed, get(f.main));
        assertTrue(f.bak.exists());
    }

    @Test
    public void theSameFileReadsFineAgainOnceItIsNotNewer() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals(LibraryFile.State.NEWER, readState(f));
        put(f.main, V2);  // what the newest app's own repair or an update leaves
        assertEquals(V2, f.read());
        assertEquals(LibraryFile.State.OK, f.state());
        assertFalse(f.locked());
        assertEquals("found is only reported for a newer file", 0, f.found());
        assertTrue(f.write(V1));
    }

    /** Each value of "schema_version" as it can appear in a file, and what this build (supported number 1) makes of it. */
    private static final String[][] SCHEMA_VALUES = {
            // value as written in the JSON, "ok" or "newer"
            {null, "ok"},                       // missing: every library written before this check
            {"null", "ok"},
            {"0", "ok"}, {"-1", "ok"}, {"-1e999", "ok"}, {"0.5", "ok"},
            {"1", "ok"}, {"1.0", "ok"}, {"1e0", "ok"},
            {"\"2\"", "ok"}, {"\"99\"", "ok"}, {"\"\"", "ok"}, {"true", "ok"}, {"[2]", "ok"}, {"{\"n\":2}", "ok"},  // not a number: no release wrote one
            {"2", "newer"}, {"99", "newer"}, {"2.0", "newer"}, {"1.5", "newer"}, {"1.0000001", "newer"},
            {"9999999999999999999999", "newer"}, {"1e308", "newer"},  // huge
            {"1e999", "newer"},  // verified on the JVM org.json of these unit tests only, NOT on Android's own org.json (no release writes such a value)
    };

    @Test
    public void everyOddSchemaValueIsOkUnlessItIsANumberAboveWhatThisBuildReads() throws Exception {
        for (String[] c : SCHEMA_VALUES) {
            File dir = tmp.newFolder();
            String text = "{" + (c[0] == null ? "" : "\"schema_version\":" + c[0] + ",") + "\"reels\":[{\"code\":\"AAAAA1\"}]}";
            put(new File(dir, "reels.json"), text);
            LibraryFile f = LibraryFile.reels(dir);
            String got = f.read();
            boolean newer = "newer".equals(c[1]);
            assertEquals("schema_version " + c[0], newer ? LibraryFile.State.NEWER : LibraryFile.State.OK, f.state());
            assertEquals("schema_version " + c[0], newer, f.locked());
            assertEquals("schema_version " + c[0], newer ? "" : text, got);
            assertEquals("the file is untouched, newer or not", text, get(f.main));
            assertArrayEquals("nothing else appears", new String[]{"reels.json"}, names(dir));
            if (!newer) assertTrue("an ok library saves", f.write(V1));
        }
    }

    @Test
    public void theNumberReportedForANewerFileIsRoundedUpAndNeverBelowWhatIsSupported() throws Exception {
        // 1e999: verified on the JVM org.json of these unit tests only, NOT on Android's own org.json (no release writes such a value)
        String[][] cases = {{"2", "2"}, {"99", "99"}, {"1.5", "2"}, {"1.0000001", "2"}, {"1e999", String.valueOf(Long.MAX_VALUE)}};
        for (String[] c : cases) {
            File dir = tmp.newFolder();
            put(new File(dir, "reels.json"), "{\"schema_version\":" + c[0] + ",\"reels\":[]}");
            LibraryFile f = LibraryFile.reels(dir);
            f.read();
            assertEquals(c[0], Long.parseLong(c[1]), f.found());
            assertTrue(c[0], f.found() > f.supported());
        }
    }

    @Test
    public void theLibraryAndTheScreenshotListEachReadTheirOwnNumber() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{\"v\":99,\"reels\":[]}");  // "v" is the screenshot list's number, not the library's
        put(new File(dir, "shots.json"), "{\"schema_version\":99,\"v\":1,\"seen\":{},\"reels\":{}}");
        assertEquals(LibraryFile.State.OK, readState(LibraryFile.reels(dir)));
        assertEquals(LibraryFile.State.OK, readState(LibraryFile.shots(dir)));
        assertEquals(LibraryFile.REELS_SCHEMA, LibraryFile.reels(dir).supported());
        assertEquals(LibraryFile.SHOTS_SCHEMA, LibraryFile.shots(dir).supported());
    }

    @Test
    public void aScreenshotListWithANewerVIsNewerAndANewerListDoesNotLockTheLibrary() throws Exception {
        File dir = tmp.newFolder();
        String newerList = "{\"v\":2,\"seen\":{\"k\":{\"m\":1,\"newField\":true}},\"reels\":{}}";
        put(new File(dir, "shots.json"), newerList);
        put(new File(dir, "shots.json.bak"), "{\"v\":1,\"seen\":{},\"reels\":{}}");
        put(new File(dir, "reels.json"), V2);
        String[] before = names(dir);
        LibraryFile s = LibraryFile.shots(dir);
        LibraryFile.Loaded l = s.load();
        assertEquals(LibraryFile.State.NEWER, l.state);
        assertEquals("", l.text);
        assertTrue(s.locked());
        assertEquals(2, s.found());
        assertFalse(s.write("{\"v\":1,\"seen\":{},\"reels\":{}}"));
        try {
            s.startNew();
            fail("startNew must never be possible for a newer list");
        } catch (IOException expected) {
            // refused
        }
        assertEquals(newerList, get(s.main));
        assertArrayEquals(before, names(dir));
        LibraryFile r = LibraryFile.reels(dir);
        assertEquals("a newer screenshot list does not lock the library", V2, r.read());
        assertEquals(LibraryFile.State.OK, r.state());
        assertTrue(r.write(V1));
    }

    @Test
    public void aScreenshotListWithAnOkOrMissingVIsRead() throws Exception {
        for (String v : new String[]{"\"v\":1,", "\"v\":0,", ""}) {
            File dir = tmp.newFolder();
            put(new File(dir, "shots.json"), "{" + v + "\"seen\":{},\"reels\":{}}");
            assertEquals(v, LibraryFile.State.OK, readState(LibraryFile.shots(dir)));
        }
    }

    // ------------------------------------------------------------------ the released libraries (tests/fixtures/library) still read as they always did

    private static List<File> fixtureVersions() {
        File root = repoFile("tests/fixtures/library");
        List<File> out = new ArrayList<>();
        File[] all = root.listFiles(File::isDirectory);
        assertNotNull(root + " cannot be listed", all);
        for (File d : all) if (d.getName().matches("\\d+\\.\\d+\\.\\d+")) out.add(d);
        return out;
    }

    @Test
    public void everyReleasedLibraryFixtureReadsAsOkAndIsReturnedAsItIs() throws Exception {
        List<File> versions = fixtureVersions();
        assertTrue("expected the 14 released versions in tests/fixtures/library, found " + versions.size(), versions.size() >= 14);
        List<String> names = new ArrayList<>();
        for (File v : versions) names.add(v.getName());
        assertTrue("1.0.0 is in the fixtures: " + names, names.contains("1.0.0"));
        assertTrue("1.3.11 is in the fixtures: " + names, names.contains("1.3.11"));
        for (File v : versions) {
            File dir = tmp.newFolder();  // a copy: the fixture itself is never opened for writing
            for (String name : new String[]{"reels.json", "shots.json"}) {
                File src = new File(v, name);
                assertTrue(src + " is missing", src.isFile());
                Files.copy(src.toPath(), new File(dir, name).toPath());
            }
            String reels = get(new File(v, "reels.json")), shots = get(new File(v, "shots.json"));
            LibraryFile r = LibraryFile.reels(dir), s = LibraryFile.shots(dir);
            assertEquals(v.getName() + " reels.json", reels, r.read());
            assertEquals(v.getName() + " reels.json", LibraryFile.State.OK, r.state());
            assertFalse(v.getName(), r.locked());
            assertEquals(v.getName() + " shots.json", shots, s.read());
            assertEquals(v.getName() + " shots.json", LibraryFile.State.OK, s.state());
            assertFalse(v.getName(), s.locked());
            assertArrayEquals(v.getName() + ": nothing but the two files", new String[]{"reels.json", "shots.json"}, names(dir));
            assertTrue(v.getName() + " saves", r.write(reels));
        }
    }

    // ------------------------------------------------------------------ snapshots and restoring a backup (LibraryBackup)

    private File staged(String text) throws IOException {
        File f = tmp.newFile();
        put(f, text);
        return f;
    }

    private static File[] beforeRestore(File dir, String name) {
        File[] a = dir.listFiles((d, n) -> n.startsWith(name + ".before-restore-"));
        Arrays.sort(a);
        return a;
    }

    /** Every file of dir with its bytes, to show that nothing at all changed. */
    private static String fingerprint(File dir) throws IOException {
        StringBuilder b = new StringBuilder();
        for (String n : names(dir)) b.append(n).append('=').append(get(new File(dir, n))).append('\n');
        return b.toString();
    }

    @Test
    public void replaceWithKeepsTheOldFileUntouchedAndTheBackupAndAdvancesTheRevision() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        assertTrue(f.write(V2));  // main = V2, bak = V1
        long rev = f.revision();
        String restored = "{\"reels\":[{\"code\":\"RESTORED\"}]}";
        File aside = f.replaceWith(staged(restored));
        assertEquals(restored, get(f.main));
        assertEquals("the old file is kept, byte for byte", V2, get(aside));
        assertTrue(aside.getName().startsWith("reels.json.before-restore-"));
        assertEquals("the backup is untouched", V1, get(f.bak));
        assertEquals(rev + 1, f.revision());
        assertEquals(LibraryFile.State.OK, f.state());
        assertEquals("restored", f.takeNotice());
        assertFalse(f.locked());
        assertEquals(1, beforeRestore(dir, "reels.json").length);
        // a page that loaded before the restore is refused as stale and changes nothing
        LibraryFile.Result r = f.write(V1, rev);
        assertTrue(r.stale);
        assertFalse(r.ok);
        assertEquals(restored, get(f.main));
        // a page that loads now can save, and the restored file becomes the backup
        assertTrue(f.write(V2, f.revision()).ok);
        assertEquals(restored, get(f.bak));
    }

    @Test
    public void replaceWithWorksWhileTheLibraryIsUnreadableAndUnlocksIt() throws Exception {
        File dir = tmp.newFolder();
        String cut = V2.substring(0, V2.length() / 2);
        put(new File(dir, "reels.json"), cut);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertTrue(f.locked());
        long rev = f.revision();
        File aside = f.replaceWith(staged(V1));
        assertEquals("the unreadable file is set aside, never deleted", cut, get(aside));
        assertEquals(V1, get(f.main));
        assertFalse(f.locked());
        assertEquals(LibraryFile.State.OK, f.state());
        assertEquals(rev + 1, f.revision());
        assertTrue(f.write(V2, f.revision()).ok);
    }

    @Test
    public void replaceWithIsRefusedWhileTheLibraryIsNewerAndTouchesNothing() throws Exception {
        // main is newer
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        put(new File(dir, "reels.json.bak"), V1);
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertEquals(LibraryFile.State.NEWER, f.state());
        String before = fingerprint(dir);
        long rev = f.revision();
        File st = staged(V2);
        try {
            f.replaceWith(st);
            fail("a newer library must never be replaced");
        } catch (IOException expected) {
            assertTrue(expected.getMessage(), expected.getMessage().contains("newer"));
        }
        assertEquals(before, fingerprint(dir));
        assertEquals(V2, get(st));  // the staged file is not consumed either
        assertEquals(rev, f.revision());
        assertTrue(f.locked());
        assertEquals(LibraryFile.State.NEWER, f.state());
        // a damaged main beside a newer backup is the same
        File dir2 = tmp.newFolder();
        put(new File(dir2, "reels.json"), V1.substring(0, 10));
        put(new File(dir2, "reels.json.bak"), NEWER);
        LibraryFile g = LibraryFile.reels(dir2);
        g.read();
        assertEquals(LibraryFile.State.NEWER, g.state());
        String before2 = fingerprint(dir2);
        try {
            g.replaceWith(staged(V2));
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertEquals(before2, fingerprint(dir2));
    }

    @Test
    public void savedByNewerReadsTheFileOnceAndOnlyANewerLibrarySaysYesAndNothingIsChanged() throws Exception {
        File newer = tmp.newFolder();
        put(new File(newer, "reels.json"), NEWER);
        String before = fingerprint(newer);
        assertTrue("never read before: it reads the file itself", LibraryFile.reels(newer).savedByNewer());
        assertEquals(before, fingerprint(newer));
        File fine = tmp.newFolder();
        put(new File(fine, "reels.json"), V1);
        assertFalse(LibraryFile.reels(fine).savedByNewer());
        File none = tmp.newFolder();
        assertFalse("no file: a new library", LibraryFile.reels(none).savedByNewer());
        File cut = tmp.newFolder();
        put(new File(cut, "reels.json"), V1.substring(0, 12));
        LibraryFile damaged = LibraryFile.reels(cut);
        assertFalse("unreadable is not newer: restoring over it is allowed", damaged.savedByNewer());
        assertTrue(damaged.locked());
        File newerBak = tmp.newFolder();
        put(new File(newerBak, "reels.json"), V1.substring(0, 12));
        put(new File(newerBak, "reels.json.bak"), NEWER);
        assertTrue("a damaged file beside a newer backup is newer too", LibraryFile.reels(newerBak).savedByNewer());
    }

    @Test
    public void replaceWithOnALibraryNobodyReadYetStillSeesThatItIsNewer() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), NEWER);
        LibraryFile f = LibraryFile.reels(dir);  // never read: its state says nothing yet
        String before = fingerprint(dir);
        try {
            f.replaceWith(staged(V2));
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertEquals(before, fingerprint(dir));
    }

    /** What a restarted app sees: the per-process instance is forgotten, so the files on disk are read afresh. */
    @SuppressWarnings("unchecked")
    private static LibraryFile restarted(File dir, String name) throws Exception {
        java.lang.reflect.Field all = LibraryFile.class.getDeclaredField("ALL");
        all.setAccessible(true);
        synchronized (LibraryFile.class) {
            ((java.util.Map<String, LibraryFile>) all.get(null)).remove(new File(dir, name).getCanonicalPath());
        }
        return LibraryFile.reels(dir);
    }

    @Test
    public void mainIsNeverMissingWhateverGoesWrongDuringReplaceWith() throws Exception {
        for (int withBak = 0; withBak < 2; withBak++) {
            for (int kind = 0; kind < 3; kind++) {
                File dir = tmp.newFolder();
                LibraryFile f = LibraryFile.reels(dir);
                f.read();
                if (withBak == 1) assertTrue(f.write(V1));
                assertTrue(f.write(V2));
                String before = fingerprint(dir);
                long rev = f.revision();
                final int k = kind;
                final String[] seen = {null};
                f.mover = (from, to) -> {
                    // at the moment of the install, main is still there, whole, and the old file is already kept under its other name
                    seen[0] = (to.exists() ? get(to) : "MISSING") + "|" + beforeRestore(dir, "reels.json").length;
                    if (k == 0) throw new Error("killed");
                    if (k == 1) throw new IllegalStateException("boom");
                    throw new IOException("disk said no");
                };
                try {
                    f.replaceWith(staged(V1));
                    fail();
                } catch (Error | RuntimeException | IOException expected) {
                    // refused
                }
                assertEquals(V2 + "|1", seen[0]);
                assertEquals(before, fingerprint(dir));  // main, .bak and nothing else: the set-aside link is removed again
                assertEquals(rev, f.revision());
                LibraryFile again = restarted(dir, "reels.json");  // a new process
                assertEquals(V2, again.read());
                assertEquals(LibraryFile.State.OK, again.state());
            }
        }
    }

    @Test
    public void ifTheProcessDiesRightAfterTheSetAsideLinkTheLibraryIsStillThere() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        // the state a kill leaves between the two steps: the old file under its other name too, main untouched
        Files.createLink(new File(dir, "reels.json.before-restore-20260101-000000").toPath(), f.main.toPath());
        LibraryFile again = restarted(dir, "reels.json");
        assertEquals(V1, again.read());
        assertEquals(LibraryFile.State.OK, again.state());
    }

    @Test
    public void aDamagedBackupBesideAnUnreadableMainSurvivesTheRestoreAndTheNextSave() throws Exception {
        File dir = tmp.newFolder();
        String badMain = V2.substring(0, 15), badBak = V1.substring(0, 20);
        put(new File(dir, "reels.json"), badMain);
        put(new File(dir, "reels.json.bak"), badBak);
        LibraryFile f = LibraryFile.reels(dir);
        assertEquals("", f.read());
        assertEquals(LibraryFile.State.UNREADABLE, f.state());
        File aside = f.replaceWith(staged(V1));
        assertEquals(badMain, get(aside));
        assertTrue(f.write(V2, f.revision()).ok);  // the next save moves main over .bak
        File[] kept = dir.listFiles((d, n) -> n.startsWith("reels.json.bak.bad-"));
        assertEquals("the damaged backup is kept, as startNew keeps it", 1, kept.length);
        assertEquals(badBak, get(kept[0]));
        assertEquals(V1, get(f.bak));
        assertEquals(V2, get(f.main));
    }

    @Test
    public void aGoodBackupIsNotMovedByARestore() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        assertTrue(f.write(V2));
        f.replaceWith(staged("{\"reels\":[]}"));
        assertEquals(V1, get(f.bak));
        assertEquals(0, dir.listFiles((d, n) -> n.contains(".bak.bad-")).length);
    }

    @Test
    public void aSecondRestoreKeepsASecondSetAsideFileAndNeverOverwritesTheFirst() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        File a = f.replaceWith(staged(V2));
        File b = f.replaceWith(staged("{\"reels\":[]}"));
        assertTrue(!a.equals(b));
        assertEquals(V1, get(a));
        assertEquals(V2, get(b));
        assertEquals(2, beforeRestore(dir, "reels.json").length);
        assertEquals("{\"reels\":[]}", get(f.main));
    }

    @Test
    public void replaceWithOnAMissingLibraryNeedsNoSetAside() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertNull(f.replaceWith(staged(V1)));
        assertEquals(V1, get(f.main));
        assertEquals(0, beforeRestore(dir, "reels.json").length);
    }

    @Test
    public void aFailedReplaceLeavesTheFileExactlyAsItWas() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        assertTrue(f.write(V2));
        String before = fingerprint(dir);
        long rev = f.revision();
        // a staged file that is not a usable library file, a newer one, a missing one: refused before anything moves
        for (File bad : new File[]{staged("{\"reels\":{\"x\":1}}"), staged(V1 + "junk"), staged(NEWER), new File(dir, "nope")}) {
            try {
                f.replaceWith(bad);
                fail("refused: " + bad);
            } catch (IOException expected) {
                // refused
            }
        }
        assertEquals(before, fingerprint(dir));
        assertEquals(rev, f.revision());
        // the second rename fails: the set-aside file is moved back
        File st = staged(V1);
        f.mover = (from, to) -> {
            throw new IOException("disk said no");
        };
        try {
            f.replaceWith(st);
            fail();
        } catch (IOException expected) {
            assertEquals("disk said no", expected.getMessage());
        }
        assertEquals("main is back exactly as it was", V2, get(f.main));
        assertEquals(V1, get(f.bak));
        assertEquals(0, beforeRestore(dir, "reels.json").length);
        assertEquals(rev, f.revision());
        assertEquals(LibraryFile.State.OK, f.state());
        assertEquals("the staged file is still there", V1, get(st));
    }

    @Test
    public void aSnapshotIsUnchangedByALaterWriteOrReplaceWith() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile f = LibraryFile.reels(dir);
        f.read();
        assertTrue(f.write(V1));
        File work = tmp.newFolder();
        File snap = new File(work, "reels.json");
        assertTrue(f.snapshotTo(snap));
        assertTrue("a hard link where the file system allows it", Files.isSameFile(snap.toPath(), f.main.toPath()));
        assertTrue(f.write(V2));
        assertEquals(V1, get(snap));
        assertTrue(f.write("{\"reels\":[{\"code\":\"C\"}]}"));
        assertEquals(V1, get(snap));
        f.replaceWith(staged("{\"reels\":[{\"code\":\"D\"}]}"));
        assertEquals(V1, get(snap));
        // the copy fallback gives the same
        File copy = new File(work, "copy.json");
        assertTrue(f.snapshot(copy, false));
        assertFalse(Files.isSameFile(copy.toPath(), f.main.toPath()));
        assertEquals(get(f.main), get(copy));
        assertTrue(f.write(V2));
        assertEquals("{\"reels\":[{\"code\":\"D\"}]}", get(copy));
    }

    @Test
    public void aSnapshotIsRefusedWhileLockedAndHasNothingToMakeWithoutAFile() throws Exception {
        File dir = tmp.newFolder();
        LibraryFile missing = LibraryFile.reels(dir);
        missing.read();
        assertFalse(missing.snapshotTo(new File(tmp.newFolder(), "x.json")));
        File dir2 = tmp.newFolder();
        put(new File(dir2, "reels.json"), V1.substring(0, 12));
        LibraryFile unreadable = LibraryFile.reels(dir2);
        unreadable.read();
        File dest = new File(tmp.newFolder(), "x.json");
        try {
            unreadable.snapshotTo(dest);
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertFalse(dest.exists());
        File dir3 = tmp.newFolder();
        put(new File(dir3, "reels.json"), NEWER);
        LibraryFile newer = LibraryFile.reels(dir3);  // never read: it reads first
        try {
            newer.snapshotTo(dest);
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertFalse(dest.exists());
        // and it never overwrites
        File dir4 = tmp.newFolder();
        LibraryFile ok = LibraryFile.reels(dir4);
        ok.read();
        ok.write(V1);
        File there = staged("mine");
        try {
            ok.snapshotTo(there);
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertEquals("mine", get(there));
        try {
            ok.snapshot(there, false);  // the copy path too
            fail();
        } catch (IOException expected) {
            // refused
        }
        assertEquals("mine", get(there));
    }

    @Test
    public void isValidFollowsTheRulesTheLibraryIsReadWith() throws Exception {
        assertTrue(LibraryFile.isValid(staged(V1), LibraryFile.RELS));
        assertTrue(LibraryFile.isValid(staged("{}"), LibraryFile.RELS));
        assertFalse(LibraryFile.isValid(staged(V1 + "x"), LibraryFile.RELS));
        assertFalse(LibraryFile.isValid(staged(V1 + "\u0000"), LibraryFile.RELS));
        assertFalse(LibraryFile.isValid(staged("{\"reels\":{}}"), LibraryFile.RELS));
        assertFalse(LibraryFile.isValid(staged(""), LibraryFile.RELS));
        assertFalse(LibraryFile.isValid(new File(tmp.getRoot(), "none"), LibraryFile.RELS));
        assertTrue(LibraryFile.isValid(staged("{\"seen\":{},\"reels\":{}}"), LibraryFile.SHOTS));
        assertFalse(LibraryFile.isValid(staged("{\"seen\":[]}"), LibraryFile.SHOTS));
    }

    @Test
    public void loadedIsFalseUntilTheFileHasBeenReadAndAskingNeverReadsIt() throws Exception {
        File dir = tmp.newFolder();
        put(new File(dir, "reels.json"), "{\"reels\":[{\"code\":\"CUT");  // damaged, with a good backup: reading it would restore the backup and set this aside
        put(new File(dir, "reels.json.bak"), V1);
        String[] before = names(dir);
        LibraryFile f = LibraryFile.reels(dir);
        assertFalse(f.loaded());
        assertFalse(f.locked());
        assertEquals(LibraryFile.State.MISSING, f.state());  // nothing is known yet: the state says nothing about the file
        assertFalse("asking is not reading", f.loaded());
        assertArrayEquals("nothing was recovered or set aside", before, names(dir));
        f.read();
        assertTrue(f.loaded());
        File dir2 = tmp.newFolder();
        LibraryFile g = LibraryFile.shots(dir2);
        assertFalse(g.loaded());
        g.load();
        assertTrue(g.loaded());
        LibraryFile h = LibraryFile.reels(tmp.newFolder());
        assertFalse(h.loaded());
        h.savedByNewer();
        assertTrue(h.loaded());
    }

    // ------------------------------------------------------------------ the numbers here and in the page code are the same ones

    private static int numberIn(File js, String regex) throws IOException {
        Matcher m = Pattern.compile(regex, Pattern.MULTILINE).matcher(get(js));
        assertTrue(js.getName() + " has no line matching " + regex, m.find());
        return Integer.parseInt(m.group(1));
    }

    @Test
    public void theSchemaNumbersInJavaAndInThePageCodeAreEqual() throws Exception {
        File assets = repoFile("android/app-shell/app/src/main/assets/local");
        assertEquals("SCHEMA in local.js and LibraryFile.REELS_SCHEMA", LibraryFile.REELS_SCHEMA, numberIn(new File(assets, "local.js"), "^const SCHEMA = (\\d+);"));
        assertEquals("SHOTS_SCHEMA in shots.js and LibraryFile.SHOTS_SCHEMA", LibraryFile.SHOTS_SCHEMA, numberIn(new File(assets, "shots.js"), "^\\s*const SHOTS_SCHEMA = (\\d+);"));
    }
}
