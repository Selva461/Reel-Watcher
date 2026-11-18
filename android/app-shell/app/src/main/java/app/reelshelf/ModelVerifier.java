package app.reelshelf;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Downloads one catalog model (ModelCatalog.Entry) so that a wrong or half-written file can never be taken for the model:
 * the size is checked against the catalog before anything is written and while writing, the SHA-256 is computed as the
 * bytes are written, and only a file with exactly the catalog size and fingerprint is renamed to its final name. A
 * download that fails the check loses only its own ".part" file: a model that is already installed is never touched.
 * A paused download continues with a Range request; the part already on disk is read once through the same digest.
 * Pure Java (files and HTTP only), tested on a computer against a local server.
 */
final class ModelVerifier {
    interface Progress {
        void on(long done, long total);
    }

    /** What the caller decides while the download runs. */
    interface Control {
        boolean stopped();

        default long freeSpace(File dir) {
            return dir.getUsableSpace();
        }
    }

    /** Space that must stay free besides the model itself. */
    static final long RESERVE = 200L * 1024 * 1024;

    static final String DAMAGED = "The download was damaged or changed on the way (check failed). Nothing was installed. Tap Download to try again.";
    static final String STOPPED_EARLY = "The download stopped early. Tap Download to continue.";
    static final String WRONG_SIZE = "The server did not send the published model (wrong size). Nothing was written. "
            + "If this network asks you to sign in, do that and tap Download to try again.";
    private static final String ODD_ANSWER = "The download server answered in an unexpected way. Nothing was written. Try again later.";

    private static final int BUFFER = 64 * 1024;
    private static final int MAX_HOPS = 6;
    private static final Pattern CONTENT_RANGE = Pattern.compile("^bytes (\\d+)-(\\d+)/(\\d+)$");

    private final Control control;
    /** Tests only: connect to this base (for example "http://127.0.0.1:8080") instead of the address's own host. The address is still checked as given. */
    private final String testBase;

    ModelVerifier(Control control) {
        this(control, null);
    }

    ModelVerifier(Control control, String testBase) {
        this.control = control;
        this.testBase = testBase;
    }

    /** Hugging Face and its download hosts only: huggingface.co, *.huggingface.co and *.hf.co. */
    static boolean allowedHost(String host) {
        if (host == null) return false;
        String h = host.toLowerCase(Locale.ROOT);
        return h.equals("huggingface.co") || h.endsWith(".huggingface.co") || h.endsWith(".hf.co");
    }

    /**
     * Downloads the model into dest (resuming dest + ".part") and installs it only when it is exactly the catalog's file.
     * Throws InterruptedIOException("paused") when stopped (the part stays); any other IOException says why in plain words.
     */
    void download(ModelCatalog.Entry e, File dest, Progress p) throws IOException {
        File part = new File(dest.getPath() + ".part");
        MessageDigest sha = digest();
        long have = part.exists() ? part.length() : 0;
        if (have > e.bytes) {  // cannot be a piece of this model
            deleteQuietly(part);
            have = 0;
        }
        File dir = dest.getAbsoluteFile().getParentFile();
        while (true) {
            if (control.freeSpace(dir) < (e.bytes - have) + RESERVE) {
                throw new IOException("Not enough free space: the model needs " + (e.bytes / (1024 * 1024)) + " MB.");
            }
            sha.reset();
            if (have > 0) {
                p.on(have, e.bytes);
                feed(sha, part, have);
            }
            HttpURLConnection c = open(e.url, have);
            try {
                int code = c.getResponseCode();
                if (code == 416 && have > 0) {  // the server holds fewer bytes than the part: only a complete, matching part is the model
                    c.disconnect();
                    if (have == e.bytes && hex(sha.digest()).equals(e.sha256)) {
                        install(part, dest);
                        return;
                    }
                    deleteQuietly(part);
                    have = 0;
                    continue;
                }
                boolean append;
                if (code == 200) {  // the whole file: from the start
                    long len = c.getContentLengthLong();
                    if (len >= 0 && len != e.bytes) throw new IOException(WRONG_SIZE);
                    append = false;
                    have = 0;
                    sha.reset();
                } else if (code == 206) {
                    Matcher m = CONTENT_RANGE.matcher(String.valueOf(c.getHeaderField("Content-Range")).trim());
                    if (!m.matches()) throw new IOException(ODD_ANSWER);
                    long first = Long.parseLong(m.group(1)), last = Long.parseLong(m.group(2)), total = Long.parseLong(m.group(3));
                    if (total != e.bytes || last != total - 1) throw new IOException(WRONG_SIZE);
                    if (first != have) throw new IOException(ODD_ANSWER);
                    append = true;
                } else {
                    throw new IOException("The download server answered " + code + ". Try again later.");
                }
                write(c, e, part, append, have, sha, p);
            } finally {
                c.disconnect();
            }
            if (part.length() != e.bytes) throw new IOException(STOPPED_EARLY);
            if (!hex(sha.digest()).equals(e.sha256)) {
                deleteQuietly(part);  // only our own part: an installed model is never touched
                throw new IOException(DAMAGED);
            }
            install(part, dest);
            return;
        }
    }

