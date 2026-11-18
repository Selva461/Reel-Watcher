package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "Files kept for safety" (Settings > Backup and restore): the copies of the library that Reel Shelf set aside and then
 * never touches again, listed so the user can save them to Downloads or delete them (LocalBridge.keptFiles, saveKept,
 * askDeleteKept, deleteKept). Pure Java, tested on a computer. This class is an allowlist and nothing else:
 * <ul>
 * <li>NAME.bad-STAMP[-N]: a library file that could not be read, set aside by recovery or by "Start a new library"
 *     (LibraryFile.quarantine); NAME.bak.bad-STAMP[-N]: a damaged previous copy set aside the same way;</li>
 * <li>NAME.before-restore-STAMP[-N]: the library a restore replaced (LibraryFile.replaceWith);</li>
 * <li>the plain files left in filesDir/restore-staging and filesDir/backup-check, as ONE row ({@link #TEMP_NAME}).</li>
 * </ul>
 * NAME is reels.json or shots.json, STAMP is yyyyMMdd-HHmmss, and N (when there) is 2 or more: exactly what LibraryFile
 * makes, and a test reads LibraryFile's source to see that it makes no other kind. Everything else is invisible here and
 * never touched, whatever it is: the library itself, its .bak, a .tmp or .part of a write that is running, models,
 * inboxes, share-staging, links, folders. The page only ever passes a name it was given by {@link #list}; every call
 * checks the name again against these patterns and looks the file up again in the folder (a regular file, not a link,
 * directly in it). The only thing a delete removes is that one file, or the plain files of the two temporary folders.
 * Listing and saving are always allowed. A delete needs a one-use confirmation token from {@link #ask} and is refused
 * while any work runs, while a backup or restore runs (the same one-at-a-time flag), and while the library cannot be
 * trusted (see {@link #LOCKED}). A sentence never has a path, an exception message or any part of the library in it.
 */
final class KeptFiles {
    private KeptFiles() {
    }

    /** The one row for the leftover files of the two temporary folders. Not a file name: it can never match a pattern below. */
    static final String TEMP_NAME = "temporary-restore-files";
    /** Folders in filesDir that only ever hold our own unpacked backups (LibraryBackup.clear empties them). */
    static final String[] TEMP_FOLDERS = {"restore-staging", "backup-check"};
    /** The time stamp LibraryFile puts in a set-aside name. */
    static final String STAMP_FORMAT = "yyyyMMdd-HHmmss";
    /** The most files listed (a library never has more than a handful). */
    static final int MAX_ITEMS = 500;
    /** How long a confirmation token lives. */
    static final long TOKEN_TTL_MS = 2 * 60 * 1000;

    // [0-9] is the ASCII digits. group 1: reels|shots, group 2: the stamp, group 3: "-N" or "" (N from 2 on, as LibraryFile counts).
    private static final String TAIL = "([0-9]{8}-[0-9]{6})((?:-(?:[2-9]|[1-9][0-9]{1,5}))?)";
    private static final Pattern BAD = Pattern.compile("(reels|shots)\\.json\\.bad-" + TAIL);
    private static final Pattern BAD_BACKUP = Pattern.compile("(reels|shots)\\.json\\.bak\\.bad-" + TAIL);
    private static final Pattern BEFORE_RESTORE = Pattern.compile("(reels|shots)\\.json\\.before-restore-" + TAIL);
    private static final int LONGEST_NAME = 80;

    static final String NOT_KEPT = "That is not one of the files Reel Shelf keeps for safety, so nothing was done.";
    static final String GONE = "That file is no longer there. Nothing was deleted.";
    static final String CHANGED = "That file changed since you looked at it, so nothing was deleted. Look at the list again.";
    static final String NOT_CONFIRMED = "The delete was not confirmed (the confirmation may have timed out), so nothing was deleted. Choose Delete again.";
    static final String BUSY = "Another backup, restore or file action is already running. Wait for it to finish, then try again. Nothing was deleted.";
    static final String WORK = "Reel Shelf is busy with a job (writing notes, reading screenshots, an online check, a download or the nightly run). Stop it, or wait until it is done, then try again. Nothing was deleted.";
    static final String LOCKED = "Your library (or your screenshot list) could not be read, or was saved by a newer Reel Shelf. The files kept for safety may then be the only copy of something you need, so none is deleted now. Nothing was deleted.";
    static final String WAITING = "A backup is waiting to be restored from these files. Finish or cancel that restore first. Nothing was deleted.";
    static final String NOT_DELETED = "The file could not be deleted. Nothing else was changed.";
    static final String TEMP_PARTLY = "Some of the temporary restore files could not be deleted. Look at the list again.";
    static final String LIST_FAILED = "The list of kept files could not be read. Nothing was changed.";
    static final String TEMP_SAVE = "Temporary restore files cannot be saved. They are only copies made while a backup file was checked; they can only be deleted.";
    static final String SAVE_GONE = "That file is no longer there. Nothing was saved.";
    static final String DISK_FULL = "The phone ran out of space while saving the file, so it was deleted from Downloads. Free up space and try again. The kept file was not changed.";
    static final String GENERIC_SAVE = "The file could not be saved. The kept file was not changed. Please try again.";
    static final String READ_BACK = "The copy was saved but could not be read back correctly, so it was deleted from Downloads. The kept file was not changed. Please try again.";
    /** What a writer that has nothing to write says (see LocalBridge.saveToDownloads); never shown. */
    static final String EMPTY = "There is nothing to save";

    /** What a kept file is. */
    enum Kind {
        /** NAME.bad-STAMP: an unreadable library file, set aside. */ BAD("bad"),
        /** NAME.bak.bad-STAMP: an unreadable previous copy, set aside. */ BAD_BACKUP("bad_backup"),
        /** NAME.before-restore-STAMP: the library a restore replaced. */ BEFORE_RESTORE("before_restore"),
        /** The plain files left in the two temporary folders. */ TEMP("temp");

        final String id;

        Kind(String id) {
            this.id = id;
        }
    }

    /** One row of the list, as found on disk now. at: when it was set aside (from its name), else its modified time. */
    static final class Item {
        final String name;
        final Kind kind;
        /** "reels", "shots", or "" for the temporary files. */
        final String library;
        /** Bytes (for the temporary files: all of them together). */
        final long size;
        final long at;
        /** Modified time (the newest one for the temporary files): with size and files it tells a file that changed. */
        final long modified;
        /** 1 for a file; for the temporary files how many. */
        final int files;

        Item(String name, Kind kind, String library, long size, long at, long modified, int files) {
            this.name = name;
            this.kind = kind;
            this.library = library;
            this.size = size;
            this.at = at;
            this.modified = modified;
            this.files = files;
        }

        JSONObject toJson() {
            JSONObject o = new JSONObject();
            try {
                o.put("name", name);
                o.put("kind", kind.id);
                o.put("library", library);
                o.put("size", size);
                o.put("at", at);
                o.put("files", files);
            } catch (JSONException e) {
                throw new IllegalStateException(e);  // not reachable: no null keys
            }
            return o;
        }
    }

    // ------------------------------------------------------------------ names

    /** What kind of kept file a name is, or null when it is not one: the only place a name is accepted. */
    static Kind kindOf(String name) {
        if (name == null || name.length() > LONGEST_NAME) return null;
        if (TEMP_NAME.equals(name)) return Kind.TEMP;
        if (BAD.matcher(name).matches()) return Kind.BAD;
        if (BAD_BACKUP.matcher(name).matches()) return Kind.BAD_BACKUP;
        if (BEFORE_RESTORE.matcher(name).matches()) return Kind.BEFORE_RESTORE;
        return null;
    }

    private static Matcher match(String name, Kind k) {
        Pattern p = k == Kind.BAD ? BAD : k == Kind.BAD_BACKUP ? BAD_BACKUP : BEFORE_RESTORE;
        Matcher m = p.matcher(name);
        if (!m.matches()) throw new IllegalStateException("not a kept file name");
        return m;
    }

    /** The name the copy gets in Downloads/ReelShelf: LIBRARY-WHAT-STAMP.txt (as saveUnreadable names its file), so any app opens it as text. Null for the temporary files. */
    static String saveName(Item it) {
        if (it == null || it.kind == Kind.TEMP) return null;
        Matcher m = match(it.name, it.kind);
        String what = it.kind == Kind.BAD ? "unreadable" : it.kind == Kind.BAD_BACKUP ? "backup-unreadable" : "before-restore";
        return m.group(1) + "-" + what + "-" + m.group(2) + m.group(3) + ".txt";
    }

    /** The moment in a set-aside name, in tz (the phone's own, as LibraryFile wrote it); -1 when it is not a real date. */
    static long stampMillis(String name, Kind k, TimeZone tz) {
        if (k == Kind.TEMP) return -1;
        try {
            String stamp = match(name, k).group(2);
            SimpleDateFormat f = new SimpleDateFormat(STAMP_FORMAT, Locale.ROOT);
            f.setTimeZone(tz);
            f.setLenient(false);
            ParsePosition pos = new ParsePosition(0);
            Date d = f.parse(stamp, pos);
            return d != null && pos.getIndex() == stamp.length() ? d.getTime() : -1;
        } catch (RuntimeException e) {
            return -1;
        }
    }

    // ------------------------------------------------------------------ listing

    private static final Comparator<Item> NEWEST_FIRST = (x, y) -> {
        int c = Long.compare(y.at, x.at);
        return c != 0 ? c : y.name.compareTo(x.name);  // the same second: "-2" is newer than the name without it
    };

    /**
     * The kept files in dir, newest first (by the moment in their names), then the one row for the temporary files when there
     * are any. Looks at each entry without following links: a link, a folder or anything that is not a regular file is not
     * listed, whatever it is called. Throws when dir cannot be read at all.
     */
    static List<Item> list(File dir, TimeZone tz) throws IOException {
        List<Item> out = new ArrayList<>();
        Path base = dir.toPath();
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(base)) {
            for (Path child : stream) {
                String name = child.getFileName().toString();
                Kind k = kindOf(name);
                if (k == null || k == Kind.TEMP) continue;
                Item it = inspect(base, name, k, tz);
                if (it != null && out.size() < MAX_ITEMS) out.add(it);
            }
        } catch (java.nio.file.DirectoryIteratorException e) {
            throw new IOException("listing failed");
        }
        Collections.sort(out, NEWEST_FIRST);
        Item temp = tempItem(dir);
        if (temp != null) out.add(temp);
        return out;
    }

    /** The item for a name, looked up again in dir now, or null: not a kept name, not there, a link, not a regular file, or not directly in dir. Never throws. */
    static Item find(File dir, String name, TimeZone tz) {
        Kind k = kindOf(name);
        if (k == null) return null;
        try {
            return k == Kind.TEMP ? tempItem(dir) : inspect(dir.toPath(), name, k, tz);
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static Item inspect(Path base, String name, Kind k, TimeZone tz) {
        try {
            Path p = base.resolve(name);
            BasicFileAttributes a = Files.readAttributes(p, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (a.isSymbolicLink() || !a.isRegularFile()) return null;
            Path parent = p.toRealPath().getParent();  // a regular file, so its real path is its own: it must be directly in the folder
            if (parent == null || !parent.equals(base.toRealPath())) return null;
            long modified = a.lastModifiedTime().toMillis();
            long stamp = stampMillis(name, k, tz);
            return new Item(name, k, match(name, k).group(1), a.size(), stamp >= 0 ? stamp : modified, modified, 1);
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /** The plain files directly in the temporary folders: regular files only, never a link, never anything in a sub-folder, never a folder that is itself a link. */
    private static List<Path> tempFiles(File dir) {
        List<Path> out = new ArrayList<>();
        for (String folder : TEMP_FOLDERS) {
            Path p = dir.toPath().resolve(folder);
            try {
                BasicFileAttributes own = Files.readAttributes(p, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                if (own.isSymbolicLink() || !own.isDirectory()) continue;
                try (DirectoryStream<Path> stream = Files.newDirectoryStream(p)) {
                    for (Path child : stream) {
                        BasicFileAttributes a = Files.readAttributes(child, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                        if (a.isRegularFile() && !a.isSymbolicLink()) out.add(child);
                    }
                }
            } catch (IOException | RuntimeException e) {
                // a folder that cannot be read is left alone, and not shown
            }
        }
        return out;
    }

    private static Item tempItem(File dir) {
        long size = 0, newest = 0;
        int files = 0;
        for (Path f : tempFiles(dir)) {
            try {
                BasicFileAttributes a = Files.readAttributes(f, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                size += a.size();
                newest = Math.max(newest, a.lastModifiedTime().toMillis());
                files++;
            } catch (IOException | RuntimeException e) {
                // gone meanwhile
            }
        }
        return files == 0 ? null : new Item(TEMP_NAME, Kind.TEMP, "", size, newest, newest, files);
    }

    /** What the page gets: {items: [{name, kind, library, size, at, files}], error}. error is a sentence when the folder could not be read (the list is then empty). */
    static String listJson(File dir, TimeZone tz) {
        JSONArray a = new JSONArray();
        String error = "";
        try {
            for (Item it : list(dir, tz)) a.put(it.toJson());
        } catch (IOException | RuntimeException e) {
            a = new JSONArray();
            error = LIST_FAILED;
        }
        try {
            return new JSONObject().put("items", a).put("error", error).toString();
        } catch (JSONException e) {
            throw new IllegalStateException(e);  // not reachable: no null keys
        }
    }

    // ------------------------------------------------------------------ deleting: ask, then delete with the token

    /** The confirmation of one delete: what the user was shown, and the token that goes with it. A new ask replaces it; a delete uses it once. */
    static final class Confirm {
        private final Supplier<String> tokens;
        private final LongSupplier clock;
        private String token;
        private Item pledge;
        private long issued;

        Confirm() {
            this(() -> UUID.randomUUID().toString(), System::currentTimeMillis);
        }

        Confirm(Supplier<String> tokens, LongSupplier clock) {
            this.tokens = tokens;
            this.clock = clock;
        }

        /** Remembers what the user is shown (name, size, time) and returns its token. Whatever was pending before is forgotten. */
        synchronized String put(Item shown) {
            token = tokens.get();
            pledge = shown;
            issued = clock.getAsLong();
            return token;
        }

        /**
         * What was shown, when t is the pending token and it was issued for this name and has not expired; and then it is gone (single
         * use). A call with another token (or none) gets null and changes nothing; a call with the pending token for another name, or
         * too late, gets null and the token is gone.
         */
        synchronized Item take(String name, String t) {
            if (token == null || t == null || !token.equals(t)) return null;
            Item shown = pledge;
            long age = clock.getAsLong() - issued;
            token = null;
            pledge = null;
            if (name == null || !name.equals(shown.name) || age < 0 || age > TOKEN_TTL_MS) return null;
            return shown;
        }

        synchronized boolean pending() {
            return token != null;
        }
    }

    /**
     * What the phone is doing and where the files are, as a delete needs to know. job is LocalBridge's one-at-a-time flag of the
     * library jobs (a backup or a restore holds it); working says a job, a download or the nightly run is going; reels and shots are the
     * library files as the phone knows them (a locked one is unreadable or from a newer Reel Shelf); stage is the backup waiting to be restored.
     */
    static final class Env {
        final File dir;
        final AtomicBoolean job;
        final BooleanSupplier working;
        final LibraryFile reels;
        final LibraryFile shots;
        final RestoreNow.Stage stage;
        final Confirm confirm;
        final TimeZone tz;

        Env(File dir, AtomicBoolean job, BooleanSupplier working, LibraryFile reels, LibraryFile shots, RestoreNow.Stage stage, Confirm confirm, TimeZone tz) {
            this.dir = dir;
            this.job = job;
            this.working = working;
            this.reels = reels;
            this.shots = shots;
            this.stage = stage;
            this.confirm = confirm;
            this.tz = tz;
        }
    }

    /**
     * The reasons a delete is refused that do not depend on the file. Listing and saving never ask this. A library that is locked
     * (unreadable, or from a newer Reel Shelf) is read from the state this process already knows (it is never read here, so asking
     * cannot recover or set aside anything): the files kept may then be the only copy of the user's data, and a newer library's
     * set-aside files are not ours to remove (the same rule LibraryFile.dropBackup has for the backup of a newer library).
     */
    private static String refusal(Env e, String name) {
        if (e.working.getAsBoolean()) return WORK;
        if (e.reels.locked() || e.shots.locked()) return LOCKED;
        if (TEMP_NAME.equals(name) && e.stage.staged()) return WAITING;
        return null;
    }

    /**
     * Step 1 of a delete: the page asks to delete name (one the list gave). Answers JSON {ok:true, token, item} with the file as it is now
     * (what the confirm screen shows), or {ok:false, text} with one sentence. Nothing is changed. Refused with the same sentences as the
     * delete itself, so a screen that would be refused is not shown.
     */
    static String ask(Env e, String name) {
        if (kindOf(name) == null) return no(NOT_KEPT);
        if (e.job.get()) return no(BUSY);
        String why = refusal(e, name);
        if (why != null) return no(why);
        Item it = find(e.dir, name, e.tz);
        if (it == null) return no(GONE);
        String token = e.confirm.put(it);
        try {
            return new JSONObject().put("ok", true).put("token", token).put("item", it.toJson()).toString();
        } catch (JSONException x) {
            throw new IllegalStateException(x);  // not reachable: no null keys
        }
    }

    /** {ok:false, text}: the answer to {@link #ask} when nothing is asked for. */
    static String refuse(String sentence) {
        return no(sentence);
    }

    private static String no(String sentence) {
        try {
            return new JSONObject().put("ok", false).put("text", sentence).toString();
        } catch (JSONException x) {
            throw new IllegalStateException(x);  // not reachable: no null keys
        }
    }

    /**
     * Step 2: deletes name, only with the token {@link #ask} gave for it. Refused, with nothing deleted, when: the name is not a kept
     * file's; a backup or restore holds the flag; work or the nightly run is going; the library is locked; the temporary files are
     * wanted by a restore that is waiting; the token is not the pending one, is for another name, or has expired (it is used up by a call
     * that gets this far, whatever the answer); the file is gone; or its size or time changed since the user was shown it. A refusal
     * for work, the flag or the library leaves the token as it is. The flag is held while the file is removed and always released.
     * Removes exactly one file (or the plain files of the two temporary folders): never a folder, never anything the list does not show.
     * Answers JSON {deleted, bytes} or one sentence.
     */
    static BackupNow.Outcome delete(Env e, String name, String token) {
        if (kindOf(name) == null) return BackupNow.fail(NOT_KEPT);
        if (!e.job.compareAndSet(false, true)) return BackupNow.fail(BUSY);
        try {
            String why = refusal(e, name);
            if (why != null) return BackupNow.fail(why);
            Item shown = e.confirm.take(name, token);
            if (shown == null) return BackupNow.fail(NOT_CONFIRMED);
            Item now = find(e.dir, name, e.tz);
            if (now == null) return BackupNow.fail(GONE);
            if (now.size != shown.size || now.modified != shown.modified || now.files != shown.files) return BackupNow.fail(CHANGED);
            return remove(e.dir, now);
        } catch (RuntimeException | Error x) {
            return BackupNow.fail(NOT_DELETED);
        } finally {
            e.job.set(false);
        }
    }

    private static BackupNow.Outcome remove(File dir, Item it) {
        try {
            if (it.kind == Kind.TEMP) {
                int failed = 0;
                for (Path f : tempFiles(dir)) {
                    try {
                        deleteRegular(f);
                    } catch (IOException | RuntimeException x) {
                        failed++;
                    }
                }
                return failed == 0 ? deleted(it) : BackupNow.fail(TEMP_PARTLY);
            }
            deleteRegular(dir.toPath().resolve(it.name));
            return deleted(it);
        } catch (NoSuchFileException x) {
            return BackupNow.fail(GONE);
        } catch (IOException | RuntimeException x) {
            return BackupNow.fail(NOT_DELETED);
        }
    }

    /** Deletes path only when it is a regular file and not a link (a link is never followed: deleting one would only remove the link, but it is not ours to remove). */
    private static void deleteRegular(Path path) throws IOException {
        BasicFileAttributes a = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (a.isSymbolicLink() || !a.isRegularFile()) throw new IOException("not a plain file");
        Files.delete(path);
    }

    private static BackupNow.Outcome deleted(Item it) {
        try {
            return new BackupNow.Outcome(true, new JSONObject().put("deleted", it.name).put("bytes", it.size).toString());
        } catch (JSONException x) {
            throw new IllegalStateException(x);  // not reachable: no null keys
        }
    }

    // ------------------------------------------------------------------ saving to Downloads (the phone's MediaStore part is LocalBridge.saveKept)

    /** The free space a copy needs: its size plus the reserve that must stay free so the library itself can still be saved. Never wraps round. */
    static long neededBytes(long size, long reserve) {
        long keep = Math.max(0, reserve), own = Math.max(0, size);
        return own > Long.MAX_VALUE - keep ? Long.MAX_VALUE : own + keep;
    }

    static String notEnoughSpace(long needed, long free) {
        long needMb = (needed + 1048575) / 1048576;
        long freeMb = Math.max(0, free) / 1048576;
        return "There is not enough free space on the phone to save this file: about " + needMb + " MB are needed and " + freeMb
                + " MB are free. Free up some space and try again. The kept file was not changed.";
    }

    static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);  // every Java has it
        }
    }

    /**
     * Copies the kept file it to out, byte for byte, feeding md as it goes; returns the number of bytes. Opens the file without following
     * a link. Throws when what it read is not the size the file had when it was looked up (it changed meanwhile).
     */
    static long copy(File dir, Item it, OutputStream out, MessageDigest md) throws IOException {
        if (it.kind == Kind.TEMP) throw new IOException(TEMP_SAVE);
        long n = 0;
        try (InputStream in = Files.newInputStream(dir.toPath().resolve(it.name), LinkOption.NOFOLLOW_LINKS)) {
            byte[] buf = new byte[64 * 1024];
            int r;
            while ((r = in.read(buf)) > 0) {
                out.write(buf, 0, r);
                md.update(buf, 0, r);
                n += r;
            }
        }
        if (n != it.size) throw new BackupNow.Failure(CHANGED);
        return n;
    }

    /** The proof that the saved copy is whole: reads it back and compares its length and SHA-256 with what was written. Throws a {@link BackupNow.Failure} with {@link #READ_BACK} when they differ. */
    static void verify(InputStream in, byte[] wantSha, long wantBytes) throws IOException {
        MessageDigest md = sha256();
        byte[] buf = new byte[64 * 1024];
        long n = 0;
        int r;
        while ((r = in.read(buf)) > 0) {
            md.update(buf, 0, r);
            n += r;
        }
        if (n != wantBytes || wantSha == null || !MessageDigest.isEqual(md.digest(), wantSha)) throw new BackupNow.Failure(READ_BACK);
    }

    /** The sentence for something that went wrong while saving: only a sentence of ours or a full disk is told apart; the exception's text is never passed on. */
    static String sentenceFor(Throwable e) {
        int depth = 0;
        for (Throwable t = e; t != null && depth < 6; t = t.getCause(), depth++) {
            if (t instanceof BackupNow.Failure) return t.getMessage();
            String m = t.getMessage();
            if (m != null && (m.contains("ENOSPC") || m.contains("No space left"))) return DISK_FULL;
        }
        return GENERIC_SAVE;
    }

    /** The answer to a good save: {name, where, bytes, uninstall_warning}. where never has a full internal path (BackupNow.where). */
    static BackupNow.Outcome saved(String name, String where, long bytes, boolean appFolder) {
        try {
            return new BackupNow.Outcome(true, new JSONObject().put("name", name).put("where", where).put("bytes", bytes).put("uninstall_warning", appFolder).toString());
        } catch (JSONException x) {
            throw new IllegalStateException(x);  // not reachable: no null keys
        }
    }
}
