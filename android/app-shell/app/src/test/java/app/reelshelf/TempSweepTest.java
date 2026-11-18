package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import org.junit.Assume;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AccessDeniedException;
import java.nio.file.DirectoryIteratorException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributeView;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import app.reelshelf.TempSweep.Busy;
import app.reelshelf.TempSweep.Entry;
import app.reelshelf.TempSweep.Folder;
import app.reelshelf.TempSweep.Reason;
import app.reelshelf.TempSweep.Verdict;

/**
 * The temp sweep deletes files, so these tests are about what it must NOT delete. The first half is the planner on plain
 * data (every rule, every way to be kept); the second half is the real sweep on real folders (links, folders that are links,
 * files that change under it, a huge folder, a folder that cannot be read, the copying lock, the library's state).
 */
public class TempSweepTest {
    private static final long HOUR = TempSweep.HOUR_MS;
    private static final long NOW = 1_800_000_000_000L;  // the injected clock: a whole second, so a file's time survives any file system
    private static final long TEN_YEARS = 3650L * 24 * HOUR;
    private static final Busy FREE = new Busy(false, 0, true, true);

    /** The design's table, written out here on purpose: widening the allowlist must show up as a change in this test. */
    private static final Object[][] ALLOWED = {
            {Folder.STAGING, "copy-1234567890123.part", 0L},
            {Folder.CACHE, "reel-video.mp4", 6 * HOUR},
            {Folder.CACHE, "reel-video-local.mp4", 6 * HOUR},
            {Folder.REEL_MEDIA, "frame0.jpg", 6 * HOUR},
            {Folder.REEL_MEDIA, "frame1.jpg", 6 * HOUR},
            {Folder.REEL_MEDIA, "frame2.jpg", 6 * HOUR},
            {Folder.REEL_MEDIA, "frame3.jpg", 6 * HOUR},
            {Folder.REEL_MEDIA, "sound.wav", 6 * HOUR},
            {Folder.FILES, "reels.json.tmp", HOUR},
            {Folder.FILES, "shots.json.tmp", HOUR},
    };

    private static Entry file(Folder folder, String name, long ageMs) {
        return new Entry(folder, name, true, false, NOW - ageMs, 100);
    }

    private static Verdict decide(Entry e) {
        return TempSweep.decide(e, NOW, FREE);
    }

    private static void assertKept(Reason why, Verdict v) {
        assertFalse(v.entry.name + " in " + v.entry.folder + " must be kept", v.delete());
        assertEquals(why, v.reason);
    }

    // ================================================================== the planner

    @Test
    public void theAllowlistIsExactlyTheDesignsTable() {
        List<String> got = new ArrayList<>();
        for (TempSweep.Rule r : TempSweep.RULES) got.add(r.folder + " " + r.name.pattern() + " " + r.minAgeMs + " " + r.guard);
        assertEquals(Arrays.asList(
                "STAGING copy-[0-9]+\\.part 0 STAGING_LOCK",
                "CACHE reel-video\\.mp4 " + 6 * HOUR + " VIDEO_READS",
                "CACHE reel-video-local\\.mp4 " + 6 * HOUR + " VIDEO_READS",
                "REEL_MEDIA frame[0-3]\\.jpg " + 6 * HOUR + " VIDEO_READS",
                "REEL_MEDIA sound\\.wav " + 6 * HOUR + " VIDEO_READS",
                "FILES reels\\.json\\.tmp " + HOUR + " REELS_LIBRARY",
                "FILES shots\\.json\\.tmp " + HOUR + " SHOTS_LIBRARY"), got);
    }

    @Test
    public void everyRowDeletesAMatchingOldFile() {
        for (Object[] row : ALLOWED) {
            Verdict v = decide(file((Folder) row[0], (String) row[1], (Long) row[2] + 1000));
            assertTrue(row[1] + " in " + row[0], v.delete());
            assertNotNull(v.rule);
        }
    }

    @Test
    public void tooYoungIsKeptAndExactlyTheMinimumAgeIsDeleted() {
        for (Object[] row : ALLOWED) {
            long min = (Long) row[2];
            Folder f = (Folder) row[0];
            String name = (String) row[1];
            if (min > 0) assertKept(Reason.TOO_YOUNG, decide(file(f, name, min - 1)));
            assertTrue(name + " at exactly its minimum age", decide(file(f, name, min)).delete());
            assertTrue(name + " one ms older", decide(file(f, name, min + 1)).delete());
        }
    }

    @Test
    public void aModifiedTimeInTheFutureIsKeptWhateverTheRule() {
        for (Object[] row : ALLOWED) {
            Folder f = (Folder) row[0];
            String name = (String) row[1];
            assertKept(Reason.FUTURE, decide(file(f, name, -1)));
            assertKept(Reason.FUTURE, decide(file(f, name, -10 * 24 * HOUR)));
            assertKept(Reason.FUTURE, TempSweep.decide(new Entry(f, name, true, false, Long.MAX_VALUE, 1), NOW, FREE));
            // a clock that was never set (1970) makes every file look like it is from the future
            assertKept(Reason.FUTURE, TempSweep.decide(new Entry(f, name, true, false, NOW - 100 * HOUR, 1), 0, FREE));
        }
        // a time so far back that now minus it overflows a long must not look old
        assertFalse(TempSweep.decide(new Entry(Folder.STAGING, "copy-1.part", true, false, Long.MIN_VALUE, 1), NOW, FREE).delete());
    }

