package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;
import static org.junit.Assume.assumeTrue;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * A model download is installed only when it is exactly the catalog's file. A small local HTTP server plays Hugging Face
 * (the verifier is told to connect there; the addresses are still checked as the real service's would be). It is written
 * on plain sockets because the Android unit-test build does not see the JDK's com.sun.net.httpserver.
 */
public class ModelVerifierTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static final String COMMIT = "0123456789abcdef0123456789abcdef01234567";
    private static final int SIZE = 5 * 65536 + 12345;  // several read buffers, and a last one that is not full

    private File models;
    private File dest;
    private File part;
    private byte[] good;
    private ModelCatalog.Entry entry;
    private final List<Server> servers = new ArrayList<>();

    @Before
    public void setUp() throws Exception {
        models = tmp.newFolder("models");
        dest = new File(models, "tiny.litertlm");
        part = new File(models, "tiny.litertlm.part");
        good = data(SIZE, 1);
        entry = entryFor(good);
    }

    @After
    public void stopServers() {
        for (Server s : servers) s.close();
    }

    // ------------------------------------------------------------------ helpers

    private static byte[] data(int n, int seed) {
        byte[] b = new byte[n];
        new Random(seed).nextBytes(b);
        return b;
    }

    private static String sha(byte[] b) throws Exception {
        return ModelVerifier.hex(MessageDigest.getInstance("SHA-256").digest(b));
    }

    private static ModelCatalog.Entry entryFor(byte[] bytes) throws Exception {
        return new ModelCatalog.Entry("t", "tiny.litertlm", "https://huggingface.co/test/resolve/" + COMMIT + "/tiny.litertlm", bytes.length, sha(bytes));
    }

    /** One request and its answer, on one connection that is closed after the answer. */
    private static final class Exchange {
        final String target;
        final Map<String, String> headers;
        private final OutputStream out;

        Exchange(String target, Map<String, String> headers, OutputStream out) {
            this.target = target;
            this.headers = headers;
            this.out = out;
        }

        String header(String name) {
            return headers.get(name.toLowerCase());
        }

        String path() {
            int q = target.indexOf('?');
            return q < 0 ? target : target.substring(0, q);
        }

        private void head(int code, String... more) throws IOException {
            StringBuilder h = new StringBuilder("HTTP/1.1 " + code + " Status\r\nConnection: close\r\n");
            for (int i = 0; i < more.length; i += 2) h.append(more[i]).append(": ").append(more[i + 1]).append("\r\n");
            out.write((h + "\r\n").getBytes(StandardCharsets.ISO_8859_1));
        }

        /** An answer with a Content-Length. */
        void send(int code, byte[] body, String... headers) throws IOException {
            String[] all = Arrays.copyOf(headers, headers.length + 2);
            all[headers.length] = "Content-Length";
            all[headers.length + 1] = String.valueOf(body.length);
            head(code, all);
            out.write(body);
            out.flush();
        }

        /** An answer without a Content-Length (chunked): the first count bytes of body, then a clean end. */
        void sendChunked(byte[] body, int count) throws IOException {
            head(200, "Transfer-Encoding", "chunked");
            int n = Math.min(count, body.length);
            for (int at = 0; at < n; at += 8192) {
                int len = Math.min(8192, n - at);
                out.write((Integer.toHexString(len) + "\r\n").getBytes(StandardCharsets.ISO_8859_1));
                out.write(body, at, len);
                out.write("\r\n".getBytes(StandardCharsets.ISO_8859_1));
            }
            out.write("0\r\n\r\n".getBytes(StandardCharsets.ISO_8859_1));
            out.flush();
        }

        /** Promises all of body (Content-Length) but hangs up after count bytes. */
        void sendCut(byte[] body, int count) throws IOException {
            head(200, "Content-Length", String.valueOf(body.length));
            out.write(body, 0, count);
            out.flush();
        }
    }

    private interface Handler {
        void handle(Exchange x) throws IOException;
    }

    /** The server's reply. */
    private static void reply(Exchange x, int code, byte[] body, String... headers) throws IOException {
        x.send(code, body, headers);
    }

    /** Whole file with a Content-Length. */
    private static void whole(Exchange x, byte[] body) throws IOException {
        x.send(200, body);
    }

    /** Whole file without a Content-Length (chunked). */
    private static void chunked(Exchange x, byte[] body, int sendOnly) throws IOException {
        x.sendChunked(body, sendOnly);
    }

    /** What a real file server does: the whole file, or the rest of it when asked with "Range: bytes=N-". */
    private static void ranged(Exchange x, byte[] body) throws IOException {
        String r = x.header("Range");
        if (r == null) {
            whole(x, body);
            return;
        }
        int from = Integer.parseInt(r.substring("bytes=".length(), r.length() - 1));
        reply(x, 206, Arrays.copyOfRange(body, from, body.length), "Content-Range", "bytes " + from + "-" + (body.length - 1) + "/" + body.length);
    }

    private static final class Server {
        final ServerSocket socket;
        final String base;
        final AtomicInteger requests = new AtomicInteger();
        final List<String> ranges = Collections.synchronizedList(new ArrayList<>());
        final List<String> paths = Collections.synchronizedList(new ArrayList<>());
        volatile String userAgent;

        Server(Handler h) throws IOException {
            socket = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"));
            base = "http://127.0.0.1:" + socket.getLocalPort();
            Thread t = new Thread(() -> {
                while (!socket.isClosed()) {
                    try {
                        Socket c = socket.accept();
                        new Thread(() -> answer(c, h)).start();
                    } catch (IOException e) {
                        return;  // closed
                    }
                }
            });
            t.setDaemon(true);
            t.start();
        }

        private void answer(Socket c, Handler h) {
            try (Socket s = c) {
                BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.ISO_8859_1));
                String line = in.readLine();
                if (line == null) return;
                Map<String, String> headers = new HashMap<>();
                for (String l = in.readLine(); l != null && !l.isEmpty(); l = in.readLine()) {
                    int colon = l.indexOf(':');
                    if (colon > 0) headers.put(l.substring(0, colon).trim().toLowerCase(), l.substring(colon + 1).trim());
                }
                Exchange x = new Exchange(line.split(" ")[1], headers, s.getOutputStream());
                requests.incrementAndGet();
                ranges.add(x.header("Range"));
                paths.add(x.target);
                userAgent = x.header("User-Agent");
                h.handle(x);
            } catch (IOException ignored) {
                // the client hung up (a paused or refused download)
            }
        }

        void close() {
            try {
                socket.close();
            } catch (IOException ignored) {
                // gone
            }
        }
    }

    private Server serve(Handler h) throws IOException {
        Server s = new Server(h);
        servers.add(s);
        return s;
    }

    private static final class Ctl implements ModelVerifier.Control {
        volatile int stopAfterChecks = Integer.MAX_VALUE;
        volatile long free = Long.MAX_VALUE / 2;
        final AtomicInteger checks = new AtomicInteger();

        @Override
        public boolean stopped() {
            return checks.incrementAndGet() > stopAfterChecks;
        }

        @Override
        public long freeSpace(File dir) {
            return free;
        }
    }

    private final List<long[]> progress = new ArrayList<>();

    private void download(Server s, ModelCatalog.Entry e, Ctl ctl) throws IOException {
        new ModelVerifier(ctl, s.base).download(e, dest, (d, t) -> progress.add(new long[]{d, t}));
    }

    private void download(Server s) throws IOException {
        download(s, entry, new Ctl());
    }

    private static byte[] read(File f) throws IOException {
        return Files.readAllBytes(f.toPath());
    }

    private static void write(File f, byte[] b) throws IOException {
        Files.write(f.toPath(), b);
    }

    private static byte[] prefix(byte[] b, int n) {
        return Arrays.copyOf(b, n);
    }

    private void assertNothingInstalled() {
        assertFalse("no final file", dest.exists());
    }

    // ------------------------------------------------------------------ a download that is right

    @Test
    public void aGoodFileIsInstalledAndTheUserAgentIsOurs() throws Exception {
        Server s = serve(x -> whole(x, good));
        download(s);
        assertArrayEquals(good, read(dest));
        assertFalse("the part is gone", part.exists());
        assertEquals(Arrays.asList(new String[]{null}), s.ranges);
        assertEquals("ReelShelf-Android", s.userAgent);
        long[] last = progress.get(progress.size() - 1);
        assertEquals(good.length, last[0]);
        for (long[] p : progress) assertEquals("the total is the catalog size", good.length, p[1]);
    }

    @Test
    public void aGoodFileReplacesAnOlderOneInOneStep() throws Exception {
        // The limit of this test: it sees the result, so it cannot tell an atomic replace from delete-then-rename.
        write(dest, "older model".getBytes(StandardCharsets.UTF_8));
        Server s = serve(x -> whole(x, good));
        download(s);
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void aGoodFileWithoutContentLengthIsInstalledToo() throws Exception {
        Server s = serve(x -> chunked(x, good, good.length));
        download(s);
        assertArrayEquals(good, read(dest));
    }

    // ------------------------------------------------------------------ a download that is wrong

    @Test
    public void oneFlippedByteIsRefused_theOwnPartIsDeleted_andTheInstalledModelIsNotTouched() throws Exception {
        byte[] bad = good.clone();
        bad[bad.length / 2] ^= 1;
        byte[] installed = "the model that is already installed".getBytes(StandardCharsets.UTF_8);
        write(dest, installed);
        Server s = serve(x -> whole(x, bad));
        IOException e = assertThrows(IOException.class, () -> download(s));
        assertEquals(ModelVerifier.DAMAGED, e.getMessage());
        assertFalse("our own part is deleted", part.exists());
        assertArrayEquals("the installed model is untouched", installed, read(dest));
    }

    @Test
    public void aFlippedByteWithoutContentLengthIsRefusedToo() throws Exception {
        byte[] bad = good.clone();
        bad[7] ^= 0x40;
        Server s = serve(x -> chunked(x, bad, bad.length));
        assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse(part.exists());
        assertNothingInstalled();
    }

    @Test
    public void aFileOfTheRightSizeButAnotherFileIsRefused() throws Exception {
        Server s = serve(x -> whole(x, data(SIZE, 99)));
        assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse(part.exists());
        assertNothingInstalled();
    }

    @Test
    public void aTruncatedDownloadKeepsThePartAndInstallsNothing_withAndWithoutContentLength() throws Exception {
        int half = good.length / 2;
        Server noLength = serve(x -> chunked(x, good, half));  // a clean end of the stream, far too early
        IOException e = assertThrows(IOException.class, () -> download(noLength));
        assertEquals(ModelVerifier.STOPPED_EARLY, e.getMessage());
        assertEquals(half, part.length());
        assertNothingInstalled();

        assertTrue(part.delete());
        Server cut = serve(x -> x.sendCut(good, half));  // promises everything, hangs up half way
        assertThrows(IOException.class, () -> download(cut));
        assertTrue("the piece that arrived is kept", part.exists() && part.length() <= half);
        assertNothingInstalled();
    }

    @Test
    public void aTruncatedDownloadContinuesAndInstalls() throws Exception {
        int half = good.length / 2;
        Server cut = serve(x -> chunked(x, good, half));
        assertThrows(IOException.class, () -> download(cut));
        Server full = serve(x -> ranged(x, good));
        download(full);
        assertEquals(Arrays.asList("bytes=" + half + "-"), full.ranges);
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void moreBytesThanTheCatalogSaysAreStoppedAndNothingIsInstalled() throws Exception {
        byte[] longer = Arrays.copyOf(good, good.length + 1000);
        Server s = serve(x -> chunked(x, longer, longer.length));
        assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse("nothing past the catalog size is kept", part.exists());
        assertNothingInstalled();
    }

    @Test
    public void aWrongContentLengthIsRefusedBeforeAnythingIsWritten() throws Exception {
        byte[] longer = Arrays.copyOf(good, good.length + 1000);
        Server s = serve(x -> whole(x, longer));
        assertEquals(ModelVerifier.WRONG_SIZE, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse("nothing was written", part.exists());
        assertNothingInstalled();
    }

    @Test
    public void anHtmlPageWithStatus200IsRefusedBeforeAnythingIsWritten() throws Exception {
        byte[] html = "<html><body>Sign in to the Wi-Fi</body></html>".getBytes(StandardCharsets.UTF_8);
        Server s = serve(x -> reply(x, 200, html, "Content-Type", "text/html"));
        assertEquals(ModelVerifier.WRONG_SIZE, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse(part.exists());
        assertNothingInstalled();

        byte[] kept = prefix(good, 1000);  // a part from before is not touched either
        write(part, kept);
        assertThrows(IOException.class, () -> download(s));
        assertArrayEquals(kept, read(part));
    }

    @Test
    public void anAnswerThatIsNotAFileIsRefused() throws Exception {
        Server s = serve(x -> reply(x, 404, new byte[0]));
        IOException e = assertThrows(IOException.class, () -> download(s));
        assertTrue(e.getMessage(), e.getMessage().contains("404"));
        assertFalse(part.exists());
    }

    // ------------------------------------------------------------------ where the bytes may come from

    @Test
    public void aRedirectToAnotherHostIsRefusedAndNothingIsRequestedThere() throws Exception {
        for (String to : new String[]{"https://evil.example.com/x", "https://huggingface.co@evil.example.com/x", "https://evilhuggingface.co/x",
                "https://huggingface.co.evil.example.com/x", "https://hf.co/x"}) {
            Server s = serve(x -> reply(x, 302, new byte[0], "Location", to));
            IOException e = assertThrows(IOException.class, () -> download(s));
            assertTrue(to + " -> " + e.getMessage(), e.getMessage().contains("another site"));
            assertEquals(to + ": only the first address was asked", 1, s.requests.get());
            assertFalse(part.exists());
            assertNothingInstalled();
        }
    }

    @Test
    public void aRedirectWithUserInfoIsRefused() throws Exception {
        // "user@" in front of an allowed host: another URL parser may read the other side of the "@" as the host
        for (String to : new String[]{"https://user:secret@huggingface.co/x", "https://huggingface.co@huggingface.co/x"}) {
            Server s = serve(x -> reply(x, 302, new byte[0], "Location", to));
            assertEquals(to, ModelVerifier.ODD_ADDRESS, assertThrows(IOException.class, () -> download(s)).getMessage());
            assertEquals(to + ": only the first address was asked", 1, s.requests.get());
            assertFalse(part.exists());
            assertNothingInstalled();
        }
    }

    @Test
    public void aRedirectWithABackslashIsRefused() throws Exception {
        for (String to : new String[]{"https://huggingface.co/x\\y", "https://evil.example.com\\@huggingface.co/x", "https://huggingface.co\\@evil.example.com/x"}) {
            Server s = serve(x -> reply(x, 302, new byte[0], "Location", to));
            assertEquals(to, ModelVerifier.ODD_ADDRESS, assertThrows(IOException.class, () -> download(s)).getMessage());
            assertEquals(to + ": only the first address was asked", 1, s.requests.get());
            assertFalse(part.exists());
            assertNothingInstalled();
        }
    }

    @Test
    public void aRedirectToHttpIsRefused() throws Exception {
        Server s = serve(x -> reply(x, 302, new byte[0], "Location", "http://huggingface.co/x"));
        assertEquals("Refused an insecure download address", assertThrows(IOException.class, () -> download(s)).getMessage());
        assertEquals(1, s.requests.get());
        assertFalse(part.exists());
    }

    @Test
    public void aRedirectToHuggingFaceHostsIsFollowed_andTheRangeReachesTheLastServer() throws Exception {
        write(part, prefix(good, 70000));
        Server s = serve(x -> {
            if (x.path().startsWith("/xet-bridge-us/")) ranged(x, good);
            else if (x.path().startsWith("/step")) reply(x, 302, new byte[0], "Location", "https://us.aws.cdn.hf.co/xet-bridge-us/abc?sig=1");
            else reply(x, 307, new byte[0], "Location", "https://cdn-lfs.huggingface.co/step");
        });
        download(s);
        assertArrayEquals(good, read(dest));
        assertEquals(3, s.requests.get());
        assertEquals(Arrays.asList("bytes=70000-", "bytes=70000-", "bytes=70000-"), s.ranges);
        assertEquals("/xet-bridge-us/abc?sig=1", s.paths.get(2));
    }

    @Test
    public void aRelativeRedirectStaysOnTheSameAllowedHost() throws Exception {
        Server s = serve(x -> {
            if (x.path().equals("/next")) whole(x, good);
            else reply(x, 302, new byte[0], "Location", "/next");
        });
        download(s);
        assertArrayEquals(good, read(dest));
    }

    @Test
    public void tooManyRedirectsAreRefused() throws Exception {
        Server s = serve(x -> reply(x, 302, new byte[0], "Location", "https://huggingface.co/again"));
        assertEquals("Too many redirects", assertThrows(IOException.class, () -> download(s)).getMessage());
        assertEquals(6, s.requests.get());
    }

    @Test
    public void onlyHuggingFaceHostsAreAllowed() {
        for (String ok : new String[]{"huggingface.co", "HuggingFace.co", "cdn-lfs.huggingface.co", "a.b.huggingface.co", "us.aws.cdn.hf.co", "cas-bridge.xethub.hf.co"})
            assertTrue(ok, ModelVerifier.allowedHost(ok));
        for (String no : new String[]{null, "", "hf.co", "huggingface.com", "evilhuggingface.co", "huggingface.co.evil.com", "hf.co.evil.com", "evilhf.co",
                "example.com", "localhost", "127.0.0.1", "alphacephei.com", "xhuggingface.co", ".huggingface.co.example.org"})
            assertFalse(String.valueOf(no), ModelVerifier.allowedHost(no));
    }

    @Test
    public void anAddressOutsideTheAllowedHostsIsNeverRequested() throws Exception {
        ModelCatalog.Entry other = new ModelCatalog.Entry("t", "tiny.litertlm", "https://example.com/resolve/" + COMMIT + "/tiny.litertlm", good.length, sha(good));
        Server s = serve(x -> whole(x, good));
        IOException e = assertThrows(IOException.class, () -> download(s, other, new Ctl()));
        assertTrue(e.getMessage(), e.getMessage().contains("example.com"));
        assertEquals(0, s.requests.get());
        ModelCatalog.Entry plain = new ModelCatalog.Entry("t", "tiny.litertlm", "http://huggingface.co/resolve/" + COMMIT + "/tiny.litertlm", good.length, sha(good));
        assertThrows(IOException.class, () -> download(s, plain, new Ctl()));
        assertEquals(0, s.requests.get());
    }

    // ------------------------------------------------------------------ continuing a paused download

    @Test
    public void aPartIsContinuedWith206AndHashedFromItsFirstByte() throws Exception {
        int k = 100000;
        write(part, prefix(good, k));
        Server s = serve(x -> ranged(x, good));
        download(s);
        assertEquals(Arrays.asList("bytes=" + k + "-"), s.ranges);
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
        assertEquals("the bar starts where the part was", k, progress.get(0)[0]);
    }

    @Test
    public void aPartThatIsNotAPieceOfTheModelIsCaughtByTheHash() throws Exception {
        byte[] wrongStart = data(100000, 5);
        write(part, wrongStart);
        Server s = serve(x -> ranged(x, good));
        assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertFalse("our part is deleted, so the next try starts clean", part.exists());
        assertNothingInstalled();
    }

    @Test
    public void whenTheServerAnswers200ToARangeTheDownloadRestartsFromZero() throws Exception {
        write(part, prefix(data(150000, 8), 150000));  // would corrupt the file if it were kept
        Server s = serve(x -> whole(x, good));
        download(s);
        assertEquals(Arrays.asList("bytes=150000-"), s.ranges);
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void a206ThatDoesNotDescribeTheModelIsRefusedAndThePartIsKept() throws Exception {
        int k = 90000;
        byte[] kept = prefix(good, k);
        byte[] rest = Arrays.copyOfRange(good, k, good.length);
        String[][] answers = {
                {"bytes " + k + "-" + (good.length - 1) + "/" + (good.length + 7)},  // a file of another size
                {"bytes " + k + "-" + (good.length - 1) + "/*"},  // size not said
                {"bytes " + (k + 1) + "-" + (good.length - 1) + "/" + good.length},  // from another place than asked
                {"bytes " + k + "-" + (good.length - 5) + "/" + good.length},  // not to the end
        };
        for (String[] a : answers) {
            write(part, kept);
            Server s = serve(x -> reply(x, 206, rest, "Content-Range", a[0]));
            assertThrows(a[0], IOException.class, () -> download(s));
            assertArrayEquals(a[0], kept, read(part));
            assertNothingInstalled();
        }
        write(part, kept);
        Server none = serve(x -> reply(x, 206, rest));  // no Content-Range at all
        assertThrows(IOException.class, () -> download(none));
        assertArrayEquals(kept, read(part));
    }

    @Test
    public void aContentRangeWithHugeNumbersIsRefusedAsAnOddAnswer_notACrash() throws Exception {
        int k = 90000;
        byte[] kept = prefix(good, k);
        byte[] rest = Arrays.copyOfRange(good, k, good.length);
        String twenty = "99999999999999999999", nineteen = "9999999999999999999";  // too big for a long
        for (String range : new String[]{"bytes " + k + "-" + twenty + "/" + twenty, "bytes " + k + "-" + nineteen + "/" + nineteen, "bytes " + twenty + "-" + twenty + "/" + twenty}) {
            write(part, kept);
            Server s = serve(x -> reply(x, 206, rest, "Content-Range", range));
            assertEquals(range, ModelVerifier.ODD_ANSWER, assertThrows(range, IOException.class, () -> download(s)).getMessage());
            assertArrayEquals("the part is kept", kept, read(part));
            assertNothingInstalled();
        }
    }

    @Test
    public void aChunked200ToARangeIsRefusedAndThePartIsNotCutDown() throws Exception {
        byte[] kept = prefix(good, 80000);
        write(part, kept);
        Server s = serve(x -> chunked(x, good, good.length));  // ignores the Range and does not say how long it is
        assertEquals(ModelVerifier.ODD_ANSWER, assertThrows(IOException.class, () -> download(s)).getMessage());
        assertArrayEquals("the part was not truncated for an answer of unknown size", kept, read(part));
        assertNothingInstalled();
    }

    @Test
    public void a416ForAWrongCompletePartDeletesItAndStartsAgain() throws Exception {
        write(part, data(SIZE, 77));  // as long as the model, but not the model
        Server s = serve(x -> {
            if (x.header("Range") != null) reply(x, 416, new byte[0], "Content-Range", "bytes */" + good.length);
            else whole(x, good);
        });
        download(s);
        assertEquals(Arrays.asList("bytes=" + SIZE + "-", null), s.ranges);
        assertArrayEquals("the wrong part was not installed", good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void a416ForACompleteAndCorrectPartInstallsItWithoutDownloadingAgain() throws Exception {
        write(part, good);
        Server s = serve(x -> reply(x, 416, new byte[0], "Content-Range", "bytes */" + good.length));
        download(s);
        assertEquals(1, s.requests.get());
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void a416ForAShorterPartDeletesItAndStartsAgain() throws Exception {
        write(part, prefix(good, 50000));
        Server s = serve(x -> {
            if (x.header("Range") != null) reply(x, 416, new byte[0]);
            else whole(x, good);
        });
        download(s);
        assertEquals(Arrays.asList("bytes=50000-", null), s.ranges);
        assertArrayEquals(good, read(dest));
    }

    @Test
    public void a416ToAFreshDownloadIsJustAnError() throws Exception {
        Server s = serve(x -> reply(x, 416, new byte[0]));
        assertTrue(assertThrows(IOException.class, () -> download(s)).getMessage().contains("416"));
        assertEquals("no endless restarts", 1, s.requests.get());
        assertNothingInstalled();
    }

    @Test
    public void aPartLongerThanTheCatalogIsDeletedAndTheDownloadRestarts() throws Exception {
        write(part, Arrays.copyOf(good, good.length + 5000));
        Server s = serve(x -> ranged(x, good));
        download(s);
        assertEquals("a fresh download, no Range", Arrays.asList(new String[]{null}), s.ranges);
        assertArrayEquals(good, read(dest));
        assertFalse(part.exists());
    }

    @Test
    public void pausingKeepsThePartAndLaterContinuesToAnInstalledModel() throws Exception {
        Server s = serve(x -> whole(x, good));
        Ctl pause = new Ctl();
        pause.stopAfterChecks = 2;
        assertThrows(InterruptedIOException.class, () -> download(s, entry, pause));
        long kept = part.length();
        assertTrue("some bytes were kept: " + kept, kept > 0 && kept < good.length);
        assertArrayEquals(prefix(good, (int) kept), read(part));
        assertNothingInstalled();

        Server again = serve(x -> ranged(x, good));
        download(again);
        assertEquals(Arrays.asList("bytes=" + kept + "-"), again.ranges);
        assertArrayEquals(good, read(dest));
    }

    @Test
    public void thePartIsReadAgainOnlyWhileNotStopped() throws Exception {
        write(part, prefix(good, 200000));
        Server s = serve(x -> ranged(x, good));
        Ctl stopped = new Ctl();
        stopped.stopAfterChecks = 0;
        assertThrows(InterruptedIOException.class, () -> download(s, entry, stopped));
        assertEquals("nothing was asked of the server", 0, s.requests.get());
        assertEquals(200000, part.length());
    }

    // ------------------------------------------------------------------ room on the phone

    @Test
    public void roomIsCheckedAgainstTheCatalogSize_beforeAnyRequest_withoutAContentLength() throws Exception {
        Server s = serve(x -> chunked(x, good, good.length));  // says nothing about its size
        Ctl tight = new Ctl();
        tight.free = ModelVerifier.RESERVE + good.length - 1;
        IOException e = assertThrows(IOException.class, () -> download(s, entry, tight));
        assertTrue(e.getMessage(), e.getMessage().startsWith("Not enough free space: the model needs "));
        assertEquals(0, s.requests.get());
        assertFalse(part.exists());

        tight.free = ModelVerifier.RESERVE + good.length;
        download(s, entry, tight);
        assertArrayEquals(good, read(dest));
    }

    @Test
    public void roomForAContinuedDownloadIsWhatIsLeftToFetch() throws Exception {
        int k = 120000;
        write(part, prefix(good, k));
        Server s = serve(x -> ranged(x, good));
        Ctl tight = new Ctl();
        tight.free = ModelVerifier.RESERVE + (good.length - k) - 1;
        assertThrows(IOException.class, () -> download(s, entry, tight));
        assertEquals(0, s.requests.get());
        tight.free = ModelVerifier.RESERVE + (good.length - k);
        download(s, entry, tight);
        assertArrayEquals(good, read(dest));
    }

    @Test
    public void aFullPhoneKeepsThePartAndSaysSo() throws Exception {
        assumeTrue("needs /dev/full (Linux)", new File("/dev/full").exists());
        Files.createSymbolicLink(part.toPath(), Paths.get("/dev/full"));
        Server s = serve(x -> whole(x, good));
        IOException e = assertThrows(IOException.class, () -> download(s));
        assertTrue(e.getMessage(), e.getMessage().startsWith("Phone storage is full"));
        assertTrue("the part stays", Files.isSymbolicLink(part.toPath()));
        assertNothingInstalled();
    }

    // ------------------------------------------------------------------ the speech model: a ZIP from one host, checked before it is unpacked

    private static void put(File f, byte[] b) throws IOException {
        Files.createDirectories(f.getParentFile().toPath());
        Files.write(f.toPath(), b);
    }

    private static final ModelZip.Plan SPEECH_PLAN = new ModelZip.Plan("m", 10, 100_000, "am", "conf");

    /** A small model ZIP: the folder m with am/ and conf/. Its comment makes two ZIPs differ without changing what they unpack to. */
    private static byte[] smallZip(String comment, String... extraNames) throws Exception {
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        try (java.util.zip.ZipOutputStream z = new java.util.zip.ZipOutputStream(bytes)) {
            z.setComment(comment);
            List<String> names = new ArrayList<>(Arrays.asList("m/am/final.mdl", "m/conf/model.conf"));
            names.addAll(Arrays.asList(extraNames));
            for (String n : names) {
                z.putNextEntry(new java.util.zip.ZipEntry(n));
                z.write(("content of " + n).getBytes(StandardCharsets.UTF_8));
                z.closeEntry();
            }
        }
        return bytes.toByteArray();
    }

    private static String md5(byte[] b) throws Exception {
        return ModelVerifier.hex(MessageDigest.getInstance("MD5").digest(b));
    }

    /** A row like the speech model's: one host, no redirect, SHA-256 and MD5 of this ZIP. */
    private static ModelCatalog.Entry speechRow(byte[] zip) throws Exception {
        return ModelCatalog.Entry.fromOneHost("speech-test", "tiny.zip", "https://alphacephei.com/vosk/models/tiny.zip", zip.length, sha(zip), md5(zip), "alphacephei.com");
    }

    private File speechZip() {
        return new File(models, "tiny.zip");
    }

    private File speechZipPart() {
        return new File(models, "tiny.zip.part");
    }

    private File speechRoot() throws IOException {
        return new File(tmp.getRoot(), "speech");
    }

    /** The model that is already installed. */
    private void installedSpeechModel() throws IOException {
        put(new File(speechRoot(), "m/am/old.bin"), "OLD MODEL".getBytes(StandardCharsets.UTF_8));
        put(new File(speechRoot(), "m/conf/old.conf"), "old conf".getBytes(StandardCharsets.UTF_8));
    }

    private void assertOldSpeechModelKept() throws IOException {
        assertEquals("OLD MODEL", new String(read(new File(speechRoot(), "m/am/old.bin")), StandardCharsets.UTF_8));
        assertEquals("old conf", new String(read(new File(speechRoot(), "m/conf/old.conf")), StandardCharsets.UTF_8));
        assertFalse("nothing of the new ZIP was unpacked", new File(speechRoot(), "m/am/final.mdl").exists());
        assertEquals("no .unpack-* or .old-* is left", Arrays.asList("m"), Arrays.asList(speechRoot().list()));
    }

    private void fetchSpeech(Server s, ModelCatalog.Entry e, Ctl ctl) throws IOException {
        ModelZip.fetch(new ModelVerifier(ctl, s.base), e, speechZip(), speechRoot(), SPEECH_PLAN, (d, t) -> progress.add(new long[]{d, t}));
    }

    private void fetchSpeech(Server s, ModelCatalog.Entry e) throws IOException {
        fetchSpeech(s, e, new Ctl());
    }

    @Test
    public void aSpeechZipIsCheckedThenUnpackedAndTheZipIsGone() throws Exception {
        byte[] zip = smallZip("published");
        Server s = serve(x -> whole(x, zip));
        installedSpeechModel();
        fetchSpeech(s, speechRow(zip));
        assertEquals("content of m/am/final.mdl", new String(read(new File(speechRoot(), "m/am/final.mdl")), StandardCharsets.UTF_8));
        assertFalse("the old model is replaced, not mixed", new File(speechRoot(), "m/am/old.bin").exists());
        assertFalse(speechZip().exists());
        assertFalse(speechZipPart().exists());
        assertEquals(Arrays.asList("m"), Arrays.asList(speechRoot().list()));
        assertEquals("ReelShelf-Android", s.userAgent);
        for (long[] p : progress) assertEquals("the total is the catalog size", zip.length, p[1]);
    }

    @Test
    public void aSpeechZipWithOneChangedByteIsNeverUnpacked_theOldModelStays_thePartIsDeleted() throws Exception {
        byte[] zip = smallZip("published");
        byte[] bad = zip.clone();
        bad[bad.length - 2] ^= 1;  // inside the ZIP's comment: it would unpack just the same, so only the fingerprint can stop it
        Server s = serve(x -> whole(x, bad));
        installedSpeechModel();
        IOException e = assertThrows(IOException.class, () -> fetchSpeech(s, speechRow(zip)));
        assertEquals(ModelVerifier.DAMAGED, e.getMessage());
        assertFalse("our own part is deleted", speechZipPart().exists());
        assertFalse(speechZip().exists());
        assertOldSpeechModelKept();
    }

    @Test
    public void aSpeechZipThatFailsTheMd5IsRefusedEvenWhenTheSha256Matches_andTheOtherWayRound() throws Exception {
        byte[] zip = smallZip("published");
        ModelCatalog.Entry real = speechRow(zip);
        ModelCatalog.Entry wrongMd5 = ModelCatalog.Entry.fromOneHost(real.id, real.file, real.url, real.bytes, real.sha256, md5(smallZip("another")), real.onlyHost);
        ModelCatalog.Entry wrongSha = ModelCatalog.Entry.fromOneHost(real.id, real.file, real.url, real.bytes, sha(smallZip("another")), real.md5, real.onlyHost);
        for (ModelCatalog.Entry row : new ModelCatalog.Entry[]{wrongMd5, wrongSha}) {
            Server s = serve(x -> whole(x, zip));
            installedSpeechModel();
            assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> fetchSpeech(s, row)).getMessage());
            assertFalse(speechZipPart().exists());
            assertOldSpeechModelKept();
        }
    }

    @Test
    public void theMd5IsAlsoCheckedWhenADownloadContinuesAndWhenTheServerSendsNoLength() throws Exception {
        byte[] zip = smallZip("published");
        ModelCatalog.Entry real = speechRow(zip);
        ModelCatalog.Entry wrongMd5 = ModelCatalog.Entry.fromOneHost(real.id, real.file, real.url, real.bytes, real.sha256, md5(smallZip("another")), real.onlyHost);
        int k = zip.length / 2;
        write(speechZipPart(), prefix(zip, k));  // a paused download is continued: its part goes through both digests again
        Server s = serve(x -> ranged(x, zip));
        assertEquals(ModelVerifier.DAMAGED, assertThrows(IOException.class, () -> fetchSpeech(s, wrongMd5)).getMessage());
        assertFalse(speechZipPart().exists());

        write(speechZipPart(), prefix(zip, k));
        Server again = serve(x -> ranged(x, zip));
        fetchSpeech(again, real);
        assertEquals(Arrays.asList("bytes=" + k + "-"), again.ranges);
        assertTrue(new File(speechRoot(), "m/am/final.mdl").isFile());

        Server chunky = serve(x -> chunked(x, zip, zip.length));
        ModelZip.deleteTree(speechRoot().toPath());
        fetchSpeech(chunky, real);
        assertTrue(new File(speechRoot(), "m/am/final.mdl").isFile());
    }

    @Test
    public void aSpeechZipOfTheWrongSizeOrCutShortIsNeverUnpacked() throws Exception {
        byte[] zip = smallZip("published");
        installedSpeechModel();
        Server longer = serve(x -> whole(x, Arrays.copyOf(zip, zip.length + 10)));
        assertEquals(ModelVerifier.WRONG_SIZE, assertThrows(IOException.class, () -> fetchSpeech(longer, speechRow(zip))).getMessage());
        assertFalse(speechZipPart().exists());
        assertOldSpeechModelKept();

        Server cut = serve(x -> chunked(x, zip, zip.length - 20));
        assertEquals(ModelVerifier.STOPPED_EARLY, assertThrows(IOException.class, () -> fetchSpeech(cut, speechRow(zip))).getMessage());
        assertTrue("the unfinished download is kept to continue", speechZipPart().exists());
        assertFalse(speechZip().exists());
        assertEquals("OLD MODEL", new String(read(new File(speechRoot(), "m/am/old.bin")), StandardCharsets.UTF_8));
        assertFalse(new File(speechRoot(), "m/am/final.mdl").exists());
    }

    @Test
    public void aSpeechZipThatPassesTheCheckButHoldsAnEscapingNameIsRefused_theOldModelStays_theZipIsDeleted() throws Exception {
        byte[] zip = smallZip("published", "m/../../evil.txt");  // a published file would never hold this; the fingerprint here is the bad ZIP's own
        Server s = serve(x -> whole(x, zip));
        installedSpeechModel();
        assertEquals(ModelZip.UNSAFE, assertThrows(IOException.class, () -> fetchSpeech(s, speechRow(zip))).getMessage());
        assertFalse(speechZip().exists());
        assertFalse(speechZipPart().exists());
        assertFalse(new File(tmp.getRoot(), "evil.txt").exists());
        assertOldSpeechModelKept();
    }

    @Test
    public void aSpeechDownloadIsOnlyFetchedFromItsOwnHostAndNeverRedirected() throws Exception {
        byte[] zip = smallZip("published");
        installedSpeechModel();
        for (String to : new String[]{"https://alphacephei.com/vosk/models/other.zip", "https://huggingface.co/x/other.zip", "https://evil.example.com/x.zip", "/vosk/models/other.zip"}) {
            Server s = serve(x -> reply(x, 302, new byte[0], "Location", to));
            IOException e = assertThrows(to, IOException.class, () -> fetchSpeech(s, speechRow(zip)));
            assertEquals(to, "Refused a download that was sent away from alphacephei.com. Nothing was written.", e.getMessage());
            assertEquals("only the first address was asked", 1, s.requests.get());
            assertFalse(speechZipPart().exists());
            assertOldSpeechModelKept();
        }
        // the address itself must be on that host: a row for another host is refused before any request
        ModelCatalog.Entry elsewhere = ModelCatalog.Entry.fromOneHost("t", "tiny.zip", "https://huggingface.co/x/tiny.zip", zip.length, sha(zip), md5(zip), "alphacephei.com");
        Server none = serve(x -> whole(x, zip));
        assertTrue(assertThrows(IOException.class, () -> fetchSpeech(none, elsewhere)).getMessage().startsWith("Refused a download from another site (huggingface.co)"));
        assertEquals(0, none.requests.get());
        // and an AI model row cannot be fetched from the speech host
        ModelCatalog.Entry ai = new ModelCatalog.Entry("t", "tiny.litertlm", "https://alphacephei.com/x/tiny.litertlm", zip.length, sha(zip));
        Server none2 = serve(x -> whole(x, zip));
        assertTrue(assertThrows(IOException.class, () -> download(none2, ai, new Ctl())).getMessage().startsWith("Refused a download from another site (alphacephei.com)"));
        assertEquals(0, none2.requests.get());
    }

    @Test
    public void aPausedSpeechDownloadKeepsItsPartAndContinuesToAnUnpackedModel() throws Exception {
        byte[] zip = smallZip("published");
        installedSpeechModel();
        Server s = serve(x -> whole(x, zip));
        Ctl pause = new Ctl();
        pause.stopAfterChecks = 0;
        assertThrows(InterruptedIOException.class, () -> fetchSpeech(s, speechRow(zip), pause));
        assertFalse(speechZip().exists());
        assertOldSpeechModelKept();

        write(speechZipPart(), prefix(zip, 100));
        Server again = serve(x -> ranged(x, zip));
        fetchSpeech(again, speechRow(zip));
        assertEquals(Arrays.asList("bytes=100-"), again.ranges);
        assertTrue(new File(speechRoot(), "m/am/final.mdl").isFile());
        assertFalse(speechZipPart().exists());
    }

    @Test
    public void whatAKilledUnpackLeftBehindIsCleanedAtTheNextDownload_andNeverCountsAsTheModel() throws Exception {
        byte[] zip = smallZip("published");
        put(new File(speechRoot(), ".unpack-99/m/am/half.bin"), "half".getBytes(StandardCharsets.UTF_8));
        write(speechZip(), "a verified ZIP whose unpack was killed".getBytes(StandardCharsets.UTF_8));
        assertFalse("a half-unpacked folder is not the model", new File(speechRoot(), "m").exists());
        Server s = serve(x -> whole(x, zip));
        fetchSpeech(s, speechRow(zip));
        assertEquals(Arrays.asList("m"), Arrays.asList(speechRoot().list()));
        assertTrue(new File(speechRoot(), "m/am/final.mdl").isFile());
        assertFalse(speechZip().exists());
    }

    @Test
    public void aFailedSpeechDownloadStillRestoresAModelThatWasSetAsideAndCutOff() throws Exception {
        // the app was killed between the two renames of an earlier install: the old model is only in ".old-*"
        put(new File(speechRoot(), ".old-5-5/am/old.bin"), "OLD MODEL".getBytes(StandardCharsets.UTF_8));
        put(new File(speechRoot(), ".old-5-5/conf/old.conf"), "old conf".getBytes(StandardCharsets.UTF_8));
        Server s = serve(x -> reply(x, 500, new byte[0]));
        assertTrue(assertThrows(IOException.class, () -> fetchSpeech(s, speechRow(smallZip("published")))).getMessage().contains("500"));
        assertOldSpeechModelKept();  // it was put back before the download started, and the failed download did not touch it
    }
}
