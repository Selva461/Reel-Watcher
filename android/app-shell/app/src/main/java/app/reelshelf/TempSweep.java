package app.reelshelf;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Decides which of the app's own leftover temporary files may be deleted. It is an allowlist and nothing else: a fixed
 * table of places and exact names, and a file is deleted only when every rule below holds. Anything not named in the
 * table is kept, whatever it is, however old. There is no list of things to avoid; the library, the notes, the backups
 * (.bak, .bad-*, before-restore-*), the AI and speech models (also their .part downloads), both picture and video inboxes
 * (a file there that no reel mentions is work waiting to be done, not garbage), downloads and the system's own files are
 * kept because they are not in the table.
 * <ol>
 * <li>Named place and exact name: the entry is directly in one of the {@link Folder}s and its whole name matches a rule.</li>
 * <li>A regular file, not a link and not a folder.</li>
 * <li>Old enough by its own clock: now minus its modified time is at least the rule's minimum age. A modified time in the
 *     future (the clock went backwards) gives a negative age: kept.</li>
 * <li>Nobody is using it: the rule's {@link Guard} (the copying lock, a video being read, the library's state).</li>
 * </ol>
 * The caller (TempSweeper) adds what only it can know: the listing is bounded, and just before a delete the file is looked
 * at again and must be unchanged. Pure Java, no Android, tested on a computer. This class only decides; it deletes nothing.
 */
final class TempSweep {
    private TempSweep() {
    }

    static final long HOUR_MS = 60L * 60 * 1000;

    /** The places the sweep looks in. The caller maps each to a real folder; a place that is a link is never entered. */
    enum Folder {
        /** files/share-staging: half-copied shared pictures and videos. */ STAGING,
        /** cache: the video copied here while it is read. */ CACHE,
        /** cache/reel-media: the key frames and sound made for the AI. */ REEL_MEDIA,
        /** files: only the library's temp files. */ FILES
    }

    /** What must be true for a file to be deleted, besides its name and age. */
    enum Guard {
        /** The sweep holds the lock no share is copied under (MediaBatch.trySweepStaging). */ STAGING_LOCK,
        /** No reel video is being read or turned into key frames and sound. */ VIDEO_READS,
        /** reels.json is read and good (state OK, not locked); deleted only through LibraryFile.dropTmp. */ REELS_LIBRARY,
        /** The same for shots.json. */ SHOTS_LIBRARY
    }

    /** Why a file was kept. */
    enum Reason {
        /** Not in the table: unknown, or in the wrong place. */ UNKNOWN_NAME,
        /** A link (the target is never looked at). */ SYMLINK,
        /** A folder or anything that is not a regular file. */ NOT_A_FILE,
        /** Modified in the future by its own clock. */ FUTURE,
        /** Younger than the rule's minimum age. */ TOO_YOUNG,
        /** A share may be copying. */ STAGING_BUSY,
        /** A video may be being read. */ VIDEO_BUSY,
        /** The library is not known to be good. */ LIBRARY_NOT_OK
    }

    /** One row of the table. */
    static final class Rule {
        final Folder folder;
        final Pattern name;
        final long minAgeMs;
        final Guard guard;

        Rule(Folder folder, String regex, long minAgeMs, Guard guard) {
            this.folder = folder;
            this.name = Pattern.compile(regex);
            this.minAgeMs = minAgeMs;
            this.guard = guard;
        }
    }

    /** The whole allowlist. Whole-name matches only ([0-9] is the ASCII digits). Adding a row is adding a place the app may delete from. */
    static final List<Rule> RULES = Collections.unmodifiableList(Arrays.asList(
            new Rule(Folder.STAGING, "copy-[0-9]+\\.part", 0, Guard.STAGING_LOCK),
            new Rule(Folder.CACHE, "reel-video\\.mp4", 6 * HOUR_MS, Guard.VIDEO_READS),
            new Rule(Folder.CACHE, "reel-video-local\\.mp4", 6 * HOUR_MS, Guard.VIDEO_READS),
            new Rule(Folder.REEL_MEDIA, "frame[0-3]\\.jpg", 6 * HOUR_MS, Guard.VIDEO_READS),
            new Rule(Folder.REEL_MEDIA, "sound\\.wav", 6 * HOUR_MS, Guard.VIDEO_READS),
            new Rule(Folder.FILES, "reels\\.json\\.tmp", HOUR_MS, Guard.REELS_LIBRARY),
            new Rule(Folder.FILES, "shots\\.json\\.tmp", HOUR_MS, Guard.SHOTS_LIBRARY)));

