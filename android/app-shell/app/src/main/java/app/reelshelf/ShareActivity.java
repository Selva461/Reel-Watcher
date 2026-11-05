package app.reelshelf;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * Receives "Share" from Instagram (a reel link), from Meta AI (its answer), or a reel video from the gallery. It only saves what was shared and closes
 * at once, so you stay in Instagram. Nothing is processed now: open Reel Shelf and tap Start when you want.
 */
public class ShareActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent in = getIntent();
        String type = in == null ? null : in.getType();
        if (type != null && type.startsWith("image/")) {  // screenshots shared from the gallery: kept to be read
            List<Uri> uris = new ArrayList<>();
            if (Intent.ACTION_SEND_MULTIPLE.equals(in.getAction())) {
                ArrayList<Uri> many = in.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                if (many != null) uris.addAll(many);
            } else {
                Uri one = in.getParcelableExtra(Intent.EXTRA_STREAM);
                if (one != null) uris.add(one);
            }
            int n = ScreenshotReader.addPictures(this, uris);
            Toast.makeText(this, n == 0 ? "Could not keep those pictures"
                    : n + (n == 1 ? " picture" : " pictures") + " saved. Open Reel Shelf, Start, Read my screenshots (or wait for the nightly run).",
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        if (type != null && type.startsWith("video/")) {  // a reel video (Instagram's Download, a screen recording): read whole
            List<Uri> uris = new ArrayList<>();
            if (Intent.ACTION_SEND_MULTIPLE.equals(in.getAction())) {
                ArrayList<Uri> many = in.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                if (many != null) uris.addAll(many);
            } else {
                Uri one = in.getParcelableExtra(Intent.EXTRA_STREAM);
                if (one != null) uris.add(one);
            }
            int n = ScreenshotReader.addVideos(this, uris);
            Toast.makeText(this, n == 0 ? "Could not keep that video"
                    : n + (n == 1 ? " video" : " videos") + " saved. Reel Shelf reads the whole reel on Start (or at night).",
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        String text = null;
        if (in != null && Intent.ACTION_SEND.equals(in.getAction())) {
            CharSequence t = in.getCharSequenceExtra(Intent.EXTRA_TEXT);
            String subject = in.getStringExtra(Intent.EXTRA_SUBJECT);
            text = t == null ? subject : (subject != null && !t.toString().contains(subject) ? subject + "\n" + t : t.toString());
        }
        if (text == null || text.trim().isEmpty()) {
            Toast.makeText(this, "Nothing to save: share a reel link or a text", Toast.LENGTH_SHORT).show();
        } else {
            LocalBridge.queueShared(this, text);
            boolean link = text.matches("(?s).*(instagram\\.com/(reels?|p|tv)/|youtube\\.com/(shorts/|watch)|youtu\\.be/).*");
            Toast.makeText(this, link ? "Saved to Reel Shelf. Open it and tap Start when you want the notes."
                    : "Saved to Reel Shelf. Open it to file this answer.", Toast.LENGTH_LONG).show();
        }
        finish();
    }
}