    @Test
    public void aWrongNameIsKept() {
        String[][] near = {
                {"STAGING", "copy-.part"}, {"STAGING", "copy-12a.part"}, {"STAGING", "copy-12.part.bak"}, {"STAGING", "xcopy-12.part"},
                {"STAGING", "copy-12.partial"}, {"STAGING", "copy-12.PART"}, {"STAGING", "Copy-12.part"}, {"STAGING", "copy-12.part\n"},
                {"STAGING", "copy-١٢.part"},  // Arabic-Indic digits are not [0-9]
                {"STAGING", "copy--12.part"}, {"STAGING", "copy- 12.part"}, {"STAGING", ".copy-12.part"}, {"STAGING", "copy-12.part~"},
                {"CACHE", "reel-video.mp4.bak"}, {"CACHE", "reel-video2.mp4"}, {"CACHE", "reel-video-local.mp4.part"}, {"CACHE", "Reel-Video.mp4"},
                {"CACHE", "reel-video-.mp4"}, {"CACHE", "reel-video.mp4 "}, {"CACHE", "reel_video.mp4"}, {"CACHE", "reel-video-local-2.mp4"},
                {"REEL_MEDIA", "frame4.jpg"}, {"REEL_MEDIA", "frame10.jpg"}, {"REEL_MEDIA", "frame.jpg"}, {"REEL_MEDIA", "frame0.jpg.bak"},
                {"REEL_MEDIA", "frame0.png"}, {"REEL_MEDIA", "sound.wav.part"}, {"REEL_MEDIA", "Sound.wav"}, {"REEL_MEDIA", "sound2.wav"},
                {"FILES", "reels.json"}, {"FILES", "shots.json"}, {"FILES", "reels.json.tmp.bak"}, {"FILES", "reels.json.tmp2"},
                {"FILES", "REELS.JSON.TMP"}, {"FILES", "xreels.json.tmp"}, {"FILES", "reels.json.tmp "}, {"FILES", "other.json.tmp"},
                {"FILES", "verify-results.json.tmp"}, {"FILES", "reels.tmp"}, {"FILES", "reels.json.tmp\n"},
        };
        for (String[] n : near) {
            assertKept(Reason.UNKNOWN_NAME, decide(file(Folder.valueOf(n[0]), n[1], TEN_YEARS)));
        }
    }

    @Test
    public void aRightNameInTheWrongFolderIsKept() {
        for (Object[] row : ALLOWED) {
            for (Folder other : Folder.values()) {
                if (other == row[0]) continue;
                assertKept(Reason.UNKNOWN_NAME, decide(file(other, (String) row[1], TEN_YEARS)));
            }
        }
    }

    @Test
    public void aFolderOrAnyOtherNonFileIsKeptEvenWithTheRightName() {
        for (Object[] row : ALLOWED) {
            Entry dir = new Entry((Folder) row[0], (String) row[1], false, false, NOW - TEN_YEARS, 4096);
            assertKept(Reason.NOT_A_FILE, TempSweep.decide(dir, NOW, FREE));
        }
    }

    @Test
    public void aLinkIsKeptEvenWithTheRightNameAndAnOldTime() {
        for (Object[] row : ALLOWED) {
            Entry link = new Entry((Folder) row[0], (String) row[1], false, true, NOW - TEN_YEARS, 10);
            assertKept(Reason.SYMLINK, TempSweep.decide(link, NOW, FREE));
            Entry odd = new Entry((Folder) row[0], (String) row[1], true, true, NOW - TEN_YEARS, 10);  // both flags set: still a link
            assertKept(Reason.SYMLINK, TempSweep.decide(odd, NOW, FREE));
        }
    }

    @Test
    public void stagingIsKeptWhileASharesCopyMayBeRunning() {
        Busy busy = new Busy(true, 0, true, true);
        assertKept(Reason.STAGING_BUSY, TempSweep.decide(file(Folder.STAGING, "copy-5.part", TEN_YEARS), NOW, busy));
        assertTrue("and deleted once the sweep holds the lock", TempSweep.decide(file(Folder.STAGING, "copy-5.part", TEN_YEARS), NOW, busy.holdingStagingLock()).delete());
        for (Object[] row : ALLOWED) {
            if (row[0] == Folder.STAGING) continue;
            assertTrue("the lock is about staging only: " + row[1], TempSweep.decide(file((Folder) row[0], (String) row[1], TEN_YEARS), NOW, busy).delete());
        }
    }

    @Test
    public void theCacheFilesAreKeptWhileAVideoIsBeingRead() {
        for (int reads : new int[]{1, 2, -1}) {  // anything but 0 counts as busy
            Busy busy = new Busy(false, reads, true, true);
            for (Object[] row : ALLOWED) {
                Verdict v = TempSweep.decide(file((Folder) row[0], (String) row[1], TEN_YEARS), NOW, busy);
                if (row[0] == Folder.CACHE || row[0] == Folder.REEL_MEDIA) assertKept(Reason.VIDEO_BUSY, v);
                else assertTrue(row[1] + " is not about videos", v.delete());
            }
        }
    }

    @Test
    public void aTmpFileIsKeptUnlessItsOwnLibraryIsOk() {
        Busy reelsBad = new Busy(false, 0, false, true);
        Busy shotsBad = new Busy(false, 0, true, false);
        assertKept(Reason.LIBRARY_NOT_OK, TempSweep.decide(file(Folder.FILES, "reels.json.tmp", TEN_YEARS), NOW, reelsBad));
        assertTrue(TempSweep.decide(file(Folder.FILES, "shots.json.tmp", TEN_YEARS), NOW, reelsBad).delete());
        assertKept(Reason.LIBRARY_NOT_OK, TempSweep.decide(file(Folder.FILES, "shots.json.tmp", TEN_YEARS), NOW, shotsBad));
        assertTrue(TempSweep.decide(file(Folder.FILES, "reels.json.tmp", TEN_YEARS), NOW, shotsBad).delete());
    }

