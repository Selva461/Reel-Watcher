package app.reelshelf;

import android.content.Context;

import com.google.ai.edge.litertlm.Backend;
import com.google.ai.edge.litertlm.Contents;
import com.google.ai.edge.litertlm.Conversation;
import com.google.ai.edge.litertlm.ConversationConfig;
import com.google.ai.edge.litertlm.Engine;
import com.google.ai.edge.litertlm.EngineConfig;
import com.google.ai.edge.litertlm.Message;
import com.google.ai.edge.litertlm.SamplerConfig;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Collections;

/**
 * The AI model that runs on the phone itself (LiteRT-LM). Nothing is installed besides this app:
 * the model file is downloaded once into the app's own storage and loaded only while the app is open.
 * Every method that does real work is called from a worker thread; stopAll() is called when the app goes
 * to the background, so nothing keeps running (or using the battery) after you leave the app.
 */
final class LocalModel {
    /** Default model: Qwen2.5 1.5B Instruct, 8-bit, Apache 2.0, about 1.6 GB, free to download without an account. */
    static final String DEFAULT_FILE = "Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm";
    static final String DEFAULT_URL = "https://huggingface.co/litert-community/Qwen2.5-1.5B-Instruct/resolve/main/" + DEFAULT_FILE;

    interface Progress {
        void on(long done, long total);
    }

    private final Context ctx;
    private final File dir;
    private volatile boolean stop;
    private Engine engine;
    private String enginePath = "";
    private String engineBackend = "";
    private volatile Conversation current;

    LocalModel(Context ctx) {
        this.ctx = ctx;
        this.dir = new File(ctx.getFilesDir(), "models");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
    }

    File dir() {
        return dir;
    }

    File file(String name) {
        String safe = new File(name == null || name.isEmpty() ? DEFAULT_FILE : name).getName();
        return new File(dir, safe);
    }

    /** Stops a download or an answer in progress and frees the model's memory. */
    void stopAll() {
        stop = true;
        Conversation c = current;
        if (c != null) {
            try {
                c.cancelProcess();  // generate() frees the model when the cancelled answer returns
            } catch (Throwable ignored) {
                // already finished
            }
            return;
        }
        synchronized (this) {
            closeEngine();
        }
    }

    void allow() {
        stop = false;
    }

    // ------------------------------------------------------------------ download (only while the app is open)

