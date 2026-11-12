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
 * One instance per file for the whole process, so the app screen and the nightly run obey the same lock.
 * Pure Java (files and org.json only), tested on a computer.
 */
final class LibraryFile {
    enum State { OK, MISSING, RECOVERED, UNREADABLE, STARTED_NEW }

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

    static synchronized LibraryFile of(File dir, String name, Shape shape) {
        String key;
        try {
            key = new File(dir, name).getCanonicalPath();
        } catch (IOException e) {
            key = new File(dir, name).getAbsolutePath();
        }
        LibraryFile f = ALL.get(key);
        if (f == null) ALL.put(key, f = new LibraryFile(dir, name, shape));
        return f;
    }

    static LibraryFile reels(File dir) {
        return of(dir, "reels.json", RELS);
    }

    static LibraryFile shots(File dir) {
        return of(dir, "shots.json", SHOTS);
    }

    final File main;
    final File bak;
    private final File tmp;
    private final Shape shape;
    private State state = State.MISSING;
    private boolean locked;
    /** The file on disk was read (or written) by this process and found good: only then may it become the backup. */
    private boolean trusted;
    private String badName = "";
    /** The damaged file this process set aside last. */
    private File setAside;
    private String notice = "";

    private LibraryFile(File dir, String name, Shape shape) {
        this.main = new File(dir, name);
        this.bak = new File(dir, name + ".bak");
        this.tmp = new File(dir, name + ".tmp");
        this.shape = shape;
    }

    synchronized State state() {
        return state;
    }

    synchronized boolean locked() {
        return locked;
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

    // ------------------------------------------------------------------ reading

    /** The file's text; "" when there is none or it is locked (see {@link #state()}). Restores a good backup when needed. */
    synchronized String read() {
        String text = valid(main);
        if (text != null) {
            trusted = true;
            locked = false;
            state = State.OK;
            return text;
        }
        boolean hadMain = main.exists();
        String old = valid(bak);
        if (old != null) {
            try {
                if (hadMain) remember(quarantine(main));
                put(main, old.getBytes(StandardCharsets.UTF_8));  // a copy: the backup stays where it is
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
            return old;
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

    /** The text of f when it is a whole JSON object of the right shape, else null. */
    private String valid(File f) {
        try {
            if (!f.isFile() || f.length() == 0) return null;
            String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            if (s.indexOf('\u0000') >= 0) return null;  // zero-filled blocks after a crash (a real file never has one: JSON escapes it)
            JSONTokener t = new JSONTokener(s);
            Object v = t.nextValue();
            if (!(v instanceof JSONObject) || t.nextClean() != 0) return null;  // not an object, or something after it
            return shape.ok((JSONObject) v) ? s : null;
        } catch (Exception e) {
            return null;
        }
    }

    // ------------------------------------------------------------------ writing

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

    // ------------------------------------------------------------------ recovery you choose

    /**
     * Sets the damaged file (and a damaged backup) aside, renamed and kept, and unlocks for a new file. Throws when a
     * rename fails: the file then stays locked and nothing is replaced.
     */
    synchronized File startNew() throws IOException {
        File bad = main.exists() ? quarantine(main) : null;
        if (bak.exists()) quarantine(bak);
        locked = false;
        trusted = true;
        state = State.STARTED_NEW;
        if (bad != null) remember(bad);
        notice = "started_new";
        return bad;
    }

    /**
     * The file to save for the user: the locked file itself, or (when only the page found it unreadable) the file in
     * place, else the one just set aside. Null when there is none.
     */
    synchronized File unreadableFile() {
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

    /** Deletes the backup (after "Delete all reels and notes", so deleted reels do not come back from it). */
    synchronized boolean dropBackup() {
        return !bak.exists() || bak.delete();
    }
}