    /** Everything the app keeps that is not a temp file, in every place, ten years old and with nothing busy: none of it is on the list. */
    private static final String[] NEVER = {
            "reels.json", "shots.json", "reels.json.bak", "shots.json.bak", "reels.json.bad-20250101-000000", "reels.json.bad-20250101-000000-2",
            "shots.json.bad-x", "reels.json.before-restore-20250101-000000", "shots.json.before-restore-x", "verify-results.json",
            "verify-results.json.tmp", "shot-inbox", "video-inbox", "shot_0123456789abcdef01234567.jpg", "shot_0123456789abcdef01234567.png",
            "video_0123456789abcdef01234567.mp4", "shot_1700000000000_1.jpg", "video_1700000000000_1.mp4", "models", "x.litertlm",
            "x.litertlm.part", "speech", "vosk-model-small-en-us-0.15.zip", "vosk-model-small-en-us-0.15.zip.part", "Download", "ReelShelf",
            "app_webview", "WebView", "backup-work", "restore-staging", "manifest.json", "unknown.bin", "reel-media", "share-staging",
            "copy-1.part.bak", "reels.json.tmp.bak", "frame0.jpg.bak", "sound.wav.part", "reel-video.mp4.part", "notes.txt", "a", "x.tmp", "x.part",
    };

    @Test
    public void whatTheAppKeepsIsNeverDeletedInAnyPlaceEvenWhenVeryOld() {
        for (Folder f : Folder.values()) {
            for (String name : NEVER) {
                Verdict v = decide(file(f, name, TEN_YEARS));
                assertFalse(name + " in " + f, v.delete());
                assertEquals(name + " in " + f, Reason.UNKNOWN_NAME, v.reason);
            }
        }
    }

    @Test
    public void planGivesOneVerdictPerEntryInOrder() {
        List<Entry> listed = Arrays.asList(file(Folder.FILES, "reels.json", TEN_YEARS), file(Folder.FILES, "reels.json.tmp", TEN_YEARS),
                file(Folder.CACHE, "reel-video.mp4", 1000), file(Folder.STAGING, "copy-9.part", 5));
        List<Verdict> out = TempSweep.plan(listed, NOW, FREE);
        assertEquals(4, out.size());
        assertEquals(Arrays.asList(false, true, false, true), Arrays.asList(out.get(0).delete(), out.get(1).delete(), out.get(2).delete(), out.get(3).delete()));
        for (int i = 0; i < 4; i++) assertEquals(listed.get(i), out.get(i).entry);
    }

    // ================================================================== the sweep on real folders

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private File files;
    private File cache;
    private File staging;
    private File media;
    private final AtomicInteger reads = new AtomicInteger();

    @Before
    public void folders() throws Exception {
        files = tmp.newFolder("files");
        cache = tmp.newFolder("cache");
        staging = new File(files, "share-staging");
        media = new File(cache, "reel-media");
    }

    private File put(File dir, String name, int size, long ageMs) throws IOException {
        dir.mkdirs();
        File f = new File(dir, name);
        Files.write(f.toPath(), new byte[size]);
        assertTrue(f.setLastModified(NOW - ageMs));
        return f;
    }

    private TempSweeper.Result sweep() {
        return TempSweeper.sweep(files, cache, NOW, reads::get);
    }

    private TempSweeper.Result sweep(TempSweeper.Io io) {
        return TempSweeper.sweep(files, cache, NOW, reads::get, io);
    }

    /** Both libraries read and good (state OK), the way the page leaves them. */
    private void libraryOk() throws IOException {
        Files.write(new File(files, "reels.json").toPath(), "{\"reels\":[]}".getBytes(StandardCharsets.UTF_8));
        Files.write(new File(files, "shots.json").toPath(), "{\"v\":1,\"seen\":{},\"reels\":{}}".getBytes(StandardCharsets.UTF_8));
        LibraryFile.reels(files).read();
        LibraryFile.shots(files).read();
        assertEquals(LibraryFile.State.OK, LibraryFile.reels(files).state());
        assertEquals(LibraryFile.State.OK, LibraryFile.shots(files).state());
    }

    /** One old, matching file per row of the table, each a different size. Returns them in the order of ALLOWED. */
    private List<File> oldAllowed(long extraAge) throws IOException {
        List<File> out = new ArrayList<>();
        int size = 1;
        for (Object[] row : ALLOWED) {
            Folder f = (Folder) row[0];
            File dir = f == Folder.STAGING ? staging : f == Folder.CACHE ? cache : f == Folder.REEL_MEDIA ? media : files;
            out.add(put(dir, (String) row[1], size++, (Long) row[2] + extraAge));
        }
        return out;
    }

    private static void ageLink(Path link, long mtimeMs) throws IOException {
        Files.getFileAttributeView(link, BasicFileAttributeView.class, LinkOption.NOFOLLOW_LINKS).setTimes(FileTime.fromMillis(mtimeMs), null, null);
        long got = Files.readAttributes(link, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS).lastModifiedTime().toMillis();
        Assume.assumeTrue("this system cannot set a link's own time", got == mtimeMs);
    }

