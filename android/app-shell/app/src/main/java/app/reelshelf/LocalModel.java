package app.reelshelf;

import android.content.Context;

import com.google.ai.edge.litertlm.Backend;
import com.google.ai.edge.litertlm.Content;
import com.google.ai.edge.litertlm.Contents;
import com.google.ai.edge.litertlm.Conversation;
import com.google.ai.edge.litertlm.ConversationConfig;
import com.google.ai.edge.litertlm.Engine;
import com.google.ai.edge.litertlm.EngineConfig;
import com.google.ai.edge.litertlm.Message;
import com.google.ai.edge.litertlm.SamplerConfig;

import java.io.File;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.util.Collections;

/**
 * The AI model that runs on the phone itself (LiteRT-LM). Nothing is installed besides this app:
 * the model file is downloaded once into the app's own storage and loaded only while the app is open.
 * Every method that does real work is called from a worker thread; stopAll() is called when the app goes
 * to the background, so nothing keeps running (or using the battery) after you leave the app.
 */
final class LocalModel {
    /** Default model: Qwen2.5 1.5B Instruct, 8-bit, Apache 2.0, about 1.6 GB, free to download without an account. */
    static final String DEFAULT_FILE = ModelCatalog.DEFAULT.file;

    private final Context ctx;
    private final File dir;
    private volatile boolean stop;
    /** The check of a model file that is already on the phone (ModelCheck): at most one, and stopAll() stops it. */
    final ModelCheck.Runner checks = new ModelCheck.Runner();
    private Engine engine;
    private String enginePath = "";
    private String engineBackend = "";
    private volatile Conversation current;
    private volatile int lastTokens = -1;

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
        checks.cancel();  // a model check in progress stops before its next read and records nothing
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

    /**
     * Downloads a catalog model into the models folder, resuming a partial download, and installs it only when its size
     * and SHA-256 are the catalog's (see ModelVerifier). Throws InterruptedIOException("paused") when stopped.
     */
    void download(ModelCatalog.Entry e, ModelVerifier.Progress p) throws IOException {
        stop = false;
        File dest = file(e.file);
        new ModelVerifier(() -> stop).download(e, dest, p);
        ModelCheck.recordDownloaded(e, dest);  // it just passed the size and SHA-256 check: no need to read it again
    }

    /** A verifier that stops when stopAll() is called: the speech model's ZIP is fetched through it, then unpacked (see ModelZip.fetch). */
    ModelVerifier verifier() {
        stop = false;
        return new ModelVerifier(() -> stop);
    }

    // ------------------------------------------------------------------ answers

    /**
     * One answer from the model. gpu=true tries the phone's graphics chip first (faster) and falls back to the CPU.
     * Returns the text; the engine stays loaded for the next reel until stopAll().
     */
    String generate(File model, boolean gpu, String system, String prompt, int maxTokens, double temperature) throws Exception {
        return generate(model, gpu, system, prompt, maxTokens, temperature, null, null);
    }

    /** Models that can look at pictures and listen to sound (Gemma 4 E2B/E4B, Gemma 3n). */
    static boolean multimodal(File model) {
        String n = model.getName().toLowerCase(java.util.Locale.ROOT);
        return n.startsWith("gemma-4-e") || n.startsWith("gemma-3n");
    }

    /**
     * One answer; with a multimodal model, key frames (JPEG files) and a sound clip (WAV file) of the reel are given
     * too, so the model sees and hears it. Other models get the text only.
     */
    String generate(File model, boolean gpu, String system, String prompt, int maxTokens, double temperature,
                    java.util.List<File> frames, File sound) throws Exception {
        if (!model.isFile()) throw new IOException("The AI model is not downloaded yet (Settings, Download model).");
        stop = false;
        lastTokens = -1;
        Conversation conv;
        synchronized (this) {
            ensureEngine(model, gpu, multimodal(model) && ((frames != null && !frames.isEmpty()) || sound != null));
            ConversationConfig cc = new ConversationConfig(
                    system == null || system.isEmpty() ? null : Contents.Companion.of(system),
                    Collections.emptyList(), Collections.emptyList(),
                    new SamplerConfig(40, 0.95, Math.max(0.0, temperature), 0));
            conv = engine.createConversation(cc);
        }
        current = conv;
        try {
            if (stop) throw new InterruptedIOException("stopped");
            Message m;
            if (engineMulti && ((frames != null && !frames.isEmpty()) || sound != null)) {
                java.util.List<Content> parts = new java.util.ArrayList<>();
                if (frames != null) for (File f : frames) parts.add(new Content.ImageFile(f.getPath()));
                if (sound != null) parts.add(new Content.AudioFile(sound.getPath()));
                parts.add(new Content.Text(prompt));
                m = conv.sendMessage(Contents.Companion.of(parts.toArray(new Content[0])), Collections.emptyMap(), null, null, null,
                        Math.max(64, Math.min(maxTokens, 3000)));
            } else {
                m = conv.sendMessage(prompt, Collections.emptyMap(), null, null, null,
                        Math.max(64, Math.min(maxTokens, 3000)));
            }
            try {
                lastTokens = conv.getTokenCount();  // what the engine counted, to compare with the page's estimate; not checked on a phone yet
            } catch (Throwable t) {
                lastTokens = -1;
            }
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

    /** The token count the engine reported after the last answer, or -1 when it did not say. */
    int lastTokens() {
        return lastTokens;
    }

    /** "gpu" or "cpu": what the loaded model actually runs on (GPU can fall back to CPU). */
    synchronized String backendInUse() {
        return engine == null ? "" : engineBackend;
    }

    private boolean engineMulti;

    private void ensureEngine(File model, boolean gpu, boolean multi) throws Exception {
        String want = gpu ? "gpu" : "cpu";
        if (engine != null && enginePath.equals(model.getPath()) && (engineBackend.equals(want) || engineBackend.equals("cpu") && gpu)
                && (engineMulti || !multi)) return;
        closeEngine();
        String cache = ctx.getCacheDir().getPath();
        if (multi) {  // sight and sound on the CPU (works on every phone), the text part on the GPU when it can
            try {
                Engine e = new Engine(new EngineConfig(model.getPath(), gpu ? new Backend.GPU() : new Backend.CPU((Integer) null, (Integer) null),
                        new Backend.CPU((Integer) null, (Integer) null), new Backend.CPU((Integer) null, (Integer) null), null, 4, cache));
                e.initialize();
                engine = e;
                enginePath = model.getPath();
                engineBackend = want;
                engineMulti = true;
                return;
            } catch (Throwable t) {
                if (gpu) {
                    try {
                        Engine e = new Engine(new EngineConfig(model.getPath(), new Backend.CPU((Integer) null, (Integer) null),
                                new Backend.CPU((Integer) null, (Integer) null), new Backend.CPU((Integer) null, (Integer) null), null, 4, cache));
                        e.initialize();
                        engine = e;
                        enginePath = model.getPath();
                        engineBackend = "cpu";
                        engineMulti = true;
                        return;
                    } catch (Throwable ignored) {
                        // fall back to text only below
                    }
                }
            }
        }
        engineMulti = false;
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
        engineMulti = false;
        enginePath = "";
        engineBackend = "";
    }
}
