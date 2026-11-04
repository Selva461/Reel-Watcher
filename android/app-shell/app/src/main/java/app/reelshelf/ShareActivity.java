package app.reelshelf;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

/**
 * Receives "Share" from Instagram (a reel link) or from Meta AI (its answer). It only saves what was shared and closes
 * at once, so you stay in Instagram. Nothing is processed now: open Reel Shelf and tap Start when you want.
 */
public class ShareActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent in = getIntent();
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
            boolean link = text.matches("(?s).*instagram\\.com/(reels?|p|tv)/.*");
            Toast.makeText(this, link ? "Saved to Reel Shelf. Open it and tap Start when you want the notes."
                    : "Saved to Reel Shelf. Open it to file this answer.", Toast.LENGTH_LONG).show();
        }
        finish();
    }
}