    /** Reads the response into the part, hashing as it goes. Stops (and drops the part) when more than the catalog size arrives. */
    private void write(HttpURLConnection c, ModelCatalog.Entry e, File part, boolean append, long have, MessageDigest sha, Progress p) throws IOException {
        long done = have;
        long lastReport = 0;
        boolean tooLong = false;
        try (InputStream raw = c.getInputStream(); DigestInputStream in = new DigestInputStream(raw, sha);
             OutputStream out = new FileOutputStream(part, append)) {
            byte[] buf = new byte[BUFFER];
            int n;
            while ((n = in.read(buf)) > 0) {
                if (control.stopped()) throw new InterruptedIOException("paused");
                if (done + n > e.bytes) {
                    tooLong = true;
                    break;
                }
                try {
                    out.write(buf, 0, n);
                } catch (IOException w) {
                    if (String.valueOf(w.getMessage()).contains("No space left")) throw new IOException("Phone storage is full. Free some space and tap Continue download.", w);
                    throw w;
                }
                done += n;
                if (done - lastReport > 4L * 1024 * 1024) {
                    lastReport = done;
                    p.on(done, e.bytes);
                }
            }
        }
        if (tooLong) {  // not the published file, whatever came before
            deleteQuietly(part);
            throw new IOException(DAMAGED);
        }
        p.on(done, e.bytes);
    }

    /** Feeds the first n bytes of the part through the digest (once, when a download continues). */
    private void feed(MessageDigest sha, File part, long n) throws IOException {
        try (InputStream in = new FileInputStream(part)) {
            byte[] buf = new byte[BUFFER];
            long left = n;
            while (left > 0) {
                if (control.stopped()) throw new InterruptedIOException("paused");
                int r = in.read(buf, 0, (int) Math.min(buf.length, left));
                if (r < 0) throw new IOException("The partial download could not be read. Delete the model and download it again.");
                sha.update(buf, 0, r);
                left -= r;
            }
        }
    }

    private static void install(File part, File dest) throws IOException {
        try {
            try {
                Files.move(part.toPath(), dest.toPath(), StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException x) {
                Files.move(part.toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException x) {
            throw new IOException("Could not save the model file", x);
        }
    }

    /** Follows redirects by hand (so the Range header reaches the final server); every address must be https on an allowed host. */
    private HttpURLConnection open(String url, long from) throws IOException {
        URL u = new URL(url);
        for (int hop = 0; hop < MAX_HOPS; hop++) {
            if (!"https".equals(u.getProtocol())) throw new IOException("Refused an insecure download address");
            if (!allowedHost(u.getHost())) throw new IOException("Refused a download from another site (" + u.getHost() + "). Nothing was written.");
            HttpURLConnection c = (HttpURLConnection) (testBase == null ? u : new URL(testBase + u.getFile())).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            c.setRequestProperty("User-Agent", "ReelShelf-Android");
            if (from > 0) c.setRequestProperty("Range", "bytes=" + from + "-");
            int code = c.getResponseCode();
            String to = c.getHeaderField("Location");
            if (code >= 300 && code < 400 && to != null) {
                c.disconnect();
                u = new URL(u, to);
                continue;
            }
            return c;
        }
        throw new IOException("Too many redirects");
    }

    private static void deleteQuietly(File f) {
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException x) {
            throw new IllegalStateException(x);  // every Java has SHA-256
        }
    }

    static String hex(byte[] b) {
        StringBuilder s = new StringBuilder();
        for (byte x : b) s.append(Character.forDigit((x >> 4) & 15, 16)).append(Character.forDigit(x & 15, 16));
        return s.toString();
    }
}
