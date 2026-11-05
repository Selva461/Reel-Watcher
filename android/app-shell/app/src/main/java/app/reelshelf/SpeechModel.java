package app.reelshelf;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * The offline speech model (Vosk, Apache 2.0, from alphacephei.com): turns what is said in a reel into text on the
 * phone. Downloaded once on request (about 40 MB), unpacked into the app's own storage. Nothing is ever uploaded.
 */
final class SpeechModel {
    private SpeechModel() {
    }

    static final String NAME = "vosk-model-small-en-us-0.15";
    static final String URL = "https://alphacephei.com/vosk/models/" + NAME + ".zip";
    static final long SIZE = 41_205_931L;

    static File root(Context c) {
        return new File(c.getFilesDir(), "speech");
    }

    /** The unpacked model folder, or null when it is not there yet. */
    static File dir(Context c) {
        File d = new File(root(c), NAME);
        return new File(d, "am").isDirectory() || new File(d, "conf").isDirectory() ? d : null;
    }

    /** Unpacks the downloaded ZIP into the app's storage (only paths inside the model folder are written). */
    static void unpack(File zip, File into) throws IOException {
        String base = into.getCanonicalPath() + File.separator;
        try (ZipFile z = new ZipFile(zip)) {
            Enumeration<? extends ZipEntry> all = z.entries();
            long total = 0;
            while (all.hasMoreElements()) {
                ZipEntry e = all.nextElement();
                File out = new File(into, e.getName());
                if (!out.getCanonicalPath().startsWith(base)) throw new IOException("bad file in the speech model");
                if (e.isDirectory()) {
                    out.mkdirs();
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null) parent.mkdirs();
                try (InputStream in = z.getInputStream(e); OutputStream o = new FileOutputStream(out)) {
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        total += n;
                        if (total > 400L * 1024 * 1024) throw new IOException("speech model too big");
                        o.write(buf, 0, n);
                    }
                }
            }
        }
    }

    static void delete(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) delete(k);
        f.delete();
    }
}
