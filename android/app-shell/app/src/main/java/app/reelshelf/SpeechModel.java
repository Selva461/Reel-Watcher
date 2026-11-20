package app.reelshelf;

import android.content.Context;

import java.io.File;

/**
 * The offline speech model (Vosk, Apache 2.0, from alphacephei.com): turns what is said in a reel into text on the
 * phone. Downloaded once on request (about 40 MB), checked against its published size and fingerprints, and only then
 * unpacked into the app's own storage (ModelCatalog.SPEECH, ModelZip). Nothing is ever uploaded.
 */
final class SpeechModel {
    private SpeechModel() {
    }

    static final String NAME = ModelCatalog.SPEECH_FOLDER;
    static final long SIZE = ModelCatalog.SPEECH.bytes;

    static File root(Context c) {
        return new File(c.getFilesDir(), "speech");
    }

    /** The unpacked model folder, or null when it is not there yet. */
    static File dir(Context c) {
        File d = new File(root(c), NAME);
        for (String marker : ModelCatalog.SPEECH_ZIP.oneOf) if (new File(d, marker).isDirectory()) return d;
        return null;
    }

    static void delete(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) delete(k);
        f.delete();
    }
}