    @Test
    public void everyAllowlistedOldFileIsDeletedAndCounted() throws Exception {
        libraryOk();
        List<File> made = oldAllowed(1000);
        long bytes = 0;
        for (File f : made) bytes += f.length();
        TempSweeper.Result r = sweep();
        for (File f : made) assertFalse(f.getName() + " is gone", f.exists());
        assertEquals(made.size(), r.files);
        assertEquals(bytes, r.bytes);
        assertTrue("the library itself is not touched", new File(files, "reels.json").isFile() && new File(files, "shots.json").isFile());
    }

    @Test
    public void tooYoungFilesStayAndExactlyTheMinimumAgeGoes() throws Exception {
        libraryOk();
        List<File> young = oldAllowed(-1000);  // one second short of the minimum (the no-minimum row is then one second in the future)
        TempSweeper.Result none = sweep();
        for (File f : young) assertTrue(f.getName() + " is too young", f.exists());
        assertEquals(0, none.files);
        List<File> exact = oldAllowed(0);  // the same files, now exactly as old as their minimum
        TempSweeper.Result all = sweep();
        for (File f : exact) assertFalse(f.getName() + " at exactly the minimum", f.exists());
        assertEquals(exact.size(), all.files);
    }

    @Test
    public void aFutureModifiedTimeIsKeptByTheRealSweepToo() throws Exception {
        libraryOk();
        List<File> future = oldAllowed(-3 * 24 * HOUR);
        TempSweeper.Result r = sweep();
        for (File f : future) assertTrue(f.getName() + " (modified in the future) is kept", f.exists());
        assertEquals(0, r.files);
    }

    @Test
    public void aWrongNameAWrongFolderAndASubFolderAreKept() throws Exception {
        libraryOk();
        List<File> keep = new ArrayList<>();
        keep.add(put(files, "copy-1.part", 1, TEN_YEARS));              // right name, wrong folder
        keep.add(put(cache, "copy-1.part", 1, TEN_YEARS));
        keep.add(put(media, "copy-1.part", 1, TEN_YEARS));
        keep.add(put(staging, "reel-video.mp4", 1, TEN_YEARS));
        keep.add(put(files, "reel-video.mp4", 1, TEN_YEARS));
        keep.add(put(cache, "frame0.jpg", 1, TEN_YEARS));
        keep.add(put(cache, "reels.json.tmp", 1, TEN_YEARS));
        keep.add(put(media, "reels.json.tmp", 1, TEN_YEARS));
        keep.add(put(staging, "copy-1.part.bak", 1, TEN_YEARS));       // wrong name
        keep.add(put(staging, "copy-x.part", 1, TEN_YEARS));
        keep.add(put(media, "frame9.jpg", 1, TEN_YEARS));
        keep.add(put(cache, "reel-video.mp4.bak", 1, TEN_YEARS));
        keep.add(put(files, "reels.json.tmp.bak", 1, TEN_YEARS));
        keep.add(put(new File(staging, "sub"), "copy-2.part", 1, TEN_YEARS));  // in a sub-folder: no recursion
        keep.add(put(new File(cache, "sub"), "reel-video.mp4", 1, TEN_YEARS));
        keep.add(put(new File(media, "sub"), "frame0.jpg", 1, TEN_YEARS));
        keep.add(put(new File(files, "sub"), "reels.json.tmp", 1, TEN_YEARS));
        keep.add(put(new File(staging, "copy-5.part"), "inside.bin", 1, TEN_YEARS));  // a FOLDER with a right name, with a file in it
        File folderNamedLikeAPart = new File(staging, "copy-5.part");
        assertTrue(folderNamedLikeAPart.setLastModified(NOW - TEN_YEARS));
        TempSweeper.Result r = sweep();
        for (File f : keep) assertTrue(f.getPath() + " is kept", f.exists());
        assertTrue(folderNamedLikeAPart.isDirectory());
        assertEquals(0, r.files);
    }

    @Test
    public void aSymlinkToAnOldFileIsKeptAndTheTargetIsNotDeleted() throws Exception {
        libraryOk();
        File gallery = tmp.newFolder("gallery");
        File victim = put(gallery, "holiday.mp4", 500, TEN_YEARS);
        Path[] links = {
                new File(staging, "copy-1.part").toPath(), new File(cache, "reel-video.mp4").toPath(), new File(cache, "reel-video-local.mp4").toPath(),
                new File(media, "frame0.jpg").toPath(), new File(media, "sound.wav").toPath(), new File(files, "reels.json.tmp").toPath(),
                new File(files, "shots.json.tmp").toPath()};
        for (Path l : links) {
            l.toFile().getParentFile().mkdirs();
            try {
                Files.createSymbolicLink(l, victim.toPath());
            } catch (UnsupportedOperationException | IOException e) {
                Assume.assumeNoException("no symbolic links on this system", e);
            }
            ageLink(l, NOW - TEN_YEARS);  // the link's own time is old too: only its being a link keeps it
        }
        TempSweeper.Result r = sweep();
        for (Path l : links) assertTrue(l + " is still a link", Files.isSymbolicLink(l));
        assertTrue("the file it pointed to is untouched", victim.isFile() && victim.length() == 500);
        assertEquals(0, r.files);
    }

