package app.reelshelf;

import android.content.Context;
import android.graphics.Bitmap;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMetadataRetriever;

import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.text.Normalizer;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

/**
 * What a reel shows and says, worked out on the phone from its video file:
 * - the text on screen: one frame every 2 seconds, read with the same text reader as screenshots;
 * - the spoken words: the sound track, turned into text by the offline Vosk speech model (when downloaded).
 * The video comes from Instagram's picture/video servers with no account and no cookies, is kept in the app's
 * cache only while it is read (at most 60 MB) and deleted right after. Nothing is uploaded anywhere.
 */
final class ReelVideo {
    private ReelVideo() {
    }

    static final long MAX_VIDEO = 60L * 1024 * 1024;
    private static final long FRAME_EVERY_US = 2_000_000L;
    private static final int MAX_FRAMES = 90;      // 3 minutes of frames: a whole reel
    private static final long MAX_AUDIO_US = 180_000_000L;  // 3 minutes of speech
    private static final int RATE = 16000;

    /** Instagram's video servers, https only (the same rule as cover pictures). */
    static boolean videoHost(String url) {
        return LocalBridge.coverHost(url);
    }

    /** Reads one reel video. Returns {screen, speech, seconds, speechModel}. */
    static JSONObject read(Context ctx, ScreenshotReader ocr, File speechModel, String url, Stop stop) throws Exception {
        File f = new File(ctx.getCacheDir(), "reel-video.mp4");
        try {
            fetch(url, f, stop);
            return analyse(ctx, ocr, speechModel, f, stop);
        } finally {
            f.delete();
        }
    }