    /** One thing found in a folder, as the sweep saw it without following links. */
    static final class Entry {
        final Folder folder;
        final String name;
        final boolean regular;
        final boolean symlink;
        final long mtimeMs;
        final long size;

        Entry(Folder folder, String name, boolean regular, boolean symlink, long mtimeMs, long size) {
            this.folder = folder;
            this.name = name;
            this.regular = regular;
            this.symlink = symlink;
            this.mtimeMs = mtimeMs;
            this.size = size;
        }
    }

    /**
     * What is going on in the app right now. All four are given, so none can be forgotten: a value left out would otherwise
     * mean "free". Pass the unsafe answer (busy, not ok) for anything you do not know.
     */
    static final class Busy {
        /** True unless the sweep holds the copying lock. */
        final boolean stagingBusy;
        /** Reel videos being read now; anything but 0 counts as busy. */
        final int videoReads;
        final boolean reelsLibraryOk;
        final boolean shotsLibraryOk;

        Busy(boolean stagingBusy, int videoReads, boolean reelsLibraryOk, boolean shotsLibraryOk) {
            this.stagingBusy = stagingBusy;
            this.videoReads = videoReads;
            this.reelsLibraryOk = reelsLibraryOk;
            this.shotsLibraryOk = shotsLibraryOk;
        }

        /** The same, now that the sweep holds the copying lock. */
        Busy holdingStagingLock() {
            return new Busy(false, videoReads, reelsLibraryOk, shotsLibraryOk);
        }

        /** The same, with a fresh count of the videos being read (a read may have started since this was taken). */
        Busy withVideoReads(int reads) {
            return new Busy(stagingBusy, reads, reelsLibraryOk, shotsLibraryOk);
        }
    }

    /** DELETE (reason is null) or KEEP with the reason. rule is the table row that matched the name, or null. */
    static final class Verdict {
        final Entry entry;
        final Rule rule;
        final Reason reason;

        Verdict(Entry entry, Rule rule, Reason reason) {
            this.entry = entry;
            this.rule = rule;
            this.reason = reason;
        }

        boolean delete() {
            return reason == null;
        }
    }

    /** One verdict per entry, in the same order. now is the clock, in ms since 1970. */
    static List<Verdict> plan(List<Entry> listed, long now, Busy busy) {
        List<Verdict> out = new ArrayList<>(listed.size());
        for (Entry e : listed) out.add(decide(e, now, busy));
        return out;
    }

    static Verdict decide(Entry e, long now, Busy busy) {
        Rule rule = ruleFor(e);
        if (rule == null) return new Verdict(e, null, Reason.UNKNOWN_NAME);
        if (e.symlink) return new Verdict(e, rule, Reason.SYMLINK);
        if (!e.regular) return new Verdict(e, rule, Reason.NOT_A_FILE);
        long age = now - e.mtimeMs;
        if (e.mtimeMs > now || age < 0) return new Verdict(e, rule, Reason.FUTURE);  // (age < 0 also catches an overflow)
        if (age < rule.minAgeMs) return new Verdict(e, rule, Reason.TOO_YOUNG);
        Reason busyWhy = blocked(rule.guard, busy);
        if (busyWhy != null) return new Verdict(e, rule, busyWhy);
        return new Verdict(e, rule, null);
    }

    private static Rule ruleFor(Entry e) {
        for (Rule r : RULES) {
            if (r.folder == e.folder && r.name.matcher(e.name).matches()) return r;
        }
        return null;
    }

    private static Reason blocked(Guard g, Busy busy) {
        switch (g) {
            case STAGING_LOCK:
                return busy.stagingBusy ? Reason.STAGING_BUSY : null;
            case VIDEO_READS:
                return busy.videoReads != 0 ? Reason.VIDEO_BUSY : null;
            case REELS_LIBRARY:
                return busy.reelsLibraryOk ? null : Reason.LIBRARY_NOT_OK;
            case SHOTS_LIBRARY:
                return busy.shotsLibraryOk ? null : Reason.LIBRARY_NOT_OK;
            default:
                return Reason.UNKNOWN_NAME;  // a guard this code does not know: keep
        }
    }
}