    @Test
    public void aFolderThatIsALinkIsNotEnteredAndItsTargetIsKept() throws Exception {
        libraryOk();
        File elsewhere = tmp.newFolder("elsewhere");
        File otherMedia = tmp.newFolder("elsewhere-media");
        File otherCache = tmp.newFolder("elsewhere-cache");
        File a = put(elsewhere, "copy-1.part", 10, TEN_YEARS);
        File b = put(otherMedia, "frame0.jpg", 10, TEN_YEARS);
        File c = put(otherCache, "reel-video.mp4", 10, TEN_YEARS);
        try {
            Files.createSymbolicLink(staging.toPath(), elsewhere.toPath());
            Files.createSymbolicLink(media.toPath(), otherMedia.toPath());
        } catch (UnsupportedOperationException | IOException e) {
            Assume.assumeNoException("no symbolic links on this system", e);
        }
        TempSweeper.Result r = sweep();
        assertTrue(a.isFile() && b.isFile());
        assertEquals(0, r.files);
        // the cache folder itself being a link is not entered either
        File linkedCache = new File(tmp.getRoot(), "cache-link");
        Files.createSymbolicLink(linkedCache.toPath(), otherCache.toPath());
        TempSweeper.Result r2 = TempSweeper.sweep(files, linkedCache, NOW, reads::get);
        assertTrue(c.isFile());
        assertEquals(0, r2.files);
    }

