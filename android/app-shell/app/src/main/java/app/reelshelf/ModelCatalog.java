package app.reelshelf;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * The models Reel Shelf may download, and the one place that says what each one must be: its file name, the pinned
 * address, the exact size and the SHA-256 fingerprint. Java decides what is downloaded (the page only names a model),
 * and ModelVerifier refuses to install anything that is not exactly this. The three AI language models are in ALL; the
 * offline speech model (a ZIP, SPEECH) is a separate row the page cannot ask for by name. Pure Java (no Android types),
 * tested on a computer.
 *
 * Every Hugging Face address contains the full 40-digit commit (".../resolve/&lt;commit&gt;/..."), never "main", so the
 * bytes behind an address cannot change under a paused download. To move a row to a newer file: read the commit, size and
 * "lfs.sha256" from https://huggingface.co/api/models/&lt;repo&gt;/revision/main?blobs=true, do one real download and
 * sha256sum it, and change the row and the display size in the page's MODELS (assets/local/local.js) in the same change.
 */
final class ModelCatalog {
    private ModelCatalog() {
    }

    /** One model. */
    static final class Entry {
        /** Short name the page uses (the page's MODELS id). */
        final String id;
        /** File name in the app's models folder, and the name the page sends. */
        final String file;
        /** The pinned address. */
        final String url;
        /** The exact size in bytes. */
        final long bytes;
        /** The SHA-256 of the file, 64 lowercase hex digits. */
        final String sha256;
        /** Older fingerprints that are still good files (for models already on the phone). Empty: a new download is always the pinned file. */
        final List<String> accepted;
        /** The MD5 the publisher lists, checked besides the SHA-256 (32 lowercase hex digits), or null when there is none. */
        final String md5;
        /** The one host this file comes from, with no redirect at all (the speech model), or null: Hugging Face and its download hosts. */
        final String onlyHost;

        Entry(String id, String file, String url, long bytes, String sha256, String... accepted) {
            this(id, file, url, bytes, sha256, null, null, Arrays.asList(accepted));
        }

        private Entry(String id, String file, String url, long bytes, String sha256, String md5, String onlyHost, List<String> accepted) {
            this.id = id;
            this.file = file;
            this.url = url;
            this.bytes = bytes;
            this.sha256 = sha256;
            this.md5 = md5;
            this.onlyHost = onlyHost;
            this.accepted = Collections.unmodifiableList(accepted);
        }

        /** A file that must come from exactly one host (no redirect) and also match the MD5 its publisher lists. */
        static Entry fromOneHost(String id, String file, String url, long bytes, String sha256, String md5, String onlyHost) {
            return new Entry(id, file, url, bytes, sha256, md5, onlyHost, Collections.<String>emptyList());
        }
    }

    /** Shown when a name is not in the table. */
    static final String UNKNOWN = "Only the models listed in Settings can be downloaded. Use 'Use my own model file (.litertlm)' for others.";

    private static final String HF = "https://huggingface.co/litert-community/";

    // Size and sha256 come from Hugging Face's own metadata (the LFS oid is the sha256 of the file), read on 2026-11-17.
    // Confirmed by one real download of each pinned address on 2026-11-18 (streamed through sha256sum and wc -c, nothing
    // stored): qwen 1597922856 bytes, gemma4 2588147712 bytes and gemma4e4 3659530240 bytes, and all three sha256 values
    // equal the ones below.
    static final Entry QWEN = new Entry("qwen", "Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm",
            HF + "Qwen2.5-1.5B-Instruct/resolve/60257f9f1d00ca1f24cc5ce3b829b4139be1ca2b/Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm",
            1597922856L, "c4a9b7289365ab80fe599b844b77ad253eb3c53fb0e5d963d699146a6f01255e");
    static final Entry GEMMA4 = new Entry("gemma4", "gemma-4-E2B-it.litertlm",
            HF + "gemma-4-E2B-it-litert-lm/resolve/2d74ac41a33d7da82f39f7d5720a04c68514a103/gemma-4-E2B-it.litertlm",
            2588147712L, "181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c");
    static final Entry GEMMA4_E4 = new Entry("gemma4e4", "gemma-4-E4B-it.litertlm",
            HF + "gemma-4-E4B-it-litert-lm/resolve/f254b5ba6e36f7d89cc7892e268e9877bc20f0a0/gemma-4-E4B-it.litertlm",
            3659530240L, "0b2a8980ce155fd97673d8e820b4d29d9c7d99b8fa6806f425d969b145bd52e0");

    static final List<Entry> ALL = Collections.unmodifiableList(Arrays.asList(QWEN, GEMMA4, GEMMA4_E4));

    /** The speech model's folder inside its ZIP and in the app (Vosk, Apache 2.0). */
    static final String SPEECH_FOLDER = "vosk-model-small-en-us-0.15";
    /** What the published ZIP holds: 20 entries (files and folders), 70898967 bytes once unpacked (read from the real file, 2026-11-18). */
    static final int SPEECH_ENTRIES = 20;
    static final long SPEECH_UNPACKED = 70_898_967L;

    // The speech model comes from alphacephei.com, which has no revision in its addresses, so the file is held to three
    // facts: its exact size, the MD5 the vendor lists in https://alphacephei.com/vosk/models/model-list.json, and a SHA-256
    // measured by one real download on 2026-11-18 (the response had no redirect; curl | sha256sum and md5sum on the saved
    // file; the ZIP starts with PK\x03\x04). The size equals Content-Length and the MD5 equals the vendor's. Not in ALL:
    // the page cannot ask for it by name through downloadModel, and it is not an AI language model.
    static final Entry SPEECH = Entry.fromOneHost("speech", SPEECH_FOLDER + ".zip",
            "https://alphacephei.com/vosk/models/" + SPEECH_FOLDER + ".zip",
            41_205_931L, "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
            "09ab50ccd62b674cbaa231b825f9c1cb", "alphacephei.com");

    /**
     * How the speech ZIP may be unpacked. The pinned size and fingerprints are what prove the ZIP; these limits only stop a
     * runaway unpack, so they sit a little (10%) above what the published file holds: well below the old 400 MB cap, but not
     * so tight that moving the row to a re-packed copy of the same model (an extra folder entry, a longer README) fails
     * until these numbers are edited in the same step.
     */
    static final ModelZip.Plan SPEECH_ZIP = new ModelZip.Plan(SPEECH_FOLDER, SPEECH_ENTRIES + SPEECH_ENTRIES / 10,
            SPEECH_UNPACKED + SPEECH_UNPACKED / 10, "am", "conf");

    /** The model used when no name is given (as LocalModel.file does). */
    static final Entry DEFAULT = QWEN;

    /**
     * The row for the name the page sent, or null when it is not in the table. An empty name is the default model; only the
     * last part of a name counts (the same rule as LocalModel.file), and it must match a file name exactly.
     */
    static Entry lookup(String name) {
        if (name == null || name.isEmpty()) return DEFAULT;
        String file = new File(name).getName();
        for (Entry e : ALL) if (e.file.equals(file)) return e;
        return null;
    }
}
