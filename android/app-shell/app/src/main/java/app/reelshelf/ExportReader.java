package app.reelshelf;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Plain Java (no Android), so it can be checked on any computer.
 * Reads only the saved-posts files out of Instagram's "Download your information" ZIP. It uses the ZIP's table of
 * contents (java.util.zip.ZipFile), so big exports, ZIP64 and files written with data descriptors all work.
 */
final class ExportReader {
    private ExportReader() {
    }

    /** saved_posts.json, saved_collections.json (or the .html versions), wherever they sit in the ZIP. */
    private static final Pattern SAVED = Pattern.compile("(?i)(^|/)saved[^/]*\\.(json|html)$");

    /** One saved-posts file is a few MB even for thousands of reels; anything bigger is not what we want. */
    static final long MAX_ENTRY = 40L * 1024 * 1024;

    static boolean isSavedFile(String entryName) {
        return entryName != null && SAVED.matcher(entryName).find();
    }

    /** A file read from the export: its name (without folders) and its text. */
    static final class Part {
        final String name;
        final String text;

        Part(String name, String text) {
            this.name = name;
            this.text = text;
        }
    }

    /**
     * The saved-posts files inside the export ZIP. Nothing else in the ZIP is read. Each file is capped at
     * MAX_ENTRY bytes after unpacking, so a broken or hostile ZIP cannot fill the phone's memory.
     */
    static List<Part> readSaved(File zip) throws IOException {
        List<Part> out = new ArrayList<>();
        try (ZipFile z = new ZipFile(zip)) {
            Enumeration<? extends ZipEntry> all = z.entries();
            while (all.hasMoreElements()) {
                ZipEntry e = all.nextElement();
                String name = e.getName();
                if (e.isDirectory() || !isSavedFile(name)) continue;
                if (e.getSize() > MAX_ENTRY) continue;
                byte[] data = readCapped(z.getInputStream(e), MAX_ENTRY);
                if (data == null) continue;
                out.add(new Part(name.substring(name.lastIndexOf('/') + 1), new String(data, StandardCharsets.UTF_8)));
            }
        }
        return out;
    }

    private static byte[] readCapped(InputStream in, long cap) throws IOException {
        try (InputStream s = in) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] b = new byte[65536];
            long total = 0;
            int n;
            while ((n = s.read(b)) > 0) {
                total += n;
                if (total > cap) return null;
                buf.write(b, 0, n);
            }
            return buf.toByteArray();
        }
    }
}
