package app.reelshelf;

import android.content.ContentResolver;
import android.content.res.AssetFileDescriptor;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * Pictures and videos shared to Reel Shelf (or chosen in its picker) as {@link MediaBatch} items. Making the list does no
 * file work, so it is safe on the main thread; everything that asks the other app (its name, type, size, the data) happens
 * later, on the copying thread.
 */
final class SharedItems {
    /** The most one share keeps: more are reported as not saved. */
    static final int MAX_PICTURES = 2000;
    static final int MAX_VIDEOS = 200;
    /**
     * Free space that must stay after a copy. The library is saved through a temporary copy of itself (about 60 MB at 10,000
     * reels), so a copy that would leave less than this could stop the library from being saved.
     */
    static final long RESERVE_BYTES = 100L * 1024 * 1024;

    private SharedItems() {
    }

    /** Where half-written copies live: next to the inboxes (the same disk, so the final rename is atomic), never inside them. */
    static File staging(Context c) {
        return new File(c.getFilesDir(), "share-staging");
    }

    static List<MediaBatch.Item> pictures(Context c, List<Uri> uris) {
        return wrap(c, uris, false);
    }

    static List<MediaBatch.Item> videos(Context c, List<Uri> uris) {
        return wrap(c, uris, true);
    }

    private static List<MediaBatch.Item> wrap(Context c, List<Uri> uris, boolean video) {
        List<MediaBatch.Item> out = new ArrayList<>();
        Context app = c.getApplicationContext();
        if (uris != null) for (Uri u : uris) if (u != null) out.add(new UriItem(app, u, video));
        return out;
    }

    private static final class UriItem implements MediaBatch.Item {
        private final Context c;
        private final Uri uri;
        private final boolean video;
        private long size = Long.MIN_VALUE;
        private volatile long exact = -1;

        UriItem(Context c, Uri uri, boolean video) {
            this.c = c;
            this.uri = uri;
            this.video = video;
        }

        @Override
        public String label() {
            try (Cursor q = c.getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                if (q != null && q.moveToFirst() && !q.isNull(0)) return q.getString(0);
            } catch (RuntimeException e) {
                // the other app does not say: the list calls it "item N"
            }
            return null;
        }

        @Override
        public MediaCopy.Rules rules() throws MediaCopy.CopyException {
            String type = c.getContentResolver().getType(uri);
            if (type != null && !type.startsWith(video ? "video/" : "image/")) {
                throw new MediaCopy.CopyException(MediaCopy.Kind.UNSUPPORTED, video ? "it is not a video" : "it is not a picture");
            }
            String ext = video ? ".mp4" : type != null && type.endsWith("png") ? ".png" : type != null && type.endsWith("webp") ? ".webp" : ".jpg";
            return new MediaCopy.Rules(video ? ScreenshotReader.videoInbox(c) : ScreenshotReader.inbox(c), staging(c), video ? "video_" : "shot_", ext,
                    video ? ScreenshotReader.MAX_VIDEO_FILE : ScreenshotReader.MAX_PICTURE, RESERVE_BYTES);
        }

        @Override
        public MediaCopy.Source source() {
            return new MediaCopy.Source() {
                @Override
                public InputStream open() throws IOException {
                    // what openInputStream does for a content address, but keeping the length the provider DECLARED for this stream
                    // (not getLength(), which guesses the file's size when nothing was declared: wrong for an asset that starts at an offset)
                    AssetFileDescriptor afd = c.getContentResolver().openAssetFileDescriptor(uri, "r");
                    if (afd == null) return null;
                    exact = afd.getDeclaredLength() > 0 ? afd.getDeclaredLength() : -1;
                    return afd.createInputStream();
                }

                @Override
                public long exactSize() {
                    return exact;
                }

                @Override
                public long size() {
                    if (size == Long.MIN_VALUE) {
                        size = -1;
                        ContentResolver cr = c.getContentResolver();
                        try (Cursor q = cr.query(uri, new String[]{OpenableColumns.SIZE}, null, null, null)) {
                            if (q != null && q.moveToFirst() && !q.isNull(0) && q.getLong(0) > 0) size = q.getLong(0);
                        } catch (RuntimeException e) {
                            // not said: the copy counts what it reads
                        }
                    }
                    return size;
                }
            };
        }
    }
}
