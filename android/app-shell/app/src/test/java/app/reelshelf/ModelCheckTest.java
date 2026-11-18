package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Random;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * The check of a model file that is already on the phone, or that the user picked: what it is called (yes, no, unknown,
 * own), the sidecar that remembers it, stopping it, and the rules for when it may start. Plain files in a temporary
 * folder; no Android, no network. A model is never deleted or replaced by any of this.
 */
public class ModelCheckTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final String COMMIT = "0123456789abcdef0123456789abcdef01234567";
    private static final int SIZE = 3 * (1 << 20) + 4321;  // several read buffers (1 MB), the last one not full

    private File dir;
    private File model;
    private byte[] good;
    private ModelCatalog.Entry row;

    @Before
    public void setUp() throws Exception {
        dir = tmp.newFolder("models");
        model = new File(dir, "tiny.litertlm");
        good = data(SIZE, 1);
        row = entryFor(good);
        Files.write(model.toPath(), good);
    }

    // ------------------------------------------------------------------ helpers

    private static byte[] data(int n, int seed) {
        byte[] b = new byte[n];
        new Random(seed).nextBytes(b);
        return b;
    }

    private static String sha(byte[] b) throws Exception {
        return ModelVerifier.hex(MessageDigest.getInstance("SHA-256").digest(b));
    }

    private static ModelCatalog.Entry entryFor(byte[] bytes, String... accepted) throws Exception {
        return new ModelCatalog.Entry("t", "tiny.litertlm", "https://huggingface.co/test/resolve/" + COMMIT + "/tiny.litertlm",
                bytes.length, sha(bytes), accepted);
    }

    private static void neverCalled() {
        fail("the check read the file when it did not have to");
    }

    private File sidecar() {
        return ModelCheck.sidecar(model);
    }

    private void writeSidecar(String text) throws IOException {
        Files.write(sidecar().toPath(), text.getBytes(StandardCharsets.UTF_8));
    }

    private static String bad(int seed) {
        return "x".repeat(seed);
    }

    // ------------------------------------------------------------------ the decision table

    @Test
    public void aPickedFileIsAlwaysOwn_neverYes_evenWhenItsHashIsTheCatalogs() {
        assertEquals(ModelCheck.OWN, ModelCheck.decide(row, row.bytes, row.sha256, true));
        assertEquals(ModelCheck.OWN, ModelCheck.decide(row, row.bytes, "0".repeat(64), true));
        assertEquals(ModelCheck.OWN, ModelCheck.decide(row, 1, null, true));
    }

    @Test
    public void aFileTheCatalogHasNoRowForIsOwn() {
        assertEquals(ModelCheck.OWN, ModelCheck.decide(null, 123, null, false));
        assertEquals(ModelCheck.OWN, ModelCheck.decide(null, 123, "0".repeat(64), false));
    }

    @Test
    public void onlyTheCatalogsOwnSizeAndFingerprintGiveYes() {
        assertEquals(ModelCheck.YES, ModelCheck.decide(row, row.bytes, row.sha256, false));
        assertEquals(ModelCheck.NO, ModelCheck.decide(row, row.bytes, "0".repeat(64), false));
        assertEquals(ModelCheck.NO, ModelCheck.decide(row, row.bytes + 1, row.sha256, false));  // cannot happen, and is never "yes"
    }

    @Test
    public void withoutAHashAWrongSizeIsAlreadyNo_theRightSizeCanOnlyBeToldByTheHash() {
        assertEquals(ModelCheck.NO, ModelCheck.decide(row, row.bytes - 1, null, false));
        assertEquals(ModelCheck.NO, ModelCheck.decide(row, 0, null, false));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.decide(row, row.bytes, null, false));
    }

    @Test
    public void anOlderGoodFingerprintIsYesWhateverItsSize_andThenASizeAloneProvesNothing() throws Exception {
        String older = "ab".repeat(32);
        ModelCatalog.Entry moved = entryFor(good, older);
        assertEquals(ModelCheck.YES, ModelCheck.decide(moved, moved.bytes - 5, older, false));
        assertEquals(ModelCheck.NO, ModelCheck.decide(moved, moved.bytes - 5, "cd".repeat(32), false));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.decide(moved, moved.bytes - 5, null, false));  // an older file may have another size
    }

    // ------------------------------------------------------------------ the sidecar

    @Test
    public void aResultIsKeptNextToTheModelAndReadBack() throws Exception {
        assertTrue(ModelCheck.write(model, new ModelCheck.Record(row.sha256, model.length(), model.lastModified(), ModelCheck.YES, false)));
        ModelCheck.Record r = ModelCheck.read(model);
        assertNotNull(r);
        assertEquals(row.sha256, r.sha256);
        assertEquals(model.length(), r.bytes);
        assertEquals(model.lastModified(), r.mtime);
        assertEquals(ModelCheck.YES, r.result);
        assertEquals(new File(model.getPath() + ".check"), sidecar());
        assertFalse(new File(sidecar().getPath() + ".tmp").exists());
    }

    @Test
    public void theResultIsReusedWhileSizeAndModifiedTimeHold_withoutReadingTheFileAgain() throws Exception {
        assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        long mtime = model.lastModified();
        byte[] other = data(SIZE, 2);  // same size, other bytes, the modified time put back: size and time are all that is looked at
        Files.write(model.toPath(), other);
        assertTrue(model.setLastModified(mtime));
        assertEquals(ModelCheck.YES, ModelCheck.known(row, model));
    }

    @Test
    public void aChangedModifiedTimeInvalidatesTheResult() throws Exception {
        assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        assertTrue(model.setLastModified(model.lastModified() + 5000));
        assertNull(ModelCheck.read(model));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));  // only a new check can tell now
    }

    @Test
    public void aChangedSizeInvalidatesTheResult() throws Exception {
        assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        long mtime = model.lastModified();
        Files.write(model.toPath(), data(SIZE + 1, 3));
        assertTrue(model.setLastModified(mtime));
        assertNull(ModelCheck.read(model));
        assertEquals(ModelCheck.NO, ModelCheck.known(row, model));  // the size alone says it is not the published file
    }

    @Test
    public void aSidecarThatIsNotWellFormedIsIgnoredAndWrittenAgain() throws Exception {
        String ok = "{\"sha256\":\"" + row.sha256 + "\",\"bytes\":" + model.length() + ",\"mtime\":" + model.lastModified() + ",\"result\":\"yes\"}";
        String[] corrupt = {
                "", "not json", "{", "[]", "null", "{\"result\":\"yes\"}", bad(5000),
                ok.replace("\"yes\"", "\"maybe\""), ok.replace(row.sha256, "ZZ" + row.sha256.substring(2)),
                ok.replace(row.sha256, row.sha256.toUpperCase()), ok.replace("\"bytes\":" + model.length(), "\"bytes\":-1"),
                ok.replace("\"bytes\":" + model.length(), "\"bytes\":\"many\""), ok.replace("\"mtime\":", "\"mtime\":\"x\",\"y\":"),
        };
        for (String c : corrupt) {
            writeSidecar(c);
            assertNull("ignored: " + c, ModelCheck.read(model));
            assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));
            assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));  // rewritten
            assertNotNull(ModelCheck.read(model));
        }
        Files.write(sidecar().toPath(), new byte[]{0, (byte) 0xff, (byte) 0xfe, 1, 2, 3});  // binary garbage
        assertNull(ModelCheck.read(model));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));
        assertTrue("the model itself is untouched", Files.readAllBytes(model.toPath()).length == SIZE);
    }

    @Test
    public void theSidecarFunctionsNeverThrow() throws Exception {
        File gone = new File(dir, "gone.litertlm");
        assertNull(ModelCheck.read(gone));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, gone));
        assertNull(ModelCheck.check(row, gone, () -> false));
        assertFalse(ModelCheck.write(new File(dir, "no-such-folder/x.litertlm"), new ModelCheck.Record("", 1, 1, ModelCheck.OWN, false)));
        assertTrue(sidecar().mkdir());  // a folder where the sidecar should be: not readable, not replaceable
        assertNull(ModelCheck.read(model));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));
        assertEquals("a verdict is still given when it cannot be remembered", ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        assertTrue("and the folder is still a folder", sidecar().isDirectory());
        File asDir = new File(dir, "folder.litertlm");
        assertTrue(asDir.mkdir());
        assertNull(ModelCheck.check(row, asDir, () -> false));
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, asDir));
        ModelCheck.forget(gone);
    }

    @Test
    public void aSidecarWrittenForAnOlderTableIsJudgedByTheTableOfNow() throws Exception {
        ModelCheck.write(model, new ModelCheck.Record(row.sha256, model.length(), model.lastModified(), ModelCheck.YES, false));
        ModelCatalog.Entry newer = new ModelCatalog.Entry("t", "tiny.litertlm", row.url, row.bytes, "9".repeat(64));
        assertEquals("the recorded word is not trusted, the fingerprint is", ModelCheck.NO, ModelCheck.known(newer, model));
        ModelCatalog.Entry newerKeepingTheOld = new ModelCatalog.Entry("t", "tiny.litertlm", row.url, row.bytes, "9".repeat(64), row.sha256);
        assertEquals(ModelCheck.YES, ModelCheck.known(newerKeepingTheOld, model));
    }

    @Test
    public void forgetRemovesOnlyTheBookkeeping() throws Exception {
        ModelCheck.check(row, model, () -> false);
        Files.write(new File(sidecar().getPath() + ".tmp").toPath(), new byte[]{1});
        ModelCheck.forget(model);
        assertFalse(sidecar().exists());
        assertFalse(new File(sidecar().getPath() + ".tmp").exists());
        assertTrue(model.isFile());
    }

    // ------------------------------------------------------------------ what the check says

    @Test
    public void thePublishedFileIsYes_andIsRecorded() throws Exception {
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));
        assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        assertEquals(ModelCheck.YES, ModelCheck.known(row, model));
        assertEquals(row.sha256, ModelCheck.read(model).sha256);
    }

    @Test
    public void oneFlippedByteIsNo_theFileIsKeptAndUntouched() throws Exception {
        byte[] damaged = good.clone();
        damaged[SIZE / 2] ^= 1;
        Files.write(model.toPath(), damaged);
        assertEquals(ModelCheck.NO, ModelCheck.check(row, model, () -> false));
        assertEquals(ModelCheck.NO, ModelCheck.known(row, model));
        assertTrue(model.isFile());
        assertArrayEquals("never deleted or changed", damaged, Files.readAllBytes(model.toPath()));
        assertEquals(ModelCheck.NO, ModelCheck.read(model).result);
    }

    @Test
    public void aFileOfAnotherSizeIsNoWithoutReadingIt() throws Exception {
        Files.write(model.toPath(), data(SIZE - 7, 4));
        assertEquals(ModelCheck.NO, ModelCheck.known(row, model));
        assertEquals(ModelCheck.NO, ModelCheck.check(row, model, () -> {
            neverCalled();
            return false;
        }));
        assertTrue(model.isFile());
    }

    @Test
    public void aFileTheCatalogHasNoRowForIsOwnWithoutReadingIt() throws Exception {
        assertEquals(ModelCheck.OWN, ModelCheck.known(null, model));
        assertEquals(ModelCheck.OWN, ModelCheck.check(null, model, () -> {
            neverCalled();
            return false;
        }));
        assertFalse("nothing to remember: it is always own", sidecar().exists());
    }

    // ------------------------------------------------------------------ stopping

    @Test
    public void aStoppedCheckEndsBeforeTheNextReadAndRecordsNothing() throws Exception {
        AtomicInteger asked = new AtomicInteger();
        assertNull(ModelCheck.check(row, model, () -> asked.incrementAndGet() > 2));
        assertEquals("it stopped at once, not at the end of the file", 3, asked.get());
        assertFalse(sidecar().exists());
        assertEquals(ModelCheck.UNKNOWN, ModelCheck.known(row, model));
        assertArrayEquals(good, Files.readAllBytes(model.toPath()));
        assertEquals("a later check is not affected", ModelCheck.YES, ModelCheck.check(row, model, () -> false));
    }

    @Test
    public void aCheckThatIsStoppedBeforeItStartsReadsNothing() {
        assertNull(ModelCheck.check(row, model, () -> true));
        assertFalse(sidecar().exists());
    }

    @Test
    public void aFileThatChangedWhileItWasReadIsNotRecorded() {
        AtomicInteger asked = new AtomicInteger();
        assertNull(ModelCheck.check(row, model, () -> {
            if (asked.incrementAndGet() == 2) {
                try {
                    Files.write(model.toPath(), data(SIZE, 5));
                } catch (IOException e) {
                    throw new IllegalStateException(e);
                }
                model.setLastModified(model.lastModified() + 7000);
            }
            return false;
        }));
        assertFalse(sidecar().exists());
    }

    // ------------------------------------------------------------------ when a check may start

    @Test
    public void aCheckStartsOnlyWhileTheAppIsOnScreen_neverAtNight_neverBesideADownloadOrAJob_notOnALowBattery() {
        assertNull(ModelCheck.refuse(true, false, false, false, 80, false));
        assertNull("unknown battery does not stop it", ModelCheck.refuse(true, false, false, false, -1, false));
        assertNotNull("the nightly run", ModelCheck.refuse(true, true, false, false, 80, true));
        assertNotNull("the nightly run, even when everything else allows it", ModelCheck.refuse(true, true, false, false, 100, true));
        assertNotNull("not on screen", ModelCheck.refuse(false, false, false, false, 80, false));
        assertNotNull("a download is running", ModelCheck.refuse(true, false, true, false, 80, false));
        assertNotNull("a job is running", ModelCheck.refuse(true, false, false, true, 80, false));
        assertNotNull("battery low", ModelCheck.refuse(true, false, false, false, ModelCheck.LOW_BATTERY - 1, false));
        assertNull("battery at the limit", ModelCheck.refuse(true, false, false, false, ModelCheck.LOW_BATTERY, false));
        assertNull("low but charging", ModelCheck.refuse(true, false, false, false, 3, true));
    }

    // ------------------------------------------------------------------ one check at a time

    private static final class Ended {
        final CountDownLatch latch = new CountDownLatch(1);
        final AtomicReference<String> verdict = new AtomicReference<>("not ended");

        void on(String v) {
            verdict.set(v);
            latch.countDown();
        }

        String await() throws InterruptedException {
            assertTrue("the check ended", latch.await(10, TimeUnit.SECONDS));
            return verdict.get();
        }
    }

    @Test
    public void aCheckThatIsStoppedWhileWaitingForTheWorkerNeverRunsAndRecordsNothing() throws Exception {
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            CountDownLatch busy = new CountDownLatch(1);
            worker.execute(() -> {
                try {
                    busy.await();
                } catch (InterruptedException ignored) {
                    // test over
                }
            });
            ModelCheck.Runner runner = new ModelCheck.Runner();
            Ended ended = new Ended();
            assertTrue(runner.start(worker, row, model, () -> true, ended::on));
            assertTrue(runner.running(model));
            assertFalse("one at a time", runner.start(worker, row, model, () -> true, v -> fail("second check")));
            runner.cancel();  // what stopAll() does
            busy.countDown();
            assertNull(ended.await());
            assertFalse(sidecar().exists());
            assertFalse(runner.running(model));
        } finally {
            worker.shutdownNow();
        }
    }

    @Test
    public void aCheckRunsOnTheWorker_endsWithItsAnswer_andAnotherMayStartAfterwards() throws Exception {
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            ModelCheck.Runner runner = new ModelCheck.Runner();
            Ended first = new Ended();
            assertTrue(runner.start(worker, row, model, () -> true, first::on));
            assertEquals(ModelCheck.YES, first.await());
            assertFalse(runner.running(model));
            Ended second = new Ended();
            assertTrue(runner.start(worker, row, model, () -> true, second::on));
            assertEquals(ModelCheck.YES, second.await());
        } finally {
            worker.shutdownNow();
        }
    }

    @Test
    public void aJobThatQueuedMeanwhileStopsTheCheckFromStarting() throws Exception {
        ExecutorService worker = Executors.newSingleThreadExecutor();
        try {
            ModelCheck.Runner runner = new ModelCheck.Runner();
            Ended ended = new Ended();
            assertTrue(runner.start(worker, row, model, () -> false, ended::on));
            assertNull(ended.await());
            assertFalse(sidecar().exists());
        } finally {
            worker.shutdownNow();
        }
    }

    @Test
    public void anExecutorThatIsGoneRefusesTheCheck() {
        ExecutorService worker = Executors.newSingleThreadExecutor();
        worker.shutdownNow();
        ModelCheck.Runner runner = new ModelCheck.Runner();
        assertFalse(runner.start(worker, row, model, () -> true, v -> fail("never started")));
        assertFalse(runner.running(model));
    }

    // ------------------------------------------------------------------ keeping using a file that failed

    @Test
    public void keepUsingItIsRememberedForThatFileOnly_andNeverForAFileThatIsNotNo() throws Exception {
        assertFalse("not checked yet: nothing to keep", ModelCheck.keep(row, model));
        assertEquals(ModelCheck.YES, ModelCheck.check(row, model, () -> false));
        assertFalse("a published file has nothing to keep", ModelCheck.keep(row, model));
        assertFalse(ModelCheck.kept(model));

        byte[] damaged = good.clone();
        damaged[10] ^= 1;
        Files.write(model.toPath(), damaged);
        assertEquals(ModelCheck.NO, ModelCheck.check(row, model, () -> false));
        assertFalse(ModelCheck.kept(model));
        assertTrue(ModelCheck.keep(row, model));
        assertTrue(ModelCheck.kept(model));
        assertEquals("still no: kept does not make it published", ModelCheck.NO, ModelCheck.known(row, model));
        assertArrayEquals(damaged, Files.readAllBytes(model.toPath()));

        assertTrue(model.setLastModified(model.lastModified() + 3000));  // another file now: asked again
        assertFalse(ModelCheck.kept(model));
    }

    @Test
    public void aFileOfTheWrongSizeCanBeKeptToo() throws Exception {
        Files.write(model.toPath(), data(SIZE - 1, 6));
        assertEquals(ModelCheck.NO, ModelCheck.known(row, model));
        assertTrue(ModelCheck.keep(row, model));
        assertTrue(ModelCheck.kept(model));
        assertEquals(ModelCheck.NO, ModelCheck.known(row, model));
    }

    // ------------------------------------------------------------------ a download, and a re-download over a damaged file

    @Test
    public void aDownloadThatPassedTheVerifierIsRecordedAsYesAndNotReadAgain() {
        ModelCheck.recordDownloaded(row, model);
        assertEquals(ModelCheck.YES, ModelCheck.known(row, model));
        assertFalse(ModelCheck.kept(model));
    }

    @Test
    public void aDamagedFileReplacedByAVerifiedDownloadIsYes_andWhatWasKeptIsForgotten() throws Exception {
        byte[] damaged = good.clone();
        damaged[99] ^= 1;
        Files.write(model.toPath(), damaged);
        assertEquals(ModelCheck.NO, ModelCheck.check(row, model, () -> false));
        assertTrue(ModelCheck.keep(row, model));
        File part = new File(model.getPath() + ".part");  // what ModelVerifier writes, then renames over the old file in one step
        Files.write(part.toPath(), good);
        assertArrayEquals("the old file stays until the new one is in place", damaged, Files.readAllBytes(model.toPath()));
        Files.move(part.toPath(), model.toPath(), java.nio.file.StandardCopyOption.ATOMIC_MOVE);
        ModelCheck.recordDownloaded(row, model);
        assertEquals(ModelCheck.YES, ModelCheck.known(row, model));
        assertFalse(ModelCheck.kept(model));
        assertArrayEquals(good, Files.readAllBytes(model.toPath()));
    }

    // ------------------------------------------------------------------ a file the user picked

    @Test
    public void aPickedFileKeepsItsOwnNameWhenFree_isMarkedOwn_andItsSizeIsRecorded() throws Exception {
        File copy = new File(dir, "picked-model.tmp");
        byte[] mine = data(2000, 7);
        Files.write(copy.toPath(), mine);
        File kept = ModelCheck.keepPicked(copy, dir, "mine.litertlm");
        assertEquals(new File(dir, "mine.litertlm"), kept);
        assertArrayEquals(mine, Files.readAllBytes(kept.toPath()));
        assertFalse("the temporary copy was moved", copy.exists());
        ModelCheck.Record r = ModelCheck.read(kept);
        assertNotNull(r);
        assertEquals(ModelCheck.OWN, r.result);
        assertEquals(2000, r.bytes);
        assertEquals(ModelCheck.OWN, ModelCheck.known(null, kept));
        assertEquals("even if a row did claim the name, the sidecar says own", ModelCheck.OWN, ModelCheck.known(row, kept));
    }

    @Test
    public void aPickedFileNeverReplacesAFileThatIsAlreadyThere() throws Exception {
        byte[] first = data(1500, 8), second = data(1600, 9), third = data(1700, 10);
        Files.write(new File(dir, "mine.litertlm").toPath(), first);
        File a = place(second, "mine.litertlm");
        File b = place(third, "mine.litertlm");
        assertEquals("mine (own).litertlm", a.getName());
        assertEquals("mine (own 2).litertlm", b.getName());
        assertArrayEquals("the file that was there is exactly as it was", first, Files.readAllBytes(new File(dir, "mine.litertlm").toPath()));
        assertArrayEquals(second, Files.readAllBytes(a.toPath()));
        assertArrayEquals(third, Files.readAllBytes(b.toPath()));
    }

    @Test
    public void aPickedFileNeverTakesAName_theCatalogUses_whetherOrNotThatModelIsOnThePhone() throws Exception {
        String catalogName = ModelCatalog.QWEN.file;
        byte[] mine = data(1000, 11);
        File a = place(mine, catalogName);  // the catalog model is not on the phone
        assertTrue(a.getName().endsWith(" (own).litertlm"));
        assertFalse(new File(dir, catalogName).exists());
        File real = new File(dir, catalogName);
        byte[] downloaded = data(1200, 12);
        Files.write(real.toPath(), downloaded);
        File b = place(mine, catalogName);  // and when it is
        assertEquals(catalogName.replace(".litertlm", " (own 2).litertlm"), b.getName());
        assertArrayEquals("the downloaded model is never touched", downloaded, Files.readAllBytes(real.toPath()));
        assertNull("no catalog row for an own name", ModelCatalog.lookup(a.getName()));
        assertEquals(ModelCheck.OWN, ModelCheck.known(ModelCatalog.lookup(b.getName()), b));
    }

    @Test
    public void aPickedNameCannotLeaveTheModelsFolder() throws Exception {
        File k = place(data(100, 13), "../../escape.litertlm");
        assertEquals(dir, k.getParentFile());
        assertEquals("escape.litertlm", k.getName());
    }

    @Test
    public void whenEveryNameIsTakenNothingIsReplacedAndTheCopyIsLeftToTheCaller() throws Exception {
        Files.write(new File(dir, "x.litertlm").toPath(), new byte[]{1});
        Files.write(new File(dir, "x (own).litertlm").toPath(), new byte[]{2});
        for (int i = 2; i < 100; i++) Files.write(new File(dir, "x (own " + i + ").litertlm").toPath(), new byte[]{3});
        File copy = new File(dir, "picked-model.tmp");
        Files.write(copy.toPath(), new byte[]{9});
        assertThrows(IOException.class, () -> ModelCheck.keepPicked(copy, dir, "x.litertlm"));
        assertTrue(copy.exists());
        assertArrayEquals(new byte[]{1}, Files.readAllBytes(new File(dir, "x.litertlm").toPath()));
        assertArrayEquals(new byte[]{2}, Files.readAllBytes(new File(dir, "x (own).litertlm").toPath()));
    }

    private File place(byte[] content, String name) throws IOException {
        File copy = new File(dir, "picked-model.tmp");
        Files.write(copy.toPath(), content);
        return ModelCheck.keepPicked(copy, dir, name);
    }
}
