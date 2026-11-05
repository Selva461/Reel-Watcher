package app.reelshelf;

import android.accessibilityservice.AccessibilityService;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * "Read while I scroll" (off unless you switch it on in Android's Accessibility settings). While you scroll Instagram
 * yourself and a comment section is on screen, it keeps the text that is already visible, so Reel Shelf can add the
 * comments to that reel's notes. It only listens to Instagram (see res/xml/comment_reader.xml), never taps, types or
 * scrolls, and keeps everything on the phone. Reel Shelf files the comments the next time it opens.
 */
public class CommentReader extends AccessibilityService {
    private static final String QUEUE = "scroll_comments";
    private static final int MAX_SCREENS = 300;
    private long last;
    private String lastKey = "";

    static boolean enabled(Context c) {
        String on = Settings.Secure.getString(c.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        return on != null && on.contains(new ComponentName(c, CommentReader.class).flattenToString());
    }

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
    }

    /** The comment screens kept so far, as JSON [{at, lines}], and the queue is emptied. */
    static synchronized String take(Context c) {
        String q = prefs(c).getString(QUEUE, "[]");
        prefs(c).edit().remove(QUEUE).apply();
        return q;
    }

    private static synchronized void keep(Context c, List<String> lines) {
        try {
            JSONArray q = new JSONArray(prefs(c).getString(QUEUE, "[]"));
            JSONObject o = new JSONObject();
            o.put("at", System.currentTimeMillis());
            o.put("lines", new JSONArray(lines));
            q.put(o);
            while (q.length() > MAX_SCREENS) q.remove(0);
            prefs(c).edit().putString(QUEUE, q.toString()).apply();
        } catch (Exception ignored) {
            // nothing kept this time
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        if (e == null || e.getPackageName() == null || !"com.instagram.android".contentEquals(e.getPackageName())) return;
        long now = System.currentTimeMillis();
        if (now - last < 1500) return;  // at most one look every 1.5 seconds: almost no battery
        last = now;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        Set<String> seen = new LinkedHashSet<>();
        collect(root, seen, 0);
        List<String> lines = new ArrayList<>(seen);
        int replies = 0;
        boolean header = false;
        for (String l : lines) {
            if (l.equalsIgnoreCase("Reply")) replies++;
            if (l.equalsIgnoreCase("Comments") || l.toLowerCase().startsWith("add a comment")) header = true;
        }
        if (!header || replies < 2) return;  // not a comment section
        String key = String.join("\n", lines);
        if (key.equals(lastKey)) return;
        lastKey = key;
        keep(this, lines.size() > 120 ? lines.subList(0, 120) : lines);
    }

    private static void collect(AccessibilityNodeInfo n, Set<String> out, int depth) {
        if (n == null || depth > 40 || out.size() > 200) return;
        CharSequence t = n.getText();
        if (t == null) t = n.getContentDescription();
        if (t != null) {
            String s = t.toString().trim();
            if (!s.isEmpty() && s.length() < 2000) out.add(s);
        }
        for (int i = 0; i < n.getChildCount(); i++) collect(n.getChild(i), out, depth + 1);
    }

    @Override
    public void onInterrupt() {
    }
}
