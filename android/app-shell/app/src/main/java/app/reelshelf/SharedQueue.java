package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;
import java.util.function.Supplier;

/**
 * The list of things shared to Reel Shelf while the app was closed (reel links, Meta AI answers), kept as JSON text in
 * the app's preferences. Two steps for the page: peek (the items stay in the list) and, once what it made of them is
 * saved, acknowledge them by id. So nothing shared is lost when a save fails or the app dies in between, and two pages
 * that peek at the same time cannot remove each other's items. Pure Java (org.json only), tested on a computer.
 */
final class SharedQueue {
    private SharedQueue() {
    }

    static final int MAX_TEXT = 20000;

    private static JSONArray parse(String queue) {
        try {
            return new JSONArray(queue == null || queue.isEmpty() ? "[]" : queue);
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    /** The list with one more item at the end: {id, text, at}. Text longer than 20000 characters is cut. */
    static String append(String queue, String text, long at, String id) {
        JSONArray a = parse(queue);
        try {
            a.put(new JSONObject().put("id", id).put("text", text.length() > MAX_TEXT ? text.substring(0, MAX_TEXT) : text).put("at", at));
        } catch (JSONException e) {
            return queue == null ? "[]" : queue;
        }
        return a.toString();
    }

    /** What peek found: the items to hand to the page, and the list to keep (items that had no id now have one). */
    static final class Peeked {
        final String items;
        final String queue;
        final boolean changed;

        Peeked(String items, String queue, boolean changed) {
            this.items = items;
            this.queue = queue;
            this.changed = changed;
        }
    }

    /** All items, as a JSON array of {id, text, at}. Items from before ids existed get one, and the list is to be saved. */
    static Peeked peek(String queue, Supplier<String> newId) {
        JSONArray a = parse(queue);
        boolean changed = false;
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.optJSONObject(i);
            if (o == null || !o.optString("id").isEmpty()) continue;
            try {
                o.put("id", newId.get());
                changed = true;
            } catch (JSONException ignored) {
                // left without an id: it is handed out again next time
            }
        }
        String text = a.toString();
        return new Peeked(text, text, changed);
    }

    /** The list without the items whose ids are in idsJson (a JSON array of strings). Asking twice changes nothing more. */
    static String acknowledge(String queue, String idsJson) {
        Set<String> gone = new HashSet<>();
        try {
            JSONArray ids = new JSONArray(idsJson == null ? "[]" : idsJson);
            for (int i = 0; i < ids.length(); i++) {
                String id = ids.optString(i);
                if (!id.isEmpty()) gone.add(id);
            }
        } catch (JSONException e) {
            return queue == null ? "[]" : queue;
        }
        JSONArray a = parse(queue);
        JSONArray keep = new JSONArray();
        for (int i = 0; i < a.length(); i++) {
            Object it = a.opt(i);
            if (it instanceof JSONObject && gone.contains(((JSONObject) it).optString("id"))) continue;
            keep.put(it);
        }
        return keep.toString();
    }
}