    @Test
    public void whileASharesCopyHoldsTheLockEveryPartFileIsKeptAndTheRestIsSwept() throws Exception {
        libraryOk();
        File p1 = put(staging, "copy-1.part", 10, TEN_YEARS);
        File p2 = put(staging, "copy-2.part", 10, TEN_YEARS);
        File cached = put(cache, "reel-video.mp4", 10, TEN_YEARS);
        CountDownLatch inside = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        Thread holder = new Thread(() -> MediaBatch.trySweepStaging(() -> {
            inside.countDown();
            try {
                release.await(20, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }));
        holder.start();
        try {
            assertTrue(inside.await(10, TimeUnit.SECONDS));
            long t0 = System.nanoTime();
            TempSweeper.Result r = sweep();
            assertTrue("it did not wait for the lock", System.nanoTime() - t0 < TimeUnit.SECONDS.toNanos(5));
            assertTrue(p1.isFile() && p2.isFile());
            assertFalse("the other folders are still swept", cached.exists());
            assertEquals(1, r.files);
        } finally {
            release.countDown();
            holder.join();
        }
        assertEquals("the next sweep, with the lock free, takes them", 2, sweep().files);
        assertFalse(p1.exists() || p2.exists());
    }

    @Test
    public void whileAVideoIsBeingReadTheCacheFilesAreKept() throws Exception {
        libraryOk();
        File v = put(cache, "reel-video.mp4", 10, TEN_YEARS);
        File l = put(cache, "reel-video-local.mp4", 10, TEN_YEARS);
        File f0 = put(media, "frame0.jpg", 10, TEN_YEARS);
        File w = put(media, "sound.wav", 10, TEN_YEARS);
        File part = put(staging, "copy-1.part", 10, TEN_YEARS);
        reads.set(1);
        TempSweeper.Result r = sweep();
        assertTrue(v.isFile() && l.isFile() && f0.isFile() && w.isFile());
        assertFalse("staging is not about videos", part.exists());
        assertEquals(1, r.files);
        reads.set(0);
        assertEquals(4, sweep().files);
        assertFalse(v.exists() || l.exists() || f0.exists() || w.exists());
    }

    @Test
    public void aLibraryThatIsNotOkKeepsItsTmpFile() throws Exception {
        File reelsTmp = put(files, "reels.json.tmp", 10, TEN_YEARS);
        File shotsTmp = put(files, "shots.json.tmp", 10, TEN_YEARS);
        // never read by this process: state MISSING
        assertEquals(0, sweep().files);
        assertTrue(reelsTmp.isFile() && shotsTmp.isFile());
        // unreadable (damaged, no backup): locked
        Files.write(new File(files, "reels.json").toPath(), "{\"reels\":[".getBytes(StandardCharsets.UTF_8));
        LibraryFile.reels(files).read();
        assertTrue(LibraryFile.reels(files).locked());
        // shots is fine, reels is not: only shots.json.tmp goes
        Files.write(new File(files, "shots.json").toPath(), "{\"v\":1,\"seen\":{},\"reels\":{}}".getBytes(StandardCharsets.UTF_8));
        LibraryFile.shots(files).read();
        TempSweeper.Result r = sweep();
        assertTrue("the damaged library's leftover may be the only other copy", reelsTmp.isFile());
        assertFalse(shotsTmp.exists());
        assertEquals(1, r.files);
        // saved by a newer Reel Shelf: locked, and its tmp stays too
        File dir2 = tmp.newFolder("files2");
        Files.write(new File(dir2, "reels.json").toPath(), "{\"schema_version\":2,\"reels\":[]}".getBytes(StandardCharsets.UTF_8));
        LibraryFile.reels(dir2).read();
        assertEquals(LibraryFile.State.NEWER, LibraryFile.reels(dir2).state());
        File newerTmp = put(dir2, "reels.json.tmp", 10, TEN_YEARS);
        assertEquals(0, TempSweeper.sweep(dir2, cache, NOW, reads::get).files);
        assertTrue(newerTmp.isFile());
    }

    @Test
    public void aFileThatChangedSizeBetweenListingAndDeleteIsKept() throws Exception {
        libraryOk();
        File grown = put(staging, "copy-1.part", 10, TEN_YEARS);
        File same = put(staging, "copy-2.part", 10, TEN_YEARS);
        TempSweeper.Result r = sweep(new TempSweeper.Io() {
            @Override
            public void afterListing(Folder folder) {
                if (folder != Folder.STAGING) return;
                try {
                    Files.write(grown.toPath(), new byte[11]);
                    grown.setLastModified(NOW - TEN_YEARS);  // the same time: only the size tells
                } catch (IOException e) {
                    throw new AssertionError(e);
                }
            }
        });
        assertTrue("it grew while we looked away", grown.isFile());
        assertFalse("the one that did not change goes", same.exists());
        assertEquals(1, r.files);
    }

    @Test
    public void aFileThatChangedTimeBetweenListingAndDeleteIsKept() throws Exception {
        libraryOk();
        File touched = put(cache, "reel-video.mp4", 10, TEN_YEARS);
        File untouched = put(cache, "reel-video-local.mp4", 10, TEN_YEARS);
        TempSweeper.Result r = sweep(new TempSweeper.Io() {
            @Override
            public void afterListing(Folder folder) {
                if (folder == Folder.CACHE) assertTrue(touched.setLastModified(NOW - 1000));  // a read just wrote to it: same size, new time
            }
        });
        assertTrue(touched.isFile());
        assertFalse(untouched.exists());
        assertEquals(1, r.files);
    }

    @Test
    public void aFileReplacedByALinkBetweenListingAndDeleteIsKeptAndTheTargetToo() throws Exception {
        libraryOk();
        File gallery = tmp.newFolder("gallery");
        File victim = put(gallery, "holiday.mp4", 500, TEN_YEARS);
        File swapped = put(staging, "copy-1.part", 10, TEN_YEARS);
        TempSweeper.Result r = sweep(new TempSweeper.Io() {
            @Override
            public void afterListing(Folder folder) {
                if (folder != Folder.STAGING) return;
                try {
                    Files.delete(swapped.toPath());
                    Files.createSymbolicLink(swapped.toPath(), victim.toPath());
                } catch (UnsupportedOperationException | IOException e) {
                    Assume.assumeNoException("no symbolic links on this system", e);
                }
            }
        });
        assertTrue(Files.isSymbolicLink(swapped.toPath()));
        assertTrue(victim.isFile() && victim.length() == 500);
        assertEquals(0, r.files);
    }

    @Test
    public void aFileThatVanishedBetweenListingAndDeleteIsNotAnError() throws Exception {
        libraryOk();
        File gone = put(staging, "copy-1.part", 10, TEN_YEARS);
        File other = put(staging, "copy-2.part", 10, TEN_YEARS);
        TempSweeper.Result r = sweep(new TempSweeper.Io() {
            @Override
            public void afterListing(Folder folder) {
                if (folder == Folder.STAGING) assertTrue(gone.delete());  // the app cleaned up after itself
            }
        });
        assertFalse(other.exists());
        assertEquals("only what this sweep deleted is counted", 1, r.files);
    }

    @Test
    public void aFileCreatedAfterTheListingIsNeverTouched() throws Exception {
        libraryOk();
        put(staging, "copy-1.part", 10, TEN_YEARS);
        File[] late = new File[3];
        sweep(new TempSweeper.Io() {
            @Override
            public void afterListing(Folder folder) {
                try {
                    if (folder == Folder.STAGING) late[0] = put(staging, "copy-99.part", 10, TEN_YEARS);  // would qualify, but was not there
                    if (folder == Folder.CACHE) late[1] = put(cache, "reel-video.mp4", 10, TEN_YEARS);
                    if (folder == Folder.FILES) late[2] = put(files, "reels.json.tmp", 10, TEN_YEARS);
                } catch (IOException e) {
                    throw new AssertionError(e);
                }
            }
        });
        for (File f : late) assertTrue(f.getName() + " appeared after the listing", f.isFile());
    }

    @Test(timeout = 60_000)
    public void aFolderOfFiftyThousandFilesIsReadUpToTheLimitOnly() throws Exception {
        staging.mkdirs();
        for (int i = 0; i < 50_000; i++) Files.createFile(new File(staging, "copy-" + i + ".part").toPath());
        long t0 = System.nanoTime();
        List<Entry> listed = TempSweeper.list(Folder.STAGING, staging, new TempSweeper.Io() {
        });
        assertNotNull(listed);
        assertEquals("at most the limit is read", 2000, listed.size());
        assertEquals(2000, TempSweeper.MAX_ENTRIES);
        TempSweeper.Result r = TempSweeper.sweep(files, cache, System.currentTimeMillis() + 60_000, reads::get);  // the staging copies have no minimum age
        long ms = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t0);
        assertEquals("the rest waits for the next run", 2000, r.files);
        assertEquals(48_000, staging.list().length);
        assertTrue("finishes quickly (took " + ms + " ms)", ms < 10_000);
    }

    @Test
    public void aFolderThatCannotBeReadKeepsEverythingInItAndNothingEscapes() throws Exception {
        libraryOk();
        File p1 = put(staging, "copy-1.part", 10, TEN_YEARS);
        File p2 = put(staging, "copy-2.part", 10, TEN_YEARS);
        File v = put(cache, "reel-video.mp4", 10, TEN_YEARS);
        File f0 = put(media, "frame0.jpg", 10, TEN_YEARS);
        File t = put(files, "reels.json.tmp", 10, TEN_YEARS);
        // 1. the folder cannot be opened (staging, cache, and files): every kind of exception
        TempSweeper.Result r = sweep(new TempSweeper.Io() {
            @Override
            public DirectoryStream<Path> open(Path dir) throws IOException {
                String n = dir.getFileName().toString();
                if (n.equals("share-staging")) throw new AccessDeniedException(dir.toString());
                if (n.equals("cache")) throw new SecurityException("denied");
                if (n.equals("files")) throw new IOException("I/O error");
                return Files.newDirectoryStream(dir);
            }
        });
        assertTrue(p1.isFile() && p2.isFile() && v.isFile() && t.isFile());
        assertFalse("a folder that could be read is still swept", f0.exists());
        assertEquals(1, r.files);
        // 2. it fails in the middle of the listing: what was listed before the error is kept too
        put(media, "frame0.jpg", 10, TEN_YEARS);
        r = sweep(new TempSweeper.Io() {
            @Override
            public DirectoryStream<Path> open(Path dir) throws IOException {
                DirectoryStream<Path> real = Files.newDirectoryStream(dir);
                return new DirectoryStream<Path>() {
                    @Override
                    public Iterator<Path> iterator() {
                        Iterator<Path> it = real.iterator();
                        return new Iterator<Path>() {
                            int given;

                            @Override
                            public boolean hasNext() {
                                if (given >= 1) throw new DirectoryIteratorException(new IOException("lost the folder"));
                                return it.hasNext();
                            }

                            @Override
                            public Path next() {
                                given++;
                                return it.next();
                            }
                        };
                    }

                    @Override
                    public void close() throws IOException {
                        real.close();
                    }
                };
            }
        });
        assertEquals("nothing is deleted anywhere when every listing fails after one entry", 0, r.files);
        assertTrue(p1.isFile() && p2.isFile() && v.isFile() && t.isFile() && new File(media, "frame0.jpg").isFile());
    }

    @Test
    public void aFolderWithNoReadPermissionKeepsEverything() throws Exception {
        libraryOk();
        File p = put(staging, "copy-1.part", 10, TEN_YEARS);
        try {
            Files.setPosixFilePermissions(staging.toPath(), PosixFilePermissions.fromString("---------"));
        } catch (UnsupportedOperationException e) {
            Assume.assumeNoException("no POSIX permissions here", e);
        }
        try {
            Assume.assumeFalse("running as a user who can read it anyway (root)", Files.isReadable(staging.toPath()));
            assertEquals(0, sweep().files);
        } finally {
            Files.setPosixFilePermissions(staging.toPath(), PosixFilePermissions.fromString("rwx------"));
        }
        assertTrue(p.isFile());
    }

    @Test
    public void aMissingFolderOrOneThatIsAPlainFileIsNotAnError() throws Exception {
        libraryOk();
        assertEquals(0, sweep().files);  // no share-staging, no reel-media yet
        File notAFolder = put(files, "share-staging", 10, TEN_YEARS);
        assertEquals(0, sweep().files);
        assertTrue(notAFolder.isFile());
    }

    @Test
    public void whatTheAppKeepsIsNeverDeletedByTheRealSweepEvenWhenVeryOldAndNothingIsBusy() throws Exception {
        libraryOk();
        String hex = "0123456789abcdef01234567";
        List<File> keep = new ArrayList<>();
        for (String n : new String[]{"reels.json", "shots.json"}) keep.add(new File(files, n));
        for (String n : new String[]{"reels.json.bak", "shots.json.bak", "reels.json.bad-20250101-000000", "shots.json.bad-20250101-000000-2",
                "reels.json.before-restore-20250101-000000", "shots.json.before-restore-x", "verify-results.json", "verify-results.json.tmp", "unknown.bin"}) {
            keep.add(put(files, n, 7, TEN_YEARS));
        }
        keep.add(put(new File(files, "shot-inbox"), "shot_" + hex + ".jpg", 7, TEN_YEARS));
        keep.add(put(new File(files, "shot-inbox"), "shot_1700000000000_2.png", 7, TEN_YEARS));
        keep.add(put(new File(files, "video-inbox"), "video_" + hex + ".mp4", 7, TEN_YEARS));
        keep.add(put(new File(files, "video-inbox"), "video_1700000000000_1.mp4", 7, TEN_YEARS));
        keep.add(put(new File(files, "models"), "m.litertlm", 7, TEN_YEARS));
        keep.add(put(new File(files, "models"), "m.litertlm.part", 7, TEN_YEARS));
        keep.add(put(new File(files, "speech/vosk-model-small-en-us-0.15/am"), "final.mdl", 7, TEN_YEARS));
        keep.add(put(new File(files, "backup-work"), "reels.json", 7, TEN_YEARS));
        keep.add(put(new File(files, "restore-staging"), "reels.json.part", 7, TEN_YEARS));
        keep.add(put(staging, "other.bin", 7, TEN_YEARS));
        keep.add(put(cache, "vosk-model-small-en-us-0.15.zip.part", 7, TEN_YEARS));
        keep.add(put(cache, "vosk-model-small-en-us-0.15.zip", 7, TEN_YEARS));
        keep.add(put(cache, "litert-engine.bin", 7, TEN_YEARS));
        keep.add(put(new File(cache, "WebView/Default"), "data_0", 7, TEN_YEARS));
        keep.add(put(media, "other.jpg", 7, TEN_YEARS));
        long[] sizes = new long[keep.size()];
        long[] times = new long[keep.size()];
        for (int i = 0; i < keep.size(); i++) {
            sizes[i] = keep.get(i).length();
            times[i] = keep.get(i).lastModified();
        }
        File ours = put(staging, "copy-3.part", 7, TEN_YEARS);  // the sweep did run
        int unknown = files.list().length + cache.list().length + media.list().length + staging.list().length - 1;  // minus ours
        TempSweeper.Result r = sweep();
        assertFalse(ours.exists());
        assertEquals(1, r.files);
        for (int i = 0; i < keep.size(); i++) {
            File f = keep.get(i);
            assertTrue(f.getPath() + " is kept", f.isFile());
            assertEquals(f.getPath(), sizes[i], f.length());
            assertEquals(f.getPath(), times[i], f.lastModified());
        }
        assertEquals("what it found that is not on the list", unknown, r.leftUnknown);
    }

    @Test
    public void theNamesMadeByTheRealCopyAreOnTheList() throws Exception {
        libraryOk();
        staging.mkdirs();
        int n = 200;
        for (int i = 0; i < n; i++) File.createTempFile("copy-", ".part", staging);  // exactly what MediaCopy does
        TempSweeper.Result r = TempSweeper.sweep(files, cache, System.currentTimeMillis() + 60_000, reads::get);
        assertEquals(n, r.files);
        assertEquals(0, staging.list().length);
    }

    // ================================================================== LibraryFile.dropTmp

    @Test
    public void dropTmpDoesNothingUnlessTheLibraryWasReadAndIsOk() throws Exception {
        AtomicBoolean ran = new AtomicBoolean();
        LibraryFile.Remover spy = f -> {
            ran.set(true);
            return true;
        };
        // not read yet (MISSING)
        File d1 = tmp.newFolder("d1");
        assertFalse(LibraryFile.reels(d1).dropTmp(spy));
        // unreadable: locked
        File d2 = tmp.newFolder("d2");
        Files.write(new File(d2, "reels.json").toPath(), "{".getBytes(StandardCharsets.UTF_8));
        LibraryFile u = LibraryFile.reels(d2);
        u.read();
        assertEquals(LibraryFile.State.UNREADABLE, u.state());
        assertFalse(u.dropTmp(spy));
        // restored from the backup (RECOVERED)
        File d3 = tmp.newFolder("d3");
        Files.write(new File(d3, "reels.json").toPath(), "{".getBytes(StandardCharsets.UTF_8));
        Files.write(new File(d3, "reels.json.bak").toPath(), "{\"reels\":[]}".getBytes(StandardCharsets.UTF_8));
        LibraryFile rec = LibraryFile.reels(d3);
        rec.read();
        assertEquals(LibraryFile.State.RECOVERED, rec.state());
        assertFalse(rec.dropTmp(spy));
        // damaged, then set aside by the user (STARTED_NEW)
        u.startNew();
        assertEquals(LibraryFile.State.STARTED_NEW, u.state());
        assertFalse(u.dropTmp(spy));
        // saved by a newer Reel Shelf
        File d4 = tmp.newFolder("d4");
        Files.write(new File(d4, "reels.json").toPath(), "{\"schema_version\":2}".getBytes(StandardCharsets.UTF_8));
        LibraryFile newer = LibraryFile.reels(d4);
        newer.read();
        assertEquals(LibraryFile.State.NEWER, newer.state());
        assertFalse(newer.dropTmp(spy));
        assertFalse("the remover was never asked", ran.get());
    }

    @Test
    public void dropTmpAsksTheRemoverAboutTheLibrarysOwnTmpWhenTheStateIsOk() throws Exception {
        libraryOk();
        File[] got = new File[1];
        assertTrue(LibraryFile.reels(files).dropTmp(f -> {
            got[0] = f;
            return true;
        }));
        assertEquals(new File(files, "reels.json.tmp"), got[0]);
        assertFalse("what the remover answers is what comes back", LibraryFile.shots(files).dropTmp(f -> false));
    }

    @Test(timeout = 20_000)
    public void dropTmpWaitsForASaveThatIsInProgress() throws Exception {
        libraryOk();
        LibraryFile lib = LibraryFile.reels(files);
        CountDownLatch holding = new CountDownLatch(1);
        CountDownLatch letGo = new CountDownLatch(1);
        Thread save = new Thread(() -> {
            synchronized (lib) {  // what a save does: it holds the library's own lock
                holding.countDown();
                try {
                    letGo.await(15, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
        });
        save.start();
        assertTrue(holding.await(10, TimeUnit.SECONDS));
        AtomicBoolean ran = new AtomicBoolean();
        Thread sweeper = new Thread(() -> {
            try {
                lib.dropTmp(f -> {
                    ran.set(true);
                    return true;
                });
            } catch (IOException e) {
                throw new AssertionError(e);
            }
        });
        sweeper.start();
        Thread.sleep(300);
        assertFalse("not while a save holds the library", ran.get());
        letGo.countDown();
        sweeper.join();
        save.join();
        assertTrue(ran.get());
    }

    @Test
    public void aRealLeftoverTmpIsDeletedThroughDropTmpAndAFreshOneIsNot() throws Exception {
        libraryOk();
        File old = put(files, "reels.json.tmp", 30, 2 * HOUR);
        File young = put(files, "shots.json.tmp", 30, HOUR - 1000);
        TempSweeper.Result r = sweep();
        assertFalse(old.exists());
        assertTrue("younger than an hour: a save may have just been cut off", young.isFile());
        assertEquals(1, r.files);
        assertEquals(30, r.bytes);
        // a save still works after the sweep, and does not leave a tmp
        assertTrue(LibraryFile.reels(files).write("{\"reels\":[{}]}"));
        assertFalse(new File(files, "reels.json.tmp").exists());
    }
}
