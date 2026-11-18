package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * One of the app's JSON data files (reels.json, shots.json) with a safety net, so a damaged file can never be
 * replaced by an empty one:
 * - every write goes to a temp file, is synced to disk, the file it replaces becomes NAME.bak, then the temp file is
 *   renamed into place (the previous version is always one step back);
 * - a file that cannot be read is never overwritten: a good backup is restored (the damaged file is kept as
 *   NAME.bad-TIME), and with no good backup the file is locked: reads give nothing, writes are refused, until
 *   {@link #startNew()} sets the damaged file aside (renamed, never deleted).
 * - a file saved by a NEWER Reel Shelf (its schema number is above what this build supports) is locked the same way and
 *   is never touched at all: not restored from the backup, not renamed, not written, not set aside. See {@link #REELS_SCHEMA}.
 * One instance per file for the whole process, so the app screen and the nightly run obey the same lock.
 * Every change to the file's content advances a revision. A page remembers the revision it loaded; a save based on an
 * older one is refused ({@link #write(String, long)}), so a page working on an out-of-date copy can never overwrite
 * newer data.
 * Pure Java (files and org.json only), tested on a computer.
 */
final class LibraryFile {
    enum State { OK, MISSING, RECOVERED, UNREADABLE, STARTED_NEW, NEWER }

    /**
     * The newest schema this build can read, per file. reels.json says which it was saved with in "schema_version",
     * shots.json in "v" (it has always had one). A file with a bigger number was saved by a newer Reel Shelf: it is
     * locked as NEWER and left exactly as it is. They MUST equal SCHEMA in local.js and SHOTS_SCHEMA in shots.js
     * (LibraryFileTest checks that). Raise them only in a build that can read the new format.
     */
    static final int REELS_SCHEMA = 1;
    static final int SHOTS_SCHEMA = 1;

    interface Shape {
        boolean ok(JSONObject o);
    }

    private static boolean emptyOr(Object v, Class<?> kind) {
        return v == null || v == JSONObject.NULL || kind.isInstance(v);
    }

    /** reels.json: an object whose "reels", when there, is a list. */
    static final Shape RELS = o -> emptyOr(o.opt("reels"), JSONArray.class);
    /** shots.json: an object whose "seen" and "reels", when there, are maps. */
    static final Shape SHOTS = o -> emptyOr(o.opt("seen"), JSONObject.class) && emptyOr(o.opt("reels"), JSONObject.class);

    private static final Map<String, LibraryFile> ALL = new HashMap<>();

    static synchronized LibraryFile of(File dir, String name, Shape shape, String schemaKey, int supported) {
        String key;
        try {
            key = new File(dir, name).getCanonicalPath();
        } catch (IOException e) {
            key = new File(dir, name).getAbsolutePath();
        }
        LibraryFile f = ALL.get(key);
        if (f == null) ALL.put(key, f = new LibraryFile(dir, name, shape, schemaKey, supported));
        return f;
    }

    static LibraryFile reels(File dir) {
        return of(dir, "reels.json", RELS, "schema_version", REELS_SCHEMA);
    }

    static LibraryFile shots(File dir) {
        return of(dir, "shots.json", SHOTS, "v", SHOTS_SCHEMA);
    }

    final File main;
    final File bak;
    private final File tmp;
    private final Shape shape;
    private final String schemaKey;
    private final int supported;
    /** The schema number of the NEWER file, rounded up to a whole number (0 unless the state is NEWER). */
    private long found;
    /** The file that made the state NEWER: main, or the backup when main is damaged. This is the one "Save a copy" gives out. */
    private File newerFile;
    private State state = State.MISSING;
    private boolean locked;
    /** The file on disk was read (or written) by this process and found good: only then may it become the backup. */
    private boolean trusted;
    private String badName = "";
    /** The damaged file this process set aside last. */
    private File setAside;
    private String notice = "";
    /** Advances whenever the file's content changes (a save, a restore from the backup, a start-new). In memory: pages cannot outlive the process. */
    private long revision;
    /** {@link #read()} has run at least once in this process, so {@link #state} says something about the file on disk. */
    private boolean loaded;
    /** How {@link #replaceWith} moves the staged file into place: a seam so a test can make that second rename fail. */
    interface Mover {
        void move(File from, File to) throws IOException;
    }

    Mover mover = LibraryFile::move;

    private LibraryFile(File dir, String name, Shape shape, String schemaKey, int supported) {
        this.main = new File(dir, name);
        this.bak = new File(dir, name + ".bak");
        this.tmp = new File(dir, name + ".tmp");
        this.shape = shape;
        this.schemaKey = schemaKey;
        this.supported = supported;
    }

    synchronized State state() {
        return state;
    }

    synchronized boolean locked() {
        return locked;
    }

    /** The schema number this build supports for this file. */
    int supported() {
        return supported;
    }

    /** The schema number the NEWER file was saved with (rounded up to a whole number), or 0 when the state is not NEWER. */
    synchronized long found() {
        return state == State.NEWER ? found : 0;
    }

    /** Name of the damaged file that was set aside, or "". */
    synchronized String badName() {
        return badName;
    }

    /** "recovered" or "started_new" once after the file was restored or set aside, so the screen can say so; then "". */
    synchronized String takeNotice() {
        String n = notice;
        notice = "";
        return n;
    }

    synchronized long revision() {
        return revision;
    }

    /** What a page gets when it loads: the text, the state and the revision the text belongs to, all at one moment. */
    static final class Loaded {
        final String text;
        final State state;
        final long revision;

        Loaded(String text, State state, long revision) {
            this.text = text;
            this.state = state;
            this.revision = revision;
        }
    }

    /** The answer to a save: done, refused because the page's copy is out of date (stale), and the revision now. */
    static final class Result {
        final boolean ok;
        final boolean stale;
        final long revision;

        Result(boolean ok, boolean stale, long revision) {
            this.ok = ok;
            this.stale = stale;
            this.revision = revision;
        }
    }

    // ------------------------------------------------------------------ reading

    /** {@link #read()} together with the revision it belongs to (nothing can change in between). */
    synchronized Loaded load() {
        String text = read();
        return new Loaded(text, state, revision);
    }

    /** The file's text; "" when there is none or it is locked (see {@link #state()}). Restores a good backup when needed. */
    synchronized String read() {
        loaded = true;
        Good now = good(main);
        if (now != null && newer(now.schema)) return lockNewer(now.schema, main);  // before anything else, and whatever its shape: no restore, no rename, no write
        if (now != null && now.shapeOk) {
            trusted = true;
            locked = false;
            state = State.OK;
            return now.text;
        }
        boolean hadMain = main.exists();
        Good old = good(bak);
        // The file is damaged, so nothing can be said about it, but the backup was saved by a newer Reel Shelf. Restoring
        // it is the newer version's job (it knows the format): this one leaves both files exactly as they are.
        if (old != null && newer(old.schema)) return lockNewer(old.schema, bak);
        if (old != null && old.shapeOk) {
            try {
                if (hadMain) remember(quarantine(main));
                put(main, old.text.getBytes(StandardCharsets.UTF_8));  // a copy: the backup stays where it is
            } catch (IOException e) {
                trusted = false;
                locked = true;
                state = State.UNREADABLE;
                return "";
            }
            trusted = true;
            locked = false;
            state = State.RECOVERED;
            notice = "recovered";
            revision++;  // the content on disk is no longer what pages loaded before
            return old.text;
        }
        if (!hadMain && !bak.exists()) {  // nothing was ever saved: a new library
            trusted = true;
            locked = false;
            state = State.MISSING;
            return "";
        }
        trusted = false;
        locked = true;
        state = State.UNREADABLE;
        return "";
    }

    /** A file that is a whole JSON object: its text, whether it has the right shape, and what it says about its schema (null when nothing). */
    static final class Good {
        final String text;
        final boolean shapeOk;
        final Object schema;

        Good(String text, boolean shapeOk, Object schema) {
            this.text = text;
            this.shapeOk = shapeOk;
            this.schema = schema;
        }
    }

    /**
     * f as a {@link Good} when it is a whole JSON object, else null. The shape is reported, not required: a newer Reel
     * Shelf may have changed it (that is what a new schema number is for), and it is then still "newer", not "damaged".
     */
    private Good good(File f) {
        return inspect(f, shape, schemaKey);
    }

    /** The one place a library file is parsed: whole object, nothing after it, no NUL. Null when it is not that. schemaKey may be null. */
    static Good inspect(File f, Shape shape, String schemaKey) {
        try {
            if (!f.isFile() || f.length() == 0) return null;
            String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            if (s.indexOf('\u0000') >= 0) return null;  // zero-filled blocks after a crash (a real file never has one: JSON escapes it)
            JSONTokener t = new JSONTokener(s);
            Object v = t.nextValue();
            if (!(v instanceof JSONObject) || t.nextClean() != 0) return null;  // not an object, or something after it
            JSONObject o = (JSONObject) v;
            return new Good(s, shape.ok(o), schemaKey == null ? null : o.opt(schemaKey));
        } catch (Exception e) {
            return null;
        }
    }

    /** Whether f is a usable library file of this shape: the same rules {@link #read()} applies to the file on disk. (A newer schema is a separate question: see {@link #isNewer}.) */
    static boolean isValid(File f, Shape shape) {
        Good g = inspect(f, shape, null);
        return g != null && g.shapeOk;
    }

    /**
     * Whether a schema value is newer than this build supports: only a NUMBER above {@code supported} is, whatever it is
     * (2, 1.5, a number too big for a long: it is a bigger number than we know). Everything else is read as before: no key,
     * null, 0, a negative number, 1 or 1.0, and a value that is not a number at all ("2", true, a list). No release ever
     * wrote one of those, so it is no sign of a newer Reel Shelf, and locking the library for it would take away a library
     * nothing is known to be wrong with. The test is on the double value, so a number too big for a double (1e999) is newer,
     * and NaN (not valid JSON anyway) is not. That 1e999 is read as a number at all is verified on the JVM org.json that
     * the unit tests use only, NOT on Android's own org.json; no release writes such a value, so nothing depends on it.
     * local.js (isNewer) and shots.js (load) apply the same rule, and the tests of both use the same list of odd values.
     */
    private boolean newer(Object schema) {
        return isNewer(schema, supported);
    }

    /** The rule above, for any schema value and any supported number (the backup check applies it to a backup's files). */
    static boolean isNewer(Object schema, int supported) {
        return schema instanceof Number && ((Number) schema).doubleValue() > supported;
    }

    private String lockNewer(Object schema, File from) {
        found = (long) Math.ceil(((Number) schema).doubleValue());  // a whole number, at most Long.MAX_VALUE
        newerFile = from;
        trusted = false;
        locked = true;
        state = State.NEWER;
        return "";
    }

    // ------------------------------------------------------------------ writing

    /**
     * Saves text only when the page's copy is the current one: expectedRevision is what it got from {@link #load()} or
     * from its last successful save. A stale save is refused and nothing changes.
     */
    synchronized Result write(String text, long expectedRevision) {
        if (expectedRevision != revision) return new Result(false, true, revision);
        boolean ok = write(text);
        return new Result(ok, false, revision);
    }

    /** Saves text. False (and nothing changes) while locked or when the disk refuses. */
    synchronized boolean write(String text) {
        if (locked || text == null) return false;
        byte[] data = text.getBytes(StandardCharsets.UTF_8);
        try {
            writeTmp(data);
            if (main.exists()) {
                if (trusted) move(main, bak);
                else remember(quarantine(main));  // never vetted in this run: set aside, not replaced
            }
            move(tmp, main);
            trusted = true;
            if (state != State.STARTED_NEW) state = State.OK;
            revision++;
            return true;
        } catch (IOException e) {
            tmp.delete();
            if (!main.exists() && bak.exists()) {  // the old file was moved away but the new one did not arrive
                try {
                    Files.copy(bak.toPath(), main.toPath());
                } catch (IOException ignored) {
                    // the next read() restores it from the backup
                }
            }
            return false;
        }
    }

    private void writeTmp(byte[] data) throws IOException {
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(data);
            out.flush();
            out.getFD().sync();
        }
        if (tmp.length() != data.length) throw new IOException("short write");
    }

    private void put(File dest, byte[] data) throws IOException {
        writeTmp(data);
        move(tmp, dest);
    }

    private static void move(File from, File to) throws IOException {
        try {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
    }

    /** Renames f to f.bad-TIME (never overwrites an earlier one). */
    private File quarantine(File f) throws IOException {
        String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
        File to = new File(f.getParentFile(), f.getName() + ".bad-" + stamp);
        for (int i = 2; to.exists(); i++) to = new File(f.getParentFile(), f.getName() + ".bad-" + stamp + "-" + i);
        move(f, to);
        return to;
    }

    private void remember(File bad) {
        setAside = bad;
        badName = bad.getName();
    }

    // ------------------------------------------------------------------ backup and restore (see LibraryBackup)

    private void ensureRead() {
        if (!loaded) read();
    }

    /**
     * Makes dest a copy of the file as it is now, under the lock, in microseconds: a hard link. That is safe because
     * this class never changes main in place (a save writes a temp file and renames it; a restore renames), so the linked
     * file never changes whatever is saved or restored afterwards. When linking is not possible the file is copied, still
     * under the lock. Returns false when there is no file (nothing is made), throws when the library is locked
     * (unreadable or NEWER: a backup is never made of a file this build cannot vouch for) or dest already exists.
     * Rules for callers: dest is (usually) a HARD LINK to the live library file, so it may only be read or deleted, never
     * opened for writing or truncated. Take both snapshots (reels first, then shots) and read them back; the folder for
     * them (backup-work) must be emptied by the caller before it takes snapshots (an old leftover makes this throw), and
     * must be on the same volume as the library (filesDir, never cacheDir or external storage) for the link to work.
     */
    synchronized boolean snapshotTo(File dest) throws IOException {
        return snapshot(dest, true);
    }

    /** {@link #snapshotTo} with the hard link switched off, so the copy fallback can be tested. */
    synchronized boolean snapshot(File dest, boolean tryLink) throws IOException {
        ensureRead();
        if (locked) throw new IOException("The library is locked (" + state + "): no backup is made of it");
        if (!main.isFile()) return false;
        File dir = dest.getParentFile();
        if (dir != null) dir.mkdirs();
        if (tryLink) {
            try {
                Files.createLink(dest.toPath(), main.toPath());
                return true;
            } catch (java.nio.file.FileAlreadyExistsException e) {
                throw e;
            } catch (IOException | UnsupportedOperationException | SecurityException e) {
                // fall through to a copy
            }
        }
        Files.copy(main.toPath(), dest.toPath());  // never overwrites
        return true;
    }

    /**
     * Installs staged (a file {@link LibraryBackup#check} accepted) as the file. Rules:
     * - NEWER (main, or a newer backup beside a damaged main): REFUSED with an IOException and nothing at all is touched.
     *   A newer library is never replaced, renamed or set aside by an older build.
     * - UNREADABLE: allowed. Restoring is a recovery path: the unreadable file is set aside like any other.
     * - The file in place is kept as NAME.before-restore-STAMP (a name that never exists yet; made as a hard link or a synced copy, so main is never missing): never deleted, never
     *   overwritten, so a second restore keeps a second one. The backup (NAME.bak) is left exactly as it is.
     * - It works while locked, and unlocks. The revision advances, so a page that loaded earlier has its next save refused as stale.
     * - main is never missing: the set-aside file is a hard link (or a synced copy) of it, and the staged file is renamed over
     *   main in one atomic step. If that fails for any reason (an Error too) the set-aside link is removed and main is as it was.
     * - A damaged backup beside an unreadable main is set aside as NAME.bak.bad-TIME (like startNew), not left to be overwritten by the next save.
     * staged is checked again here (whole object, shape, not newer): installing a bad file would lock the library.
     * Returns the set-aside file, or null when there was no file.
     * Rules for callers: pass only a staged file of an OK {@link LibraryBackup.Checked}, from a staging folder on the same
     * volume as the library (filesDir/restore-staging, never cacheDir or external storage: the install is a rename). Order:
     * check, then replaceWith for reels, then for shots; when reels succeeded and shots failed, report exactly that (reels
     * are already replaced). Only one check or restore at a time. The staged file is moved away: afterwards (and on cancel)
     * the caller must call {@link LibraryBackup#clear} on the staging folder (manifest.json stays there).
     */
    synchronized File replaceWith(File staged) throws IOException {
        ensureRead();
        if (state == State.NEWER) throw new IOException("Saved by a newer Reel Shelf: it is never replaced by an older one");
        if (!staged.isFile()) throw new IOException("Nothing to restore from: " + staged);
        Good g = inspect(staged, shape, schemaKey);
        if (g == null || !g.shapeOk || newer(g.schema)) throw new IOException("The file to restore is not a usable " + main.getName());
        // A damaged backup beside an unreadable main must survive the next save (which moves main over .bak), as startNew keeps it.
        boolean keepBadBak = (state == State.UNREADABLE || !trusted) && bak.exists() && !isValid(bak, shape);
        File aside = null;
        if (main.exists()) {
            String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
            aside = new File(main.getParentFile(), main.getName() + ".before-restore-" + stamp);
            for (int i = 2; aside.exists(); i++) aside = new File(main.getParentFile(), main.getName() + ".before-restore-" + stamp + "-" + i);
            link(main, aside);  // a second name for main: main itself is never missing, whatever happens next
        }
        try {
            mover.move(staged, main);  // one atomic rename over main
        } catch (Throwable t) {  // an Error too: the state must stay consistent
            if (aside != null) aside.delete();  // only our own link or copy; main was never touched
            throw t;
        }
        trusted = true;
        locked = false;
        state = State.OK;
        notice = "restored";
        revision++;
        if (keepBadBak) {
            try {
                quarantine(bak);
            } catch (IOException e) {
                trusted = false;  // the next save then sets main aside instead of moving it over the damaged backup
            }
        }
        return aside;
    }

    /** to becomes a second name for from (a hard link), or a synced copy when linking is not possible. Never overwrites. */
    private static void link(File from, File to) throws IOException {
        try {
            Files.createLink(to.toPath(), from.toPath());
            return;
        } catch (java.nio.file.FileAlreadyExistsException e) {
            throw e;
        } catch (IOException | UnsupportedOperationException | SecurityException e) {
            // fall through to a copy
        }
        File part = new File(to.getParentFile(), to.getName() + ".part");
        try {
            Files.copy(from.toPath(), part.toPath(), StandardCopyOption.REPLACE_EXISTING);
            try (java.nio.channels.FileChannel c = java.nio.channels.FileChannel.open(part.toPath(), java.nio.file.StandardOpenOption.WRITE)) {
                c.force(true);
            }
            move(part, to);
        } finally {
            part.delete();
        }
    }

    // ------------------------------------------------------------------ recovery you choose

    /**
     * Sets the damaged file (and a damaged backup) aside, renamed and kept, and unlocks for a new file. Throws when a
     * rename fails: the file then stays locked and nothing is replaced. Always throws for a NEWER file (nothing is changed).
     */
    synchronized File startNew() throws IOException {
        if (state == State.NEWER) throw new IOException("Saved by a newer Reel Shelf: it is never set aside");
        File bad = main.exists() ? quarantine(main) : null;
        if (bak.exists()) quarantine(bak);
        locked = false;
        trusted = true;
        state = State.STARTED_NEW;
        if (bad != null) remember(bad);
        notice = "started_new";
        revision++;
        return bad;
    }

    /**
     * The file to save for the user: the locked file itself, or (when only the page found it unreadable) the file in
     * place, else the one just set aside. Null when there is none.
     */
    synchronized File unreadableFile() {
        if (state == State.NEWER && newerFile != null && newerFile.isFile()) return newerFile;  // the newer library itself, even when main is a cut file beside a newer backup  // the newer library itself, even when main is a cut file beside a newer backup
        if (locked) return main.exists() ? main : bak.exists() ? bak : null;
        if (state == State.OK || state == State.MISSING) return main.isFile() ? main : null;
        return setAside != null && setAside.isFile() ? setAside : null;
    }

    /** Copies the unreadable file to out. Returns the number of bytes, or -1 when there is no such file. */
    long copyUnreadableTo(OutputStream out) throws IOException {
        File f = unreadableFile();
        if (f == null) return -1;
        return Files.copy(f.toPath(), out);
    }

    /** What the temp sweep does to a leftover temp file, once this class has said it is safe to. */
    interface Remover {
        boolean remove(File tmp) throws IOException;
    }

    /**
     * For the temp sweep: lets remover delete a leftover NAME.tmp (a save that was cut off between writing the temp file and
     * renaming it). It runs under this file's own lock, so no save can be half way, and only when this process has read the
     * file and found it good (state OK, not locked). In any other state (not read yet, recovered, set aside, unreadable, a
     * newer Reel Shelf) nothing is touched: a leftover may then be the only other copy. Returns what remover returned, or
     * false when it was not allowed to run.
     */
    synchronized boolean dropTmp(Remover remover) throws IOException {
        if (locked || state != State.OK) return false;
        return remover.remove(tmp);
    }

    /** Deletes the backup (after "Delete all reels and notes", so deleted reels do not come back from it). */
    synchronized boolean dropBackup() {
        if (state == State.NEWER) return false;  // the backup of a newer library is never deleted
        return !bak.exists() || bak.delete();
    }
}
