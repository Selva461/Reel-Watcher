package app.reelshelf;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * Settings are one JSON object kept in the app's preferences. A page sends only the keys it changed, and they are
 * merged into what is stored, so a key changed elsewhere (the other page, an earlier version of this page) is never
 * reverted by an unrelated change. Pure Java (org.json only), tested on a computer.
 */
final class SettingsPatch {
    private SettingsPatch() {
    }

    private static JSONObject object(String text) {
        try {
            return new JSONObject(text == null || text.isEmpty() ? "{}" : text);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    /** The stored settings with the patch's keys set (a key set to null is removed). The stored text when the patch is not an object. */
    static String merge(String stored, String patch) {
        JSONObject p;
        try {
            p = new JSONObject(patch);
        } catch (JSONException | NullPointerException e) {
            return stored == null || stored.isEmpty() ? "{}" : stored;
        }
        JSONObject cur = object(stored);
        List<String> keys = new ArrayList<>();
        for (Iterator<String> it = p.keys(); it.hasNext(); ) keys.add(it.next());
        try {
            for (String k : keys) {
                Object v = p.get(k);
                if (v == JSONObject.NULL) cur.remove(k);
                else cur.put(k, v);
            }
        } catch (JSONException e) {
            return stored == null || stored.isEmpty() ? "{}" : stored;
        }
        return cur.toString();
    }
}
