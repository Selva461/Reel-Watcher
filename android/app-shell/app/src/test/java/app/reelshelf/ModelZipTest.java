package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;
import static org.junit.Assume.assumeTrue;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * A model ZIP is unpacked only after it has been checked, only inside its own folder, and the folder that was there before
 * is never lost to a failed unpack. The ZIPs here are built in memory; some are then patched byte by byte, because the
 * things that matter (a link, a repeated name, a lying size) cannot be written with Java's own ZIP writer.
 */
public class ModelZipTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private File base;
    private File root;
    private File zip;
    private final ModelZip.Plan plan = new ModelZip.Plan("m", 10, 1000, "am", "conf");

    @Before
    public void setUp() throws Exception {
        base = tmp.newFolder("app");
        root = new File(base, "speech");
        zip = new File(base, "model.zip");
        putOldModelBack();
    }

    /** The model that is "already installed": a folder m with a model in it. */
    private void putOldModelBack() throws IOException {
        ModelZip.deleteTree(new File(root, "m").toPath());
        write(new File(root, "m/am/old.bin"), "OLD MODEL".getBytes(StandardCharsets.UTF_8));
        write(new File(root, "m/conf/old.conf"), "old conf".getBytes(StandardCharsets.UTF_8));
    }

    // ------------------------------------------------------------------ building ZIPs

    private static final class Z {
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private final ZipOutputStream out = new ZipOutputStream(bytes);

        Z file(String name, byte[] data) throws IOException {
            out.putNextEntry(new ZipEntry(name));
            out.write(data);
            out.closeEntry();
            return this;
        }

        Z file(String name, String text) throws IOException {
            return file(name, text.getBytes(StandardCharsets.UTF_8));
        }

        Z dir(String name) throws IOException {
            out.putNextEntry(new ZipEntry(name));
            out.closeEntry();
            return this;
        }

        byte[] done() throws IOException {
            out.close();
            return bytes.toByteArray();
        }
    }

    /** A small model: the folder m with the two sub-folders a model needs. */
    private static byte[] good() throws IOException {
        return new Z().dir("m/").dir("m/am/").file("m/am/final.mdl", "model data").dir("m/conf/").file("m/conf/model.conf", "conf").file("m/README", "hi").done();
    }

    private static int le16(byte[] b, int at) {
        return (b[at] & 0xFF) | (b[at + 1] & 0xFF) << 8;
    }

    private static long le32(byte[] b, int at) {
        return (b[at] & 0xFFL) | (b[at + 1] & 0xFFL) << 8 | (b[at + 2] & 0xFFL) << 16 | (b[at + 3] & 0xFFL) << 24;
    }

    private static void put32(byte[] b, int at, long v) {
        for (int i = 0; i < 4; i++) b[at + i] = (byte) (v >>> (8 * i));
    }

    /** The offsets of the central directory records. */
    private static List<Integer> records(byte[] z) {
        int eocd = z.length - 22;
        while (le32(z, eocd) != 0x06054b50L) eocd--;
        int count = le16(z, eocd + 10);
        int p = (int) le32(z, eocd + 16);
        List<Integer> at = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            at.add(p);
            p += 46 + le16(z, p + 28) + le16(z, p + 30) + le16(z, p + 32);
        }
        return at;
    }

    private static int record(byte[] z, String name) {
        for (int p : records(z)) if (new String(z, p + 46, le16(z, p + 28), StandardCharsets.ISO_8859_1).equals(name)) return p;
        throw new AssertionError("no entry " + name);
    }

    /** Marks an entry as made on Unix with this file mode (what zip -y writes for a link, for example). */
    private static byte[] unix(byte[] z, String name, int mode) {
        byte[] c = z.clone();
        int p = record(c, name);
        c[p + 4] = 20;
        c[p + 5] = 3;
        put32(c, p + 38, ((long) mode) << 16);
        return c;
    }

    /** A real-looking Unix ZIP: every entry made on Unix with the usual modes. */
    private static byte[] allUnix(byte[] z) {
        byte[] c = z.clone();
        for (int p : records(c)) {
            boolean dir = c[p + 46 + le16(c, p + 28) - 1] == '/';
            c[p + 4] = 20;
            c[p + 5] = 3;
            put32(c, p + 38, dir ? 0x41ed0010L : 0x81a40000L);
        }
        return c;
    }

    private static byte[] size(byte[] z, String name, long declared) {
        byte[] c = z.clone();
        put32(c, record(c, name) + 24, declared);
        return c;
    }

    /** Replaces every occurrence of a name (in the local headers and in the central directory); same length only. */
    private static byte[] rename(byte[] z, String from, String to) {
        assertEquals(from.length(), to.length());
        byte[] f = from.getBytes(StandardCharsets.ISO_8859_1), t = to.getBytes(StandardCharsets.ISO_8859_1);
        byte[] c = z.clone();
        int hits = 0;
        for (int i = 0; i + f.length <= c.length; i++) {
            if (Arrays.equals(Arrays.copyOfRange(c, i, i + f.length), f)) {
                System.arraycopy(t, 0, c, i, t.length);
                hits++;
            }
        }
        assertTrue("the name " + from + " is in the ZIP twice (local header and directory)", hits >= 2);
        return c;
    }

    /** Where the stored or compressed bytes of an entry start. */
    private static int dataAt(byte[] z, String name) {
        int local = (int) le32(z, record(z, name) + 42);
        return local + 30 + le16(z, local + 26) + le16(z, local + 28);
    }

    // ------------------------------------------------------------------ looking at the result

    private static void write(File f, byte[] b) throws IOException {
        Files.createDirectories(f.getParentFile().toPath());
        Files.write(f.toPath(), b);
    }

    /** Every file under dir, as "relative path = text". */
    private static TreeMap<String, String> snapshot(File dir) throws IOException {
        TreeMap<String, String> all = new TreeMap<>();
        if (!dir.exists()) return all;
        try (java.util.stream.Stream<Path> walk = Files.walk(dir.toPath())) {
            for (Path p : (Iterable<Path>) walk::iterator) {
                String rel = dir.toPath().relativize(p).toString();
                all.put(rel + (Files.isDirectory(p) ? "/" : ""), Files.isDirectory(p) ? "" : new String(Files.readAllBytes(p), StandardCharsets.UTF_8));
            }
        }
        return all;
    }

    private TreeMap<String, String> oldModel() throws IOException {
        TreeMap<String, String> t = new TreeMap<>();
        t.put("/", "");
        t.put("am/", "");
        t.put("am/old.bin", "OLD MODEL");
        t.put("conf/", "");
        t.put("conf/old.conf", "old conf");
        return t;
    }

    private void assertOldModelKept() throws IOException {
        assertEquals("the old model folder is exactly as it was", oldModel(), snapshot(new File(root, "m")));
    }

    private void assertOnlyTheModelIsInRoot() {
        assertEquals("no .unpack-* or .old-* is left", Arrays.asList("m"), names(root));
    }

    private static List<String> names(File dir) {
        String[] n = dir.list();
        List<String> l = n == null ? new ArrayList<>() : new ArrayList<>(Arrays.asList(n));
        Collections.sort(l);
        return l;
    }

    private void install(byte[] z) throws IOException {
        write(zip, z);
        ModelZip.install(zip, root, plan);
    }

    /** The ZIP is refused with exactly this message, the old model is untouched and nothing is left behind. */
    private void assertRefused(String why, byte[] z, String message) throws Exception {
        IOException e = assertThrows(why, IOException.class, () -> install(z));
        assertEquals(why, message, e.getMessage());
        assertOldModelKept();
        assertOnlyTheModelIsInRoot();
        assertFalse("nothing was written outside the unpack folder (" + why + ")", new File(base, "evil.txt").exists() || new File(root, "evil.txt").exists());
    }

    // ------------------------------------------------------------------ a ZIP that is right

    @Test
    public void aGoodZipIsUnpackedAndReplacesTheOldFolderWhole() throws Exception {
        install(good());
        TreeMap<String, String> now = snapshot(new File(root, "m"));
        assertEquals("model data", now.get("am/final.mdl"));
        assertEquals("conf", now.get("conf/model.conf"));
        assertEquals("hi", now.get("README"));
        assertFalse("nothing of the old model is mixed into the new one", now.containsKey("am/old.bin") || now.containsKey("conf/old.conf"));
        assertOnlyTheModelIsInRoot();
    }

    @Test
    public void aGoodZipUnpacksWhereThereWasNoModelAndNoRootYet() throws Exception {
        ModelZip.deleteTree(root.toPath());
        assertFalse(root.exists());
        install(good());
        assertEquals("model data", snapshot(new File(root, "m")).get("am/final.mdl"));
        assertOnlyTheModelIsInRoot();
    }

    @Test
    public void filesWithoutTheirFolderEntriesGetTheirFolders() throws Exception {
        install(new Z().file("m/am/final.mdl", "x").file("m/deep/er/still/file.txt", "y").done());
        assertEquals("y", snapshot(new File(root, "m")).get("deep/er/still/file.txt"));
    }

    @Test
    public void aRealLookingUnixZipIsAccepted() throws Exception {
        // the published speech ZIP is made on Unix: files are mode 100644, folders 40755
        install(allUnix(good()));
        assertEquals("model data", snapshot(new File(root, "m")).get("am/final.mdl"));
    }

    @Test
    public void theShapeOfThePublishedSpeechZipPassesThePinnedLimits() throws Exception {
        String f = ModelCatalog.SPEECH_FOLDER + "/";
        Z z = new Z();
        for (String d : new String[]{"", "am/", "graph/", "graph/phones/", "conf/", "ivector/"}) z.dir(f + d);
        for (String n : new String[]{"am/final.mdl", "graph/disambig_tid.int", "graph/HCLr.fst", "graph/Gr.fst", "graph/phones/word_boundary.int",
                "conf/model.conf", "conf/mfcc.conf", "ivector/splice.conf", "ivector/final.dubm", "ivector/global_cmvn.stats",
                "ivector/final.ie", "ivector/online_cmvn.conf", "ivector/final.mat", "README"}) z.file(f + n, "x");
        byte[] real = allUnix(z.done());
        assertEquals("the published ZIP holds 20 entries", ModelCatalog.SPEECH_ENTRIES, records(real).size());
        write(zip, real);
        ModelZip.install(zip, root, ModelCatalog.SPEECH_ZIP);
        assertTrue(new File(root, ModelCatalog.SPEECH_FOLDER + "/am/final.mdl").isFile());
    }

    // ------------------------------------------------------------------ names that leave the folder (zip-slip)

    @Test
    public void everyNameThatLeavesTheFolderIsRefused() throws Exception {
        String[] bad = {"../evil.txt", "m/../../evil.txt", "m/a/../../../evil.txt", "/evil.txt", "/tmp/evil.txt", "m/../evil.txt",
                "m\\..\\evil.txt", "..\\evil.txt", "C:/evil.txt", "m/C:/evil.txt", "m/./x", "m//x", "m/a/./b", "other/x", "m", "mm/x",
                "m/a\u0000b", "m/\u00e9.txt", "m/tab\tname", "../evil/", "m/../evil/", "m/..", "m/../"};
        for (String name : bad) {
            Z z = new Z().dir("m/").dir("m/am/");
            if (name.endsWith("/")) z.dir(name);
            else z.file(name, "x");
            assertRefused("name " + name.replace("\u0000", "\\0"), z.done(), ModelZip.UNSAFE);
        }
    }

    @Test
    public void safeNamesAreOnlyPlainPathsInsideTheFolder() {
        for (String ok : new String[]{"m/a", "m/a/", "m/a/b.c", "m/a-b_c.d+e f", "m/.hidden", "m/..x", "m/x.."}) assertTrue(ok, ModelZip.safeName(ok, "m"));
        for (String no : new String[]{"", "m", "/m/a", "m/../a", "m/a/..", "m/a/../", "m/./a", "m//a", "m\\a", "m/a:b", "n/a", "m/a\u0001"}) assertFalse(no, ModelZip.safeName(no, "m"));
    }

    // ------------------------------------------------------------------ links and special files

    @Test
    public void aLinkOrAnySpecialFileIsRefused() throws Exception {
        int[] modes = {0120777, 0120644, 0010644, 0020644, 0060644, 0140644};  // link, link, pipe, char device, block device, socket
        for (int mode : modes) {
            byte[] z = new Z().dir("m/").dir("m/am/").file("m/am/final.mdl", "x").file("m/link", "../../evil.txt").done();
            assertRefused("mode " + Integer.toOctalString(mode), unix(z, "m/link", mode), ModelZip.UNSAFE);
        }
    }

    @Test
    public void aLinkIsRefusedEvenWhenItPointsInsideTheFolder() throws Exception {
        byte[] z = new Z().dir("m/").dir("m/am/").file("m/am/final.mdl", "x").file("m/link", "am/final.mdl").done();
        assertRefused("a link inside", unix(z, "m/link", 0120777), ModelZip.UNSAFE);
    }

    // ------------------------------------------------------------------ repeated names

    @Test
    public void aRepeatedNameIsRefused() throws Exception {
        byte[] files = rename(new Z().dir("m/").dir("m/am/").file("m/a.txt", "first").file("m/b.txt", "second").done(), "m/b.txt", "m/a.txt");
        assertRefused("same file twice", files, ModelZip.UNSAFE);
        byte[] dirs = rename(new Z().dir("m/").dir("m/am/").dir("m/d1/").dir("m/d2/").done(), "m/d2/", "m/d1/");
        assertRefused("same folder twice", dirs, ModelZip.UNSAFE);
        byte[] mixed = rename(new Z().dir("m/").dir("m/am/").file("m/yy", "file").dir("m/yz/").done(), "m/yz/", "m/yy/");
        assertRefused("a file and a folder with one name", mixed, ModelZip.UNSAFE);
    }

    // ------------------------------------------------------------------ too many entries, too much data

    @Test
    public void moreEntriesThanThePlanAllowsAreRefused_exactlyTheLimitIsFine() throws Exception {
        Z z = new Z().dir("m/").dir("m/am/");  // 2 entries
        for (int i = 0; i < 8; i++) z.file("m/f" + i, "x");  // 10 in all: the limit
        install(z.done());
        assertEquals("x", snapshot(new File(root, "m")).get("f7"));

        putOldModelBack();
        Z more = new Z().dir("m/").dir("m/am/");
        for (int i = 0; i < 9; i++) more.file("m/f" + i, "x");  // 11
        assertRefused("11 entries", more.done(), ModelZip.TOO_BIG);
    }

    @Test
    public void moreDataThanThePlanAllowsIsRefused_exactlyTheLimitIsFine() throws Exception {
        byte[] sixHundred = new byte[600];
        Arrays.fill(sixHundred, (byte) 'a');
        install(new Z().dir("m/").dir("m/am/").file("m/a", sixHundred).file("m/b", Arrays.copyOf(sixHundred, 400)).done());  // 1000: the limit
        assertEquals(600, snapshot(new File(root, "m")).get("a").length());

        putOldModelBack();
        assertRefused("1001 bytes in two files", new Z().dir("m/").dir("m/am/").file("m/a", sixHundred).file("m/b", Arrays.copyOf(sixHundred, 401)).done(), ModelZip.TOO_BIG);
    }

    @Test
    public void aZipBombIsRefusedByItsDeclaredSize() throws Exception {
        byte[] zeros = new byte[2_000_000];  // a few KB as a ZIP, 2 MB unpacked
        byte[] z = new Z().dir("m/").dir("m/am/").file("m/zeros", zeros).done();
        assertTrue("the bomb is small as a ZIP", z.length < 20_000);
        assertRefused("a bomb", z, ModelZip.TOO_BIG);
    }

    @Test
    public void aZipThatLiesAboutItsSizeIsStoppedByTheBytesReallyWritten() throws Exception {
        byte[] z = new Z().dir("m/").dir("m/am/").file("m/zeros", new byte[2_000_000]).done();
        byte[] lying = size(z, "m/zeros", 10);  // the directory says 10 bytes, the data inflates to 2 MB
        IOException e = assertThrows(IOException.class, () -> install(lying));
        assertTrue(e.getMessage(), e.getMessage().equals(ModelZip.TOO_BIG) || e.getMessage().equals(ModelZip.BROKEN));
        assertOldModelKept();
        assertOnlyTheModelIsInRoot();
    }

    // ------------------------------------------------------------------ a ZIP that is not whole

    @Test
    public void aTruncatedOrDamagedZipIsRefused() throws Exception {
        byte[] g = good();
        assertRefused("cut in the middle", Arrays.copyOf(g, g.length / 2), ModelZip.BROKEN);
        assertRefused("without its last bytes", Arrays.copyOf(g, g.length - 5), ModelZip.BROKEN);
        assertRefused("without the end record", Arrays.copyOf(g, g.length - 22), ModelZip.BROKEN);
        assertRefused("empty", new byte[0], ModelZip.BROKEN);
        assertRefused("ten bytes of nothing", new byte[10], ModelZip.BROKEN);
        assertRefused("not a ZIP at all", "<html>Please sign in to the Wi-Fi</html>".repeat(5).getBytes(StandardCharsets.UTF_8), ModelZip.BROKEN);
        byte[] none = new byte[22];
        none[0] = 'P';
        none[1] = 'K';
        none[2] = 5;
        none[3] = 6;
        assertRefused("a ZIP with no entries", none, ModelZip.BROKEN);
    }

    @Test
    public void anEntryThatCannotBeInflatedIsRefused() throws Exception {
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < 20; i++) text.append("some words that compress well ");
        byte[] z = new Z().dir("m/").dir("m/am/").file("m/am/final.mdl", text.toString()).done();
        byte[] broken = z.clone();
        broken[dataAt(broken, "m/am/final.mdl")] = 0x07;  // a deflate block of the forbidden type
        assertRefused("a broken deflate stream", broken, ModelZip.BROKEN);
    }

    @Test
    public void aFolderThatIsNotAModelIsRefused() throws Exception {
        assertRefused("neither am nor conf", new Z().dir("m/").file("m/README", "just a readme").done(), ModelZip.BROKEN);
        assertRefused("am is a file, not a folder", new Z().dir("m/").file("m/am", "not a folder").done(), ModelZip.BROKEN);
    }

    // ------------------------------------------------------------------ the old model

    @Test
    public void theOldModelIsDeletedOnlyAfterTheNewOneIsInPlace() throws Exception {
        List<String> seen = new ArrayList<>();
        ModelZip.Mover spy = (from, to) -> {
            // at each step: is the old model still somewhere on disk, and is the new one in its place yet?
            boolean oldKept = false;
            for (String n : names(root)) if (n.startsWith(ModelZip.OLD)) oldKept = new File(new File(root, n), "am/old.bin").isFile();
            boolean oldInPlace = new File(root, "m/am/old.bin").isFile();
            seen.add(from.getName() + "->" + to.getName().replaceAll("[0-9-]+$", "") + " old(aside=" + oldKept + ",inplace=" + oldInPlace + ")");
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE);
        };
        write(zip, good());
        ModelZip.install(zip, root, plan, spy);
        assertEquals("the old folder is set aside first, then the new one moves in", Arrays.asList(
                "m->.old old(aside=false,inplace=true)",
                "m->m old(aside=true,inplace=false)"), seen);
        assertOnlyTheModelIsInRoot();
        assertEquals("model data", snapshot(new File(root, "m")).get("am/final.mdl"));
    }

    @Test
    public void ifTheNewFolderCannotMoveInTheOldOneComesBack() throws Exception {
        int[] calls = {0};
        ModelZip.Mover failing = (from, to) -> {
            if (++calls[0] == 2) throw new IOException("disk says no");
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE);
            if (calls[0] == 3) assertTrue("the old folder was moved back", new File(to, "am/old.bin").isFile());
        };
        write(zip, good());
        IOException e = assertThrows(IOException.class, () -> ModelZip.install(zip, root, plan, failing));
        assertEquals(ModelZip.NOT_SAVED, e.getMessage());
        assertEquals(3, calls[0]);
        assertOldModelKept();
        assertOnlyTheModelIsInRoot();
    }

    @Test
    public void ifTheOldFolderCannotBeSetAsideNothingChanges() throws Exception {
        ModelZip.Mover failing = (from, to) -> {
            throw new IOException("disk says no");
        };
        write(zip, good());
        IOException e = assertThrows(IOException.class, () -> ModelZip.install(zip, root, plan, failing));
        assertEquals(ModelZip.NOT_SAVED, e.getMessage());
        assertOldModelKept();
        assertOnlyTheModelIsInRoot();
    }

    // ------------------------------------------------------------------ leftovers of a killed install

    @Test
    public void recoverRemovesTheLeftoversAndKeepsEverythingElse() throws Exception {
        write(new File(root, ".unpack-123/m/am/half.bin"), "half".getBytes(StandardCharsets.UTF_8));
        write(new File(root, ".old-1-2/am/old.bin"), "older".getBytes(StandardCharsets.UTF_8));
        write(new File(root, "keep.txt"), "not ours".getBytes(StandardCharsets.UTF_8));
        write(new File(root, ".unpackers/x"), "not ours either".getBytes(StandardCharsets.UTF_8));
        ModelZip.recover(root, "m");
        assertEquals(Arrays.asList(".unpackers", "keep.txt", "m"), names(root));
        assertOldModelKept();
    }

    @Test
    public void recoverPutsBackTheModelThatWasSetAsideWhenTheNewOneNeverArrived() throws Exception {
        ModelZip.deleteTree(new File(root, "m").toPath());
        write(new File(root, ".old-1-1/am/old.bin"), "OLDER MODEL".getBytes(StandardCharsets.UTF_8));
        write(new File(root, ".old-2-1/am/old.bin"), "OLD MODEL".getBytes(StandardCharsets.UTF_8));
        write(new File(root, ".old-2-1/conf/old.conf"), "old conf".getBytes(StandardCharsets.UTF_8));
        write(new File(root, ".unpack-9/m/am/x"), "half".getBytes(StandardCharsets.UTF_8));
        ModelZip.recover(root, "m");
        assertOldModelKept();  // the newest one came back
        assertOnlyTheModelIsInRoot();
    }

    @Test
    public void recoverOnAFolderThatIsNotThereIsHarmless() {
        ModelZip.recover(new File(base, "nothing-here"), "m");
    }

    @Test
    public void deletingALeftoverNeverFollowsALink() throws Exception {
        File outside = tmp.newFolder("outside");
        write(new File(outside, "precious.txt"), "keep me".getBytes(StandardCharsets.UTF_8));
        File leftover = new File(root, ".unpack-77");
        assertTrue(leftover.mkdirs());
        try {
            Files.createSymbolicLink(new File(leftover, "link").toPath(), outside.toPath());
        } catch (UnsupportedOperationException | IOException x) {
            assumeTrue("needs symbolic links", false);
        }
        ModelZip.recover(root, "m");
        assertFalse(leftover.exists());
        assertArrayEquals("keep me".getBytes(StandardCharsets.UTF_8), Files.readAllBytes(new File(outside, "precious.txt").toPath()));
    }
}
