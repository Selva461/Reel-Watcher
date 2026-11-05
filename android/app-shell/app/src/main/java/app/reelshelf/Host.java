package app.reelshelf;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;

import java.util.function.Consumer;

/**
 * What window.RN (LocalBridge) needs from whoever shows the built-in page: the app's screen (MainActivity), or the
 * nightly run (NightRun), which loads the same page without a screen. Things that need a screen do nothing at night.
 */
interface Host {
    Context ctx();

    boolean localPageTrusted();

    void callPage(String js);

    void runOnUiThread(Runnable r);

    void toast(String msg);

    void startActivity(Intent i);

    void openExternal(Uri u);


    void pickModelFile(Consumer<Uri> cb);

    void pickFolder(Consumer<Uri> cb);

    /** Android's picture picker, several at once; null or empty when cancelled. */
    void pickImages(Consumer<java.util.List<Uri>> cb);

    void sendToLens(Uri uri);

    void keepScreenOn(boolean on);

    String displayName(Uri uri);

    long sizeOf(Uri uri);

    void setWorking(boolean on);

    /** True only for the nightly run (no screen). */
    boolean isNight();

    /** The nightly run is finished (the page calls this when it has done everything it can). */
    void nightDone();
}
