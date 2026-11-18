package app.reelshelf;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * The AI models Reel Shelf may download, and the one place that says what each one must be: its file name, the pinned
 * address, the exact size and the SHA-256 fingerprint. Java decides what is downloaded (the page only names a model),
 * and ModelVerifier refuses to install anything that is not exactly this. Pure Java (no Android types), tested on a computer.
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

        Entry(String id, String file, String url, long bytes, String sha256, String... accepted) {
            this.id = id;
            this.file = file;
            this.url = url;
            this.bytes = bytes;
            this.sha256 = sha256;
            this.accepted = Collections.unmodifiableList(Arrays.asList(accepted));
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