    /**
     * Reads a reel video that is on the phone (saved with Instagram's own Download, a screen recording, or shared to
     * Reel Shelf). The whole video: frames for the text on screen, speech to text, key frames and sound for the AI.
     * Copied to the app's cache while it is read, then the copy is deleted; the original is never changed.
     */
    static JSONObject readLocal(Context ctx, ScreenshotReader ocr, File speechModel, android.net.Uri uri, Stop stop) throws Exception {
        File f = new File(ctx.getCacheDir(), "reel-video-local.mp4");
        try {
            try (InputStream in = ctx.getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(f)) {
                if (in == null) throw new IOException("Could not open the video");
                byte[] buf = new byte[65536];
                long total = 0;
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (stop.now()) throw new IOException("stopped");
                    total += n;
                    if (total > ScreenshotReader.MAX_VIDEO_FILE) throw new IOException("video too big (over 500 MB)");
                    out.write(buf, 0, n);
                }
            }
            return analyse(ctx, ocr, speechModel, f, stop);
        } finally {
            f.delete();
        }
    }

    private static JSONObject analyse(Context ctx, ScreenshotReader ocr, File speechModel, File f, Stop stop) throws Exception {
        JSONObject o = new JSONObject();
        long us = durationUs(f);
        o.put("seconds", us / 1_000_000L);
        o.put("screen", screenText(f, us, ocr, stop));
        byte[] pcm = decodePcm(f, stop);
        boolean haveModel = speechModel != null;
        o.put("speechModel", haveModel);
        o.put("speech", haveModel && pcm.length > 0 ? vosk(pcm, speechModel, stop) : "");
        o.put("media", saveMedia(ctx, f, us, pcm));
        return o;
    }

    interface Stop {
        boolean now();
    }

    private static void fetch(String url, File dest, Stop stop) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(15000);
            c.setReadTimeout(30000);
            c.setInstanceFollowRedirects(false);
            c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36");
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("Instagram answered " + code + " for the video");
            long len = c.getContentLengthLong();
            if (len > MAX_VIDEO) throw new IOException("video too big");
            try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[65536];
                long total = 0;
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (stop.now()) throw new IOException("stopped");
                    total += n;
                    if (total > MAX_VIDEO) throw new IOException("video too big");
                    out.write(buf, 0, n);
                }
            }
        } finally {
            c.disconnect();
        }
    }

    private static long durationUs(File f) {
        MediaMetadataRetriever m = new MediaMetadataRetriever();
        try {
            m.setDataSource(f.getPath());
            String d = m.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            return d == null ? 0 : Long.parseLong(d) * 1000L;
        } catch (Exception e) {
            return 0;
        } finally {
            try {
                m.release();
            } catch (Exception ignored) {
            }
        }
    }

    // ------------------------------------------------------------------ text on screen

    private static String fold(String s) {
        return Normalizer.normalize(s.toLowerCase(Locale.ROOT), Normalizer.Form.NFKD).replaceAll("[^\\p{L}\\p{N}]+", "");
    }

    /** One frame every 2 seconds, read; each different line kept once, in the order it first appears. */
    static String screenText(File f, long durationUs, ScreenshotReader ocr, Stop stop) {
        Set<String> seen = new LinkedHashSet<>();
        StringBuilder out = new StringBuilder();
        MediaMetadataRetriever m = new MediaMetadataRetriever();
        try {
            m.setDataSource(f.getPath());
            long end = durationUs > 0 ? durationUs : FRAME_EVERY_US * 15;
            int frames = 0;
            for (long t = 500_000L; t < end && frames < MAX_FRAMES && !stop.now(); t += FRAME_EVERY_US, frames++) {
                Bitmap bm = null;
                try {
                    bm = m.getScaledFrameAtTime(t, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 1280, 1280);
                    if (bm == null) continue;
                    for (String line : ocr.textOf(bm).split("\n")) {
                        String l = line.trim();
                        String k = fold(l);
                        if (k.length() < 3 || seen.contains(k)) continue;
                        seen.add(k);
                        out.append(l).append('\n');
                    }
                } catch (Exception ignored) {
                    // one bad frame: go on
                } finally {
                    if (bm != null) bm.recycle();
                }
            }
        } catch (Exception ignored) {
            // not a video we can open
        } finally {
            try {
                m.release();
            } catch (Exception ignored) {
            }
        }
        return out.toString().trim();
    }

    // ------------------------------------------------------------------ spoken words

    // ------------------------------------------------------------------ what the on-phone AI gets to see and hear

    /** Where the current reel's key frames and sound clip are kept for the on-phone AI (replaced for every reel). */
    static File mediaDir(Context ctx) {
        return new File(ctx.getCacheDir(), "reel-media");
    }

    static void clearMedia(Context ctx) {
        File[] old = mediaDir(ctx).listFiles();
        if (old != null) for (File x : old) x.delete();
    }

    /** 4 key frames (JPEG) and the first 30 seconds of sound (16 kHz mono WAV). Returns how many files were made. */
    static int saveMedia(Context ctx, File video, long durationUs, byte[] pcm) {
        clearMedia(ctx);
        File dir = mediaDir(ctx);
        dir.mkdirs();
        int n = 0;
        MediaMetadataRetriever m = new MediaMetadataRetriever();
        try {
            m.setDataSource(video.getPath());
            long d = durationUs > 0 ? durationUs : 20_000_000L;
            double[] at = {0.12, 0.37, 0.62, 0.87};
            for (int i = 0; i < at.length; i++) {
                Bitmap bm = null;
                try {
                    bm = m.getScaledFrameAtTime((long) (d * at[i]), MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 768, 768);
                    if (bm == null) continue;
                    try (OutputStream o = new FileOutputStream(new File(dir, "frame" + i + ".jpg"))) {
                        bm.compress(Bitmap.CompressFormat.JPEG, 85, o);
                    }
                    n++;
                } catch (Exception ignored) {
                } finally {
                    if (bm != null) bm.recycle();
                }
            }
        } catch (Exception ignored) {
        } finally {
            try {
                m.release();
            } catch (Exception ignored) {
            }
        }
        if (pcm.length > RATE) {
            int len = Math.min(pcm.length, RATE * 2 * 30) & ~1;
            try (OutputStream o = new FileOutputStream(new File(dir, "sound.wav"))) {
                o.write(wavHeader(len));
                o.write(pcm, 0, len);
                n++;
            } catch (Exception ignored) {
            }
        }
        return n;
    }

    private static byte[] wavHeader(int dataLen) {
        ByteBuffer b = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        b.put("RIFF".getBytes()).putInt(36 + dataLen).put("WAVE".getBytes());
        b.put("fmt ".getBytes()).putInt(16).putShort((short) 1).putShort((short) 1).putInt(RATE).putInt(RATE * 2).putShort((short) 2).putShort((short) 16);
        b.put("data".getBytes()).putInt(dataLen);
        return b.array();
    }

    // ------------------------------------------------------------------ spoken words

    /** Feeds 16 kHz mono PCM to the Vosk recognizer and returns the words. */
    static String vosk(byte[] pcm, File modelDir, Stop stop) throws Exception {
        StringBuilder words = new StringBuilder();
        try (Model model = new Model(modelDir.getPath()); Recognizer rec = new Recognizer(model, RATE)) {
            int chunk = RATE;  // half a second of 16-bit samples
            for (int i = 0; i < pcm.length && !stop.now(); i += chunk) {
                byte[] part = java.util.Arrays.copyOfRange(pcm, i, Math.min(pcm.length, i + chunk));
                if (rec.acceptWaveForm(part, part.length)) add(words, rec.getResult());
            }
            add(words, rec.getFinalResult());
        }
        return words.toString().trim();
    }

    /** The sound track decoded to 16 kHz mono 16-bit PCM (at most 3 minutes); empty when there is none. */
    static byte[] decodePcm(File f, Stop stop) throws Exception {
        MediaExtractor ex = new MediaExtractor();
        MediaCodec codec = null;
        java.io.ByteArrayOutputStream all = new java.io.ByteArrayOutputStream();
        try {
            ex.setDataSource(f.getPath());
            int track = -1;
            MediaFormat fmt = null;
            for (int i = 0; i < ex.getTrackCount(); i++) {
                MediaFormat tf = ex.getTrackFormat(i);
                String mime = tf.getString(MediaFormat.KEY_MIME);
                if (mime != null && mime.startsWith("audio/")) {
                    track = i;
                    fmt = tf;
                    break;
                }
            }
            if (track < 0) return new byte[0];
            ex.selectTrack(track);
            codec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME));
            codec.configure(fmt, null, null, 0);
            codec.start();
            int srcRate = fmt.getInteger(MediaFormat.KEY_SAMPLE_RATE);
            int channels = fmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inDone = false, outDone = false;
            double pos = 0;  // position in the source samples for resampling
            while (!outDone && !stop.now()) {
                if (!inDone) {
                    int ib = codec.dequeueInputBuffer(10_000);
                    if (ib >= 0) {
                        ByteBuffer buf = codec.getInputBuffer(ib);
                        int n = buf == null ? -1 : ex.readSampleData(buf, 0);
                        if (n < 0 || ex.getSampleTime() > MAX_AUDIO_US) {
                            codec.queueInputBuffer(ib, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inDone = true;
                        } else {
                            codec.queueInputBuffer(ib, 0, n, ex.getSampleTime(), 0);
                            ex.advance();
                        }
                    }
                }
                int ob = codec.dequeueOutputBuffer(info, 10_000);
                if (ob == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat of = codec.getOutputFormat();
                    srcRate = of.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    channels = of.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                } else if (ob >= 0) {
                    ByteBuffer out = codec.getOutputBuffer(ob);
                    if (out != null && info.size > 0) {
                        out.position(info.offset);
                        out.limit(info.offset + info.size);
                        short[] pcm = new short[info.size / 2];
                        out.order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm);
                        int frames = pcm.length / Math.max(1, channels);
                        double step = (double) srcRate / RATE;  // mono, then 16 kHz (linear interpolation)
                        int outN = (int) Math.max(0, Math.floor((frames - pos) / step));
                        byte[] bytes = new byte[outN * 2];
                        for (int i = 0; i < outN; i++) {
                            double x = pos + i * step;
                            int a = Math.min((int) x, frames - 1);
                            int b = Math.min(a + 1, frames - 1);
                            double w = x - a;
                            double va = 0, vb = 0;
                            for (int ch = 0; ch < channels; ch++) {
                                va += pcm[a * channels + ch];
                                vb += pcm[b * channels + ch];
                            }
                            int v = (int) Math.round(((1 - w) * va + w * vb) / channels);
                            v = Math.max(Short.MIN_VALUE, Math.min(Short.MAX_VALUE, v));
                            bytes[2 * i] = (byte) (v & 0xff);
                            bytes[2 * i + 1] = (byte) ((v >> 8) & 0xff);
                        }
                        pos = pos + outN * step - frames;
                        all.write(bytes, 0, bytes.length);
                    }
                    codec.releaseOutputBuffer(ob, false);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) outDone = true;
                }
            }
        } finally {
            if (codec != null) {
                try {
                    codec.stop();
                } catch (Exception ignored) {
                }
                codec.release();
            }
            ex.release();
        }
        return all.toByteArray();
    }

    private static void add(StringBuilder words, String json) {
        try {
            String t = new JSONObject(json).optString("text", "").trim();
            if (!t.isEmpty()) words.append(t).append(". ");
        } catch (Exception ignored) {
        }
    }
}
