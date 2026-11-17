package app.reelshelf;

import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.EOFException;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * A backup of the library: one ZIP with reels.json and shots.json (byte-for-byte copies of the files) and manifest.json
 * (written last: format, versions, and the size and SHA-256 of each file). Pure Java, tested on a computer.
 * Making a backup never parses the library (the caller passes the counts and the app version). Checking one does, once
 * per file, through {@link LibraryFile#inspect}; nothing is installed here: {@link #check} only stages the files, and
 * {@link LibraryFile#replaceWith} installs them.
 * Settings (and so API keys) are not in a backup, and there is no encryption.
 */
final class LibraryBackup {
    static final String FORMAT = "reelshelf-backup";
    static final int FORMAT_VERSION = 1;
    static final String MANIFEST = "manifest.json";
    static final String REELS = "reels.json";
    static final String SHOTS = "shots.json";
    static final String CONTAINS = "reels, notes, watchlist, quotes, products; no settings, no API keys, no pictures or videos";
    /** The manifest is a few hundred bytes; this much is plenty and keeps a bogus one from filling memory. */
    static final long MANIFEST_MAX_BYTES = 1L << 20;

    private LibraryBackup() {
    }

    // ------------------------------------------------------------------ making a backup

    /**
     * Writes the backup ZIP to out: reels, then shots (when shotsSnapshot is not null), then the manifest. The snapshots are
     * files from {@link LibraryFile#snapshotTo}, streamed through a 64 KB buffer and hashed as they go: never parsed, never
     * held whole. schema numbers, counts and the app version are the caller's (counts only to show on screen). out is
     * finished but not closed. When this throws, what was written to out is incomplete: the caller must discard it
     * (delete the half-written file). The ZipOutputStream is closed here either way (its Deflater is released), without closing out.
     * reelsSnapshot must not be null (IllegalArgumentException).
     */
    static void write(OutputStream out, File reelsSnapshot, int reelsSchema, File shotsSnapshot, int shotsSchema,
                      JSONObject counts, String versionName, int versionCode, long nowMillis) throws IOException {
        if (reelsSnapshot == null) throw new IllegalArgumentException("A backup needs the reels file: reelsSnapshot is null");
        ZipOutputStream zip = new ZipOutputStream(new java.io.FilterOutputStream(out) {
            @Override
            public void write(byte[] b, int off, int len) throws IOException {
                out.write(b, off, len);
            }

            @Override
            public void close() throws IOException {
                flush();  // out stays the caller's
            }
        });
        zip.setLevel(java.util.zip.Deflater.DEFAULT_COMPRESSION);
        JSONObject files = new JSONObject();
        try {
            files.put(REELS, addFile(zip, REELS, reelsSnapshot, reelsSchema));
            if (shotsSnapshot != null) files.put(SHOTS, addFile(zip, SHOTS, shotsSnapshot, shotsSchema));
            SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT);
            iso.setTimeZone(TimeZone.getTimeZone("UTC"));
            JSONObject app = new JSONObject();
            app.put("version_name", versionName);
            app.put("version_code", versionCode);
            JSONObject m = new JSONObject();
            m.put("format", FORMAT);
            m.put("format_version", FORMAT_VERSION);
            m.put("created_at", iso.format(new Date(nowMillis)));
            m.put("app", app);
            m.put("files", files);
            m.put("counts", counts == null ? new JSONObject() : counts);
            m.put("contains", CONTAINS);
            zip.putNextEntry(new ZipEntry(MANIFEST));
            zip.write(m.toString().getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
            zip.finish();
            zip.flush();
        } catch (org.json.JSONException e) {
            throw new IOException(e);
        } finally {
            try {
                zip.close();  // releases the Deflater; after a failure the caller discards the output anyway
            } catch (IOException ignored) {
                // the original failure, if any, is the one that matters
            }
        }
    }

    private static JSONObject addFile(ZipOutputStream zip, String name, File f, int schema) throws IOException, org.json.JSONException {
        MessageDigest md = sha256();
        long n = 0;
        byte[] buf = new byte[64 * 1024];
        zip.putNextEntry(new ZipEntry(name));
        try (InputStream in = Files.newInputStream(f.toPath())) {
            for (int r; (r = in.read(buf)) > 0; ) {
                md.update(buf, 0, r);
                zip.write(buf, 0, r);
                n += r;
            }
        }
        zip.closeEntry();
        JSONObject o = new JSONObject();
        o.put("bytes", n);
        o.put("sha256", hex(md.digest()));
        o.put("schema_version", schema);
        return o;
    }

    // ------------------------------------------------------------------ checking one

    /** Why a backup was refused. The page can pick its own words by code; {@link Checked#message} is a plain sentence. */
    enum Code {
        OK, NOT_A_BACKUP, CORRUPT, IO_ERROR, BAD_ENTRY, DUPLICATE_ENTRY, ENTRY_TOO_BIG, TOTAL_TOO_BIG, NO_MANIFEST, BAD_MANIFEST,
        WRONG_FORMAT, NEWER_FORMAT, UNLISTED_FILE, NO_REELS, FILE_MISSING, FILE_MISMATCH, NEWER_SCHEMA, INVALID_CONTENT
    }

    /** The answer of {@link #check}: accepted (the staged files are in place) or refused with a code and a sentence. */
    static final class Checked {
        final Code code;
        final String message;
        /** The staged files (null when refused; shots is null when the backup has none). */
        final File reels;
        final File shots;
        /** From the manifest, for the confirm screen (empty or 0 when refused). */
        final String createdAt;
        final String appVersionName;
        final long appVersionCode;
        final JSONObject counts;

        private Checked(Code code, String message, File reels, File shots, String createdAt, String appVersionName, long appVersionCode, JSONObject counts) {
            this.code = code;
            this.message = message;
            this.reels = reels;
            this.shots = shots;
            this.createdAt = createdAt;
            this.appVersionName = appVersionName;
            this.appVersionCode = appVersionCode;
            this.counts = counts;
        }

        boolean ok() {
            return code == Code.OK;
        }

        boolean hasShots() {
            return shots != null;
        }
    }

    private static final class Refused extends Exception {
        final Code code;

        Refused(Code code, String message) {
            super(message);
            this.code = code;
        }
    }

    /**
     * Reads a backup from in and stages it in the folder staging (created when missing; whatever was in it from an
     * earlier check is cleared first). Each entry is streamed to NAME.part, hashed as it goes, and renamed to NAME when
     * whole; the number of bytes is counted while inflating and the declared sizes are never trusted. Refuses:
     * an entry name that is not exactly manifest.json, reels.json or shots.json (zip-slip, directories, extras), an entry
     * twice, an entry bigger than maxBytes, more than maxBytes in all (a zip bomb stops at the limit), a damaged or
     * truncated ZIP, a missing or unreadable manifest, another format, a newer format_version or schema, a file the manifest
     * does not list, a listed file that is missing or has other bytes or SHA-256, no reels.json, and content that
     * {@link LibraryFile#inspect} does not accept. A refusal leaves staging empty, and so does an Error that escapes (it is rethrown). in is not closed.
     * Rules for callers: staging must be on the same volume as the library (filesDir/restore-staging, never cacheDir or
     * external storage); only one check or restore at a time; after an OK result the staged files are installed with
     * {@link LibraryFile#replaceWith} (reels, then shots) and the caller then {@link #clear}s staging (manifest.json is
     * still there), also when the user cancels. Whole files are read into memory to be validated: the caller picks
     * maxBytes with that in mind and catches OutOfMemoryError.
     */
    static Checked check(InputStream in, File staging, long maxBytes) {
        Checked result = null;
        try {
            result = checkOrRefuse(in, staging, maxBytes);
            return result;
        } finally {
            if (result == null || !result.ok()) clear(staging);  // also when an Error (out of memory, deep nesting) escapes: nothing unverified stays
        }
    }

    private static Checked checkOrRefuse(InputStream in, File staging, long maxBytes) {
        try {
            prepare(staging);
            Checked c = checkInto(in, staging, maxBytes);
            return c;
        } catch (Refused r) {
            clear(staging);
            return new Checked(r.code, r.getMessage(), null, null, "", "", 0, new JSONObject());
        } catch (ZipException | EOFException e) {
            clear(staging);
            return new Checked(Code.CORRUPT, "This file is damaged or incomplete (for example a download that stopped early). Nothing was changed.", null, null, "", "", 0, new JSONObject());
        } catch (IOException | RuntimeException e) {
            clear(staging);
            return new Checked(Code.IO_ERROR, "The file could not be read. Nothing was changed.", null, null, "", "", 0, new JSONObject());
        }
    }

    private static void prepare(File staging) throws IOException {
        if (!staging.isDirectory() && !staging.mkdirs() && !staging.isDirectory()) throw new IOException("no staging folder");
        clear(staging);
    }

    /** Deletes the files in our own staging folder (nothing else is ever there). */
    static void clear(File staging) {
        File[] all = staging.listFiles();
        if (all == null) return;
        for (File f : all) if (f.isFile()) f.delete();
    }

    private static Checked checkInto(InputStream in, File staging, long maxBytes) throws IOException, Refused {
        ZipInputStream zin = new ZipInputStream(new FilterInputStream(in) {
            @Override
            public void close() {
                // the caller's stream stays the caller's
            }
        });
        Map<String, String> sha = new HashMap<>();
        Map<String, Long> size = new HashMap<>();
        long total = 0;
        int entries = 0;
        byte[] buf = new byte[64 * 1024];
        for (ZipEntry e; (e = zin.getNextEntry()) != null; ) {
            entries++;
            String name = e.getName();
            if (e.isDirectory() || !(name.equals(MANIFEST) || name.equals(REELS) || name.equals(SHOTS))) {
                throw new Refused(Code.BAD_ENTRY, "This is not a Reel Shelf backup: it contains something else (\"" + printable(name) + "\"). Nothing was changed.");
            }
            if (sha.containsKey(name)) throw new Refused(Code.DUPLICATE_ENTRY, "This backup is not valid: \"" + name + "\" is in it twice. Nothing was changed.");
            long limit = name.equals(MANIFEST) ? Math.min(maxBytes, MANIFEST_MAX_BYTES) : maxBytes;
            MessageDigest md = sha256();
            long len = 0;
            File part = new File(staging, name + ".part");
            try (FileOutputStream os = new FileOutputStream(part)) {
                for (int r; (r = zin.read(buf)) > 0; ) {  // counted as it is inflated: the size the ZIP declares is never trusted
                    len += r;
                    if (len > limit) throw new Refused(Code.ENTRY_TOO_BIG, name.equals(MANIFEST)
                            ? "This backup is not valid: its manifest is too big. Nothing was changed."
                            : "\"" + name + "\" in this backup is bigger than there is room for. Nothing was changed.");
                    if (total + len > maxBytes) throw new Refused(Code.TOTAL_TOO_BIG, "This backup is bigger than there is room for on this phone. Nothing was changed.");
                    md.update(buf, 0, r);
                    os.write(buf, 0, r);
                }
                os.flush();
                os.getFD().sync();  // it becomes the library by a rename: it must be on disk first
            }
            total += len;
            File whole = new File(staging, name);
            Files.move(part.toPath(), whole.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            sha.put(name, hex(md.digest()));
            size.put(name, len);
        }
        if (entries == 0) throw new Refused(Code.NOT_A_BACKUP, "This is not a Reel Shelf backup file. A plain reels.json or a notes export (JSON) cannot be restored; only a backup made by Reel Shelf can. Nothing was changed.");
        if (!sha.containsKey(MANIFEST)) throw new Refused(Code.NO_MANIFEST, "This backup is incomplete: it has no manifest. Nothing was changed.");

        JSONObject m = manifest(new File(staging, MANIFEST));
        Object fmt = m.opt("format");
        if (!FORMAT.equals(fmt)) throw new Refused(Code.WRONG_FORMAT, "This is not a Reel Shelf backup. Nothing was changed.");
        Object ver = m.opt("format_version");
        if (!(ver instanceof Number)) throw new Refused(Code.BAD_MANIFEST, "This backup is not valid: its manifest has no version. Nothing was changed.");
        double v = ((Number) ver).doubleValue();
        if (v > FORMAT_VERSION) throw new Refused(Code.NEWER_FORMAT, "This backup was made by a newer Reel Shelf: update Reel Shelf first, then restore it. Nothing was changed.");
        if (v < FORMAT_VERSION || v != Math.floor(v)) throw new Refused(Code.BAD_MANIFEST, "This backup is not valid: its manifest version is wrong. Nothing was changed.");
        JSONObject files = m.optJSONObject("files");
        if (files == null) throw new Refused(Code.BAD_MANIFEST, "This backup is not valid: its manifest lists no files. Nothing was changed.");
        for (java.util.Iterator<String> it = files.keys(); it.hasNext(); ) {
            String k = it.next();
            if (!k.equals(REELS) && !k.equals(SHOTS)) throw new Refused(Code.BAD_MANIFEST, "This backup is not valid: its manifest lists an unknown file. Nothing was changed.");
        }
        for (String name : sha.keySet()) {
            if (!name.equals(MANIFEST) && files.optJSONObject(name) == null) throw new Refused(Code.UNLISTED_FILE, "This backup is not valid: \"" + name + "\" is in it but the manifest does not list it. Nothing was changed.");
        }
        if (files.optJSONObject(REELS) == null) throw new Refused(Code.NO_REELS, "This backup has no reels file, so there is nothing to restore. Nothing was changed.");
        for (String name : new String[]{REELS, SHOTS}) {
            JSONObject want = files.optJSONObject(name);
            if (want == null) continue;
            if (!sha.containsKey(name)) throw new Refused(Code.FILE_MISSING, "This backup is incomplete: \"" + name + "\" is missing from it. Nothing was changed.");
            Object bytes = want.opt("bytes");
            if (!(bytes instanceof Number) || ((Number) bytes).longValue() != size.get(name) || !sha.get(name).equalsIgnoreCase(want.optString("sha256", ""))) {
                throw new Refused(Code.FILE_MISMATCH, "This backup is damaged: \"" + name + "\" is not what was saved (for example a download that stopped early). Nothing was changed.");
            }
        }
        // The content itself: parsed once per file, by the same rules the library file is read with.
        check(files.optJSONObject(REELS), new File(staging, REELS), REELS, LibraryFile.RELS, "schema_version", LibraryFile.REELS_SCHEMA);
        if (files.optJSONObject(SHOTS) != null) check(files.optJSONObject(SHOTS), new File(staging, SHOTS), SHOTS, LibraryFile.SHOTS, "v", LibraryFile.SHOTS_SCHEMA);

        JSONObject app = m.optJSONObject("app");
        return new Checked(Code.OK, "", new File(staging, REELS), files.optJSONObject(SHOTS) != null ? new File(staging, SHOTS) : null,
                m.optString("created_at", ""), app == null ? "" : app.optString("version_name", ""), app == null ? 0 : app.optLong("version_code", 0),
                m.optJSONObject("counts") == null ? new JSONObject() : m.optJSONObject("counts"));
    }

    private static void check(JSONObject listed, File f, String name, LibraryFile.Shape shape, String key, int supported) throws Refused {
        LibraryFile.Good g = LibraryFile.inspect(f, shape, key);
        // a newer layout may have another shape, so "newer" is decided before "damaged"; the manifest's own number counts too
        if ((g != null && LibraryFile.isNewer(g.schema, supported)) || LibraryFile.isNewer(listed.opt("schema_version"), supported)) {
            throw new Refused(Code.NEWER_SCHEMA, "This backup was made by a newer Reel Shelf (\"" + name + "\" uses a layout this version cannot read): update Reel Shelf first, then restore it. Nothing was changed.");
        }
        if (g == null || !g.shapeOk) throw new Refused(Code.INVALID_CONTENT, "This backup is damaged: \"" + name + "\" is not a valid library file. Nothing was changed.");
    }

    private static JSONObject manifest(File f) throws Refused {
        try {
            String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            JSONTokener t = new JSONTokener(s);
            Object v = t.nextValue();
            if (v instanceof JSONObject && t.nextClean() == 0) return (JSONObject) v;
        } catch (Exception e) {
            // fall through
        }
        throw new Refused(Code.BAD_MANIFEST, "This backup is not valid: its manifest cannot be read. Nothing was changed.");
    }

    private static String printable(String s) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < s.length() && i < 40; i++) {
            char c = s.charAt(i);
            b.append(c < 32 || c == 127 ? '?' : c);
        }
        return b.toString();
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static String hex(byte[] d) {
        StringBuilder b = new StringBuilder();
        for (byte x : d) b.append(String.format(Locale.ROOT, "%02x", x));
        return b.toString();
    }
}