    /** Downloads url into dest, resuming a partial download. Throws InterruptedIOException("paused") when stopped. */
    void download(String url, File dest, Progress p) throws IOException {
        stop = false;
        File part = new File(dest.getPath() + ".part");
        long have = part.exists() ? part.length() : 0;
        HttpURLConnection c = open(url, have);
        int code = c.getResponseCode();
        if (code == 416 && have > 0) {  // the partial file is already complete
            c.disconnect();
            finish(part, dest);
            return;
        }
        if (code == 200) have = 0;  // the server sent the whole file: start over
        else if (code != 206) throw new IOException("The download server answered " + code + ". Try again later.");
        long len = c.getContentLengthLong();
        long total = len > 0 ? have + len : -1;
        if (total > 0 && dir.getUsableSpace() < (total - have) + 200L * 1024 * 1024) {
            c.disconnect();
            throw new IOException("Not enough free space: the model needs " + (total / (1024 * 1024)) + " MB.");
        }
        try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(part, have > 0)) {
            byte[] buf = new byte[1 << 16];
            long done = have;
            long lastReport = 0;
            int n;
            while ((n = in.read(buf)) > 0) {
                if (stop) throw new InterruptedIOException("paused");
                out.write(buf, 0, n);
                done += n;
                if (done - lastReport > 4L * 1024 * 1024) {
                    lastReport = done;
                    p.on(done, total);
                }
            }
            p.on(done, total);
        } finally {
            c.disconnect();
        }
        if (total > 0 && part.length() != total) throw new IOException("The download stopped early. Tap Download to continue.");
        finish(part, dest);
    }

    private static void finish(File part, File dest) throws IOException {
        if (dest.exists() && !dest.delete()) throw new IOException("Could not replace the old model file");
        if (!part.renameTo(dest)) throw new IOException("Could not save the model file");
    }

    /** Follows redirects by hand so the Range header (resume) reaches the final server. */
    private static HttpURLConnection open(String url, long from) throws IOException {
        String u = url;
        for (int hop = 0; hop < 6; hop++) {
            HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            c.setRequestProperty("User-Agent", "ReelShelf-Android");
            if (from > 0) c.setRequestProperty("Range", "bytes=" + from + "-");
            int code = c.getResponseCode();
            if (code >= 300 && code < 400 && c.getHeaderField("Location") != null) {
                URL next = new URL(new URL(u), c.getHeaderField("Location"));
                c.disconnect();
                if (!"https".equals(next.getProtocol())) throw new IOException("Refused an insecure download address");
                u = next.toString();
                continue;
            }
            return c;
        }
        throw new IOException("Too many redirects");
    }

    // ------------------------------------------------------------------ answers

    /**
     * One answer from the model. gpu=true tries the phone's graphics chip first (faster) and falls back to the CPU.
     * Returns the text; the engine stays loaded for the next reel until stopAll().
     */
    String generate(File model, boolean gpu, String system, String prompt, int maxTokens, double temperature) throws Exception {
        if (!model.isFile()) throw new IOException("The AI model is not downloaded yet (Settings, Download model).");
        stop = false;
        Conversation conv;
        synchronized (this) {
            ensureEngine(model, gpu);
            ConversationConfig cc = new ConversationConfig(
                    system == null || system.isEmpty() ? null : Contents.Companion.of(system),
                    Collections.emptyList(), Collections.emptyList(),
                    new SamplerConfig(40, 0.95, Math.max(0.0, temperature), 0));
            conv = engine.createConversation(cc);
        }
        current = conv;
        try {
            if (stop) throw new InterruptedIOException("stopped");
            Message m = conv.sendMessage(prompt, Collections.emptyMap(), null, null, null,
                    Math.max(64, Math.min(maxTokens, 3000)));
            if (stop) throw new InterruptedIOException("stopped");
            return m.toString();
        } finally {
            current = null;
            try {
                conv.close();
            } catch (Throwable ignored) {
                // freed with the engine
            }
            if (stop) {
                synchronized (this) {
                    closeEngine();
                }
            }
        }
    }

    /** "gpu" or "cpu": what the loaded model actually runs on (GPU can fall back to CPU). */
    synchronized String backendInUse() {
        return engine == null ? "" : engineBackend;
    }

    private void ensureEngine(File model, boolean gpu) throws Exception {
        String want = gpu ? "gpu" : "cpu";
        if (engine != null && enginePath.equals(model.getPath()) && (engineBackend.equals(want) || engineBackend.equals("cpu") && gpu)) return;
        closeEngine();
        String cache = ctx.getCacheDir().getPath();
        if (gpu) {
            try {
                Engine e = new Engine(new EngineConfig(model.getPath(), new Backend.GPU(), null, null, null, null, cache));
                e.initialize();
                engine = e;
                enginePath = model.getPath();
                engineBackend = "gpu";
                return;
            } catch (Throwable t) {
                // this phone's GPU driver cannot run it: use the CPU
            }
        }
        Engine e = new Engine(new EngineConfig(model.getPath(), new Backend.CPU((Integer) null, (Integer) null), null, null, null, null, cache));
        e.initialize();
        engine = e;
        enginePath = model.getPath();
        engineBackend = "cpu";
    }

    private void closeEngine() {
        if (engine != null) {
            try {
                engine.close();
            } catch (Throwable ignored) {
                // nothing left to free
            }
        }
        engine = null;
        enginePath = "";
        engineBackend = "";
    }
}
