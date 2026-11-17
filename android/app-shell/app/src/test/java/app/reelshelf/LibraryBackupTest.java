package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
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
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** A backup of the library: made from snapshots, checked before anything is installed, and refused whenever it cannot be trusted. */
public class LibraryBackupTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final String REELS = "{\"schema_version\":1,\"reels\":[{\"code\":\"AAAAA1\",\"note\":\"café ☃\"}],\"media\":[],\"inbox\":[]}";
    private static final String SHOTS = "{\"v\":1,\"seen\":{\"a\":1},\"reels\":{}}";
    private static final long MAX = 50L * 1024 * 1024;

    private static byte[] b(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    private File file(String content) throws IOException {
        File f = tmp.newFile();
        Files.write(f.toPath(), b(content));
        return f;
    }

    private static String sha(byte[] d) throws Exception {
        StringBuilder s = new StringBuilder();
        for (byte x : MessageDigest.getInstance("SHA-256").digest(d)) s.append(String.format("%02x", x));
        return s.toString();
    }

    /** A real backup made by LibraryBackup.write. */
    private byte[] backup(String reels, String shots) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        JSONObject counts = new JSONObject().put("reels", 1).put("titles", 0);
        LibraryBackup.write(out, file(reels), 1, shots == null ? null : file(shots), 1, counts, "1.3.17", 24, 1_700_000_000_000L);
        return out.toByteArray();
    }

    private LibraryBackup.Checked check(byte[] zip, File staging, long max) {
        return LibraryBackup.check(new ByteArrayInputStream(zip), staging, max);
    }

    private LibraryBackup.Checked check(byte[] zip) throws IOException {
        return check(zip, tmp.newFolder(), MAX);
    }

    private static String[] list(File dir) {
        String[] n = dir.list();
        Arrays.sort(n);
        return n;
    }

    /** The manifest of a correct backup of these files, for a test to damage. */
    private static JSONObject manifest(byte[] reels, byte[] shots) throws Exception {
        JSONObject files = new JSONObject();
        files.put("reels.json", new JSONObject().put("bytes", reels.length).put("sha256", sha(reels)).put("schema_version", 1));
        if (shots != null) files.put("shots.json", new JSONObject().put("bytes", shots.length).put("sha256", sha(shots)).put("schema_version", 1));
        return new JSONObject().put("format", "reelshelf-backup").put("format_version", 1).put("created_at", "2026-01-01T00:00:00Z")
                .put("app", new JSONObject().put("version_name", "x").put("version_code", 1)).put("files", files)
                .put("counts", new JSONObject()).put("contains", "x");
    }

    /** A ZIP with exactly these entries, in this order (name, bytes, name, bytes ...). */
    private static byte[] zip(Object... pairs) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (ZipOutputStream z = new ZipOutputStream(out)) {
            for (int i = 0; i < pairs.length; i += 2) {
                z.putNextEntry(new ZipEntry((String) pairs[i]));
                z.write((byte[]) pairs[i + 1]);
                z.closeEntry();
            }
        }
        return out.toByteArray();
    }

    private static byte[] mf(JSONObject m) {
        return b(m.toString());
    }

    private void refused(LibraryBackup.Code code, byte[] zip) throws Exception {
        File staging = tmp.newFolder();
        LibraryBackup.Checked c = check(zip, staging, MAX);
        assertFalse(c.message, c.ok());
        assertEquals(c.message, code, c.code);
        assertFalse("a plain sentence is given", c.message.isEmpty());
        assertTrue("it says nothing was changed: " + c.message, c.message.contains("Nothing was changed"));
        assertNull(c.reels);
        assertEquals("a refused backup leaves nothing in staging", 0, list(staging).length);
    }

    // ------------------------------------------------------------------ making and round trip

    @Test
    public void aBackupOfReelsAndShotsComesBackByteForByte() throws Exception {
        byte[] zip = backup(REELS, SHOTS);
        File staging = tmp.newFolder();
        LibraryBackup.Checked c = check(zip, staging, MAX);
        assertTrue(c.message, c.ok());
        assertArrayEquals(b(REELS), Files.readAllBytes(c.reels.toPath()));
        assertArrayEquals(b(SHOTS), Files.readAllBytes(c.shots.toPath()));
        assertEquals("2023-11-14T22:13:20Z", c.createdAt);
        assertEquals("1.3.17", c.appVersionName);
        assertEquals(24, c.appVersionCode);
        assertEquals(1, c.counts.getInt("reels"));
        assertFalse("no .part is left", Arrays.toString(list(staging)).contains(".part"));
    }

    @Test
    public void theManifestHasTheFieldsAndTheHashesAndIsWrittenLast() throws Exception {
        byte[] zip = backup(REELS, SHOTS);
        List<String> order = new ArrayList<>();
        JSONObject m = null;
        try (java.util.zip.ZipInputStream in = new java.util.zip.ZipInputStream(new ByteArrayInputStream(zip))) {
            for (ZipEntry e; (e = in.getNextEntry()) != null; ) {
                order.add(e.getName());
                if (e.getName().equals("manifest.json")) {
                    ByteArrayOutputStream o = new ByteArrayOutputStream();
                    byte[] buf = new byte[1024];
                    for (int r; (r = in.read(buf)) > 0; ) o.write(buf, 0, r);
                    m = new JSONObject(o.toString("UTF-8"));
                }
            }
        }
        assertEquals(Arrays.asList("reels.json", "shots.json", "manifest.json"), order);
        assertEquals("reelshelf-backup", m.getString("format"));
        assertEquals(1, m.getInt("format_version"));
        assertEquals("1.3.17", m.getJSONObject("app").getString("version_name"));
        assertEquals(24, m.getJSONObject("app").getInt("version_code"));
        assertTrue(m.getString("contains").contains("no settings, no API keys"));
        assertEquals(1, m.getJSONObject("counts").getInt("reels"));
        JSONObject r = m.getJSONObject("files").getJSONObject("reels.json");
        assertEquals(b(REELS).length, r.getInt("bytes"));
        assertEquals(sha(b(REELS)), r.getString("sha256"));
        assertEquals(1, r.getInt("schema_version"));
        JSONObject s = m.getJSONObject("files").getJSONObject("shots.json");
        assertEquals(b(SHOTS).length, s.getInt("bytes"));
        assertEquals(sha(b(SHOTS)), s.getString("sha256"));
    }

    @Test
    public void aBackupWithoutShotsIsFine() throws Exception {
        byte[] zip = backup(REELS, null);
        LibraryBackup.Checked c = check(zip);
        assertTrue(c.message, c.ok());
        assertNull(c.shots);
        assertArrayEquals(b(REELS), Files.readAllBytes(c.reels.toPath()));
    }

    @Test
    public void stagingIsClearedOfAnEarlierCheckAndOverwritten() throws Exception {
        File staging = tmp.newFolder();
        Files.write(new File(staging, "shots.json").toPath(), b("old"));
        LibraryBackup.Checked c = check(backup(REELS, null), staging, MAX);
        assertTrue(c.message, c.ok());
        assertFalse("the earlier shots.json is gone", new File(staging, "shots.json").exists());
    }

    // ------------------------------------------------------------------ refusals

    @Test
    public void aFileCutAtAnyPlaceBeforeTheManifestEndsIsRefused() throws Exception {
        byte[] zip = backup(REELS, SHOTS);
        int n = zip.length;
        int cd = (zip[n - 6] & 0xff) | (zip[n - 5] & 0xff) << 8 | (zip[n - 4] & 0xff) << 16 | (zip[n - 3] & 0xff) << 24;  // start of the central directory (the end record has no comment)
        assertTrue(cd > 100 && cd < n);
        for (int cut : new int[]{0, 1, 10, 30, cd / 4, cd / 2, cd * 3 / 4, cd - 20, cd - 1}) {
            File staging = tmp.newFolder();
            LibraryBackup.Checked c = check(Arrays.copyOf(zip, cut), staging, MAX);
            assertFalse("cut at " + cut + " of " + n, c.ok());
            assertEquals("cut at " + cut, 0, list(staging).length);
        }
    }

    @Test
    public void aFileThatIsNotAZipIsRefusedWithTheReasonForD4() throws Exception {
        refused(LibraryBackup.Code.NOT_A_BACKUP, b(REELS));  // a bare reels.json
        refused(LibraryBackup.Code.NOT_A_BACKUP, b("[{\"code\":\"x\",\"note\":\"y\"}]"));  // the old notes export
        refused(LibraryBackup.Code.NOT_A_BACKUP, new byte[0]);
    }

    @Test
    public void aChangedFileIsRefusedByItsHash() throws Exception {
        byte[] reels = b(REELS);
        byte[] changed = b(REELS.replace("AAAAA1", "AAAAA2"));  // the same length: only the hash tells
        assertEquals(reels.length, changed.length);
        refused(LibraryBackup.Code.FILE_MISMATCH, zip("reels.json", changed, "manifest.json", mf(manifest(reels, null))));
        // and a lying byte count
        JSONObject m = manifest(reels, null);
        m.getJSONObject("files").getJSONObject("reels.json").put("bytes", reels.length + 1);
        refused(LibraryBackup.Code.FILE_MISMATCH, zip("reels.json", reels, "manifest.json", mf(m)));
    }

    @Test
    public void anEntryTheManifestDoesNotListIsRefused() throws Exception {
        byte[] reels = b(REELS), shots = b(SHOTS);
        refused(LibraryBackup.Code.UNLISTED_FILE, zip("reels.json", reels, "shots.json", shots, "manifest.json", mf(manifest(reels, null))));
    }

    @Test
    public void anyEntryNameButTheThreeIsRefused() throws Exception {
        byte[] reels = b(REELS);
        byte[] m = mf(manifest(reels, null));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("reels.json", reels, "extra.txt", b("x"), "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("../reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("../../etc/passwd", b("x"), "reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("/reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("/data/data/app.reelshelf/files/reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("reels.json/", new byte[0], "reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("sub/", new byte[0], "reels.json", reels, "manifest.json", m));
        refused(LibraryBackup.Code.BAD_ENTRY, zip("Reels.json", reels, "manifest.json", m));
        File outside = new File(tmp.getRoot(), "evil.txt");
        assertFalse(outside.exists());
    }

    @Test
    public void anEntryTwiceIsRefused() throws Exception {
        byte[] reels = b(REELS);
        byte[] m = mf(manifest(reels, null));
        // ZipOutputStream will not write two of one name: write "reels.jsoX" and rename it in the bytes (local header and directory)
        byte[] z = zip("reels.json", reels, "reels.jsoX", reels, "manifest.json", m);
        byte[] x = b("reels.jsoX");
        for (int i = 0; i + x.length <= z.length; i++) if (Arrays.equals(Arrays.copyOfRange(z, i, i + x.length), x)) z[i + x.length - 1] = 'n';
        refused(LibraryBackup.Code.DUPLICATE_ENTRY, z);
    }

    @Test
    public void aMissingReelsFileOrManifestIsRefused() throws Exception {
        byte[] reels = b(REELS), shots = b(SHOTS);
        // the manifest lists reels.json but the file is not there
        refused(LibraryBackup.Code.FILE_MISSING, zip("shots.json", shots, "manifest.json", mf(manifest(reels, shots))));
        // a backup of shots only
        JSONObject m = manifest(reels, shots);
        m.getJSONObject("files").remove("reels.json");
        refused(LibraryBackup.Code.NO_REELS, zip("shots.json", shots, "manifest.json", mf(m)));
        refused(LibraryBackup.Code.NO_MANIFEST, zip("reels.json", reels));
    }

    @Test
    public void aBadManifestIsRefused() throws Exception {
        byte[] reels = b(REELS);
        refused(LibraryBackup.Code.BAD_MANIFEST, zip("reels.json", reels, "manifest.json", b("not json")));
        refused(LibraryBackup.Code.BAD_MANIFEST, zip("reels.json", reels, "manifest.json", b(manifest(reels, null) + " x")));
        refused(LibraryBackup.Code.BAD_MANIFEST, zip("reels.json", reels, "manifest.json", b("[1]")));
        JSONObject m = manifest(reels, null);
        m.getJSONObject("files").put("other.json", new JSONObject());
        refused(LibraryBackup.Code.BAD_MANIFEST, zip("reels.json", reels, "manifest.json", mf(m)));
    }

    @Test
    public void aWrongFormatNameOrANewerFormatVersionIsRefused() throws Exception {
        byte[] reels = b(REELS);
        refused(LibraryBackup.Code.NEWER_FORMAT, zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format_version", 2))));
        refused(LibraryBackup.Code.NEWER_FORMAT, zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format_version", 1.5))));
        refused(LibraryBackup.Code.WRONG_FORMAT, zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format", "something-else"))));
        refused(LibraryBackup.Code.WRONG_FORMAT, zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format", "REELSHELF-BACKUP"))));
        refused(LibraryBackup.Code.BAD_MANIFEST, zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format_version", "1"))));
        LibraryBackup.Checked c = check(zip("reels.json", reels, "manifest.json", mf(manifest(reels, null).put("format_version", 2))));
        assertTrue(c.message, c.message.contains("newer Reel Shelf") && c.message.contains("update"));
    }

    @Test
    public void aLibraryFromANewerReelShelfIsRefusedForReelsAndForShots() throws Exception {
        String newerReels = "{\"schema_version\":2,\"reels\":[{\"code\":\"N1\"}]}";
        byte[] shots = b(SHOTS), reels = b(REELS), nr = b(newerReels);
        refused(LibraryBackup.Code.NEWER_SCHEMA, zip("reels.json", nr, "manifest.json", mf(manifest(nr, null))));
        // even when the newer layout changed the shape
        byte[] nr2 = b("{\"schema_version\":2,\"reels\":{\"by\":\"id\"}}");
        refused(LibraryBackup.Code.NEWER_SCHEMA, zip("reels.json", nr2, "manifest.json", mf(manifest(nr2, null))));
        byte[] ns = b("{\"v\":2,\"seen\":{},\"reels\":{}}");
        refused(LibraryBackup.Code.NEWER_SCHEMA, zip("reels.json", reels, "shots.json", ns, "manifest.json", mf(manifest(reels, ns))));
        // the manifest's own number counts too
        JSONObject m = manifest(reels, shots);
        m.getJSONObject("files").getJSONObject("shots.json").put("schema_version", 2);
        refused(LibraryBackup.Code.NEWER_SCHEMA, zip("reels.json", reels, "shots.json", shots, "manifest.json", mf(m)));
        LibraryBackup.Checked c = check(zip("reels.json", nr, "manifest.json", mf(manifest(nr, null))));
        assertTrue(c.message, c.message.contains("newer Reel Shelf") && c.message.contains("update"));
    }

    @Test
    public void contentThatIsNotAValidLibraryFileIsRefused() throws Exception {
        String[] bad = {
                "{\"reels\":{\"not\":\"a list\"}}",                 // wrong shape
                "[1,2,3]",                                          // not an object
                REELS + "garbage",                                  // trailing junk
                REELS + "\u0000\u0000",                             // NUL
                "{\"reels\":[{\"code\":\"A\"",                      // cut
                "",                                                 // empty
        };
        for (String s : bad) {
            byte[] r = b(s);
            refused(LibraryBackup.Code.INVALID_CONTENT, zip("reels.json", r, "manifest.json", mf(manifest(r, null))));
        }
        byte[] reels = b(REELS), badShots = b("{\"seen\":[1]}");
        refused(LibraryBackup.Code.INVALID_CONTENT, zip("reels.json", reels, "shots.json", badShots, "manifest.json", mf(manifest(reels, badShots))));
    }

    @Test
    public void aTooBigEntryOrTooBigInAllIsRefusedAndTheLimitHoldsWhileInflating() throws Exception {
        byte[] small = b("{\"reels\":[]}" + new String(new char[48]).replace('\0', ' '));  // 60 bytes
        byte[] big = b("{\"reels\":[]}" + new String(new char[138]).replace('\0', ' '));   // 150 bytes
        File st = tmp.newFolder();
        LibraryBackup.Checked c = check(zip("reels.json", big, "manifest.json", mf(manifest(big, null))), st, 100);
        assertEquals(c.message, LibraryBackup.Code.ENTRY_TOO_BIG, c.code);
        assertEquals(0, list(st).length);
        byte[] shots = b("{\"v\":1}" + new String(new char[53]).replace('\0', ' '));  // 60 bytes
        c = check(zip("reels.json", small, "shots.json", shots, "manifest.json", mf(manifest(small, shots))), st, 100);
        assertEquals(c.message, LibraryBackup.Code.TOTAL_TOO_BIG, c.code);
        assertEquals(0, list(st).length);
        // 60 + 60 fits in 120
        c = check(zip("reels.json", small, "shots.json", shots, "manifest.json", mf(manifest(small, shots))), st, 10_000);
        assertTrue(c.message, c.ok());
        // a zip bomb: 30 MB of spaces is a few KB zipped; the limit stops it at 1 MB, whatever the ZIP says
        byte[] bomb = new byte[30 << 20];
        Arrays.fill(bomb, (byte) ' ');
        System.arraycopy(b("{\"reels\":[]}"), 0, bomb, 0, 12);
        byte[] z = zip("reels.json", bomb, "manifest.json", mf(manifest(bomb, null)));
        assertTrue("the bomb is small zipped: " + z.length, z.length < 200_000);
        c = check(z, st, 1 << 20);
        assertEquals(c.message, LibraryBackup.Code.ENTRY_TOO_BIG, c.code);
        assertEquals(0, list(st).length);
        // a manifest that is huge is refused even when the files may be as big
        byte[] bigManifest = b(manifest(small, null).put("contains", new String(new char[2 << 20]).replace('\0', 'x')).toString());
        c = check(zip("reels.json", small, "manifest.json", bigManifest), st, MAX);
        assertEquals(c.message, LibraryBackup.Code.ENTRY_TOO_BIG, c.code);
    }

    private static void le(ByteArrayOutputStream o, long v, int bytes) {
        for (int i = 0; i < bytes; i++) o.write((int) (v >> (8 * i)) & 0xff);
    }

    @Test
    public void aZipWhoseDeclaredSizeLiesIsRefused() throws Exception {
        byte[] reels = b(REELS);
        byte[] m = mf(manifest(reels, null));
        // 1. a deflated entry whose size record (in the data descriptor) says 1 byte
        byte[] z = zip("reels.json", reels, "manifest.json", m);
        boolean patched = false;
        for (int i = 0; i + 16 <= z.length; i++) {
            if (z[i] == 'P' && z[i + 1] == 'K' && z[i + 2] == 7 && z[i + 3] == 8) {
                z[i + 12] = 1; z[i + 13] = 0; z[i + 14] = 0; z[i + 15] = 0;
                patched = true;
                break;
            }
        }
        assertTrue(patched);
        File st = tmp.newFolder();
        assertFalse(check(z, st, MAX).ok());
        assertEquals(0, list(st).length);
        // 2. a stored entry that says it is 10 bytes long and holds 5000
        byte[] body = b("{\"reels\":[]}" + new String(new char[5000]).replace('\0', ' '));
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        byte[] name = b("reels.json");
        le(o, 0x04034b50L, 4); le(o, 20, 2); le(o, 0, 2); le(o, 0, 2); le(o, 0, 4);
        CRC32 crc = new CRC32();
        crc.update(body, 0, 10);
        le(o, crc.getValue(), 4); le(o, 10, 4); le(o, 10, 4); le(o, name.length, 2); le(o, 0, 2);
        o.write(name);
        o.write(body);
        assertFalse(check(o.toByteArray(), st, MAX).ok());
        assertEquals(0, list(st).length);
    }

    @Test
    public void aFailedCheckLeavesNothingInStagingWhateverTheReason() throws Exception {
        byte[] reels = b(REELS);
        File st = tmp.newFolder();
        // reels.json is staged first and fine; the manifest then fails
        LibraryBackup.Checked c = check(zip("reels.json", reels, "manifest.json", b("{")), st, MAX);
        assertFalse(c.ok());
        assertEquals(0, list(st).length);
    }

    /** A stream of a real backup that throws an Error (not an Exception) after `after` bytes, as an out-of-memory or a too deep JSON would. */
    private static java.io.InputStream failingAfter(byte[] zip, int after, Error error) {
        return new java.io.InputStream() {
            int pos;

            @Override
            public int read() {
                byte[] one = new byte[1];
                return read(one, 0, 1) < 0 ? -1 : one[0] & 0xff;
            }

            @Override
            public int read(byte[] b, int off, int len) {
                if (pos >= after) throw error;
                int n = Math.min(len, Math.min(zip.length - pos, after - pos));
                if (n <= 0) return -1;
                System.arraycopy(zip, pos, b, off, n);
                pos += n;
                return n;
            }
        };
    }

    @Test
    public void anErrorThatEscapesTheCheckStillLeavesStagingEmpty() throws Exception {
        byte[] zip = backup(REELS, SHOTS);
        int n = zip.length;
        int cd = (zip[n - 6] & 0xff) | (zip[n - 5] & 0xff) << 8 | (zip[n - 4] & 0xff) << 16 | (zip[n - 3] & 0xff) << 24;
        for (int after : new int[]{cd - 5, cd / 2, n}) {  // inside the manifest, inside the files, after everything (the content check)
            File staging = tmp.newFolder();
            try {
                LibraryBackup.check(failingAfter(zip, after, new StackOverflowError("deep")), staging, MAX);
                if (after < n) fail("the Error is rethrown, not swallowed (cut at " + after + ")");
            } catch (StackOverflowError expected) {
                // rethrown
            }
            if (after < n) assertEquals("cut at " + after + ": nothing unverified stays", 0, list(staging).length);
        }
        // an Error while the files are being judged: reels.json is staged and whole at that moment
        File staging = tmp.newFolder();
        byte[] reels = b(REELS);
        byte[] z = zip("reels.json", reels, "manifest.json", mf(manifest(reels, null)));
        try {
            LibraryBackup.check(failingAfter(z, z.length - 10, new OutOfMemoryError("big")), staging, MAX);
            fail();
        } catch (OutOfMemoryError expected) {
            // rethrown
        }
        assertEquals(0, list(staging).length);
    }

    @Test
    public void aBackupNeedsAReelsSnapshotAndTheCallersStreamStaysOpen() throws Exception {
        try {
            LibraryBackup.write(new ByteArrayOutputStream(), null, 1, null, 1, null, "v", 1, 0L);
            fail();
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage(), expected.getMessage().contains("reelsSnapshot"));
        }
        final boolean[] closed = {false};
        ByteArrayOutputStream out = new ByteArrayOutputStream() {
            @Override
            public void close() {
                closed[0] = true;
            }
        };
        LibraryBackup.write(out, file(REELS), 1, null, 1, null, "v", 1, 0L);
        assertFalse("write finishes the ZIP but leaves out open", closed[0]);
        assertTrue(check(out.toByteArray()).ok());
    }

    // ------------------------------------------------------------------ every released library

    @Test
    public void aBackupOfEveryReleasedLibraryFixtureRoundTrips() throws Exception {
        File root = repoFile("tests/fixtures/library");
        File[] versions = root.listFiles(File::isDirectory);
        int n = 0;
        for (File v : versions) {
            if (!v.getName().matches("\\d+\\.\\d+\\.\\d+")) continue;
            n++;
            File dir = tmp.newFolder();
            Files.copy(new File(v, "reels.json").toPath(), new File(dir, "reels.json").toPath());
            Files.copy(new File(v, "shots.json").toPath(), new File(dir, "shots.json").toPath());
            LibraryFile r = LibraryFile.reels(dir), s = LibraryFile.shots(dir);
            r.read();
            s.read();
            File work = tmp.newFolder();
            assertTrue(r.snapshotTo(new File(work, "reels.json")));
            assertTrue(s.snapshotTo(new File(work, "shots.json")));
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            LibraryBackup.write(out, new File(work, "reels.json"), r.supported(), new File(work, "shots.json"), s.supported(), new JSONObject(), "t", 1, 0L);
            LibraryBackup.Checked c = check(out.toByteArray());
            assertTrue(v.getName() + ": " + c.message, c.ok());
            assertArrayEquals(v.getName(), Files.readAllBytes(new File(v, "reels.json").toPath()), Files.readAllBytes(c.reels.toPath()));
            assertArrayEquals(v.getName(), Files.readAllBytes(new File(v, "shots.json").toPath()), Files.readAllBytes(c.shots.toPath()));
            // and it installs into a fresh library
            File dir2 = tmp.newFolder();
            LibraryFile r2 = LibraryFile.reels(dir2);
            r2.read();
            assertNull(r2.replaceWith(c.reels));
            assertEquals(v.getName(), new String(Files.readAllBytes(new File(v, "reels.json").toPath()), StandardCharsets.UTF_8), r2.read());
        }
        assertTrue("fixtures found: " + n, n >= 14);
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
}
