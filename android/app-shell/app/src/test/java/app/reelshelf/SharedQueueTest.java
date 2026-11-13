package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.util.concurrent.atomic.AtomicInteger;

/** The list of shared items: peek leaves them in place, acknowledging by id removes exactly those. */
public class SharedQueueTest {
    private static String ids(String... a) {
        return new JSONArray(java.util.Arrays.asList(a)).toString();
    }

    private static int size(String queue) throws Exception {
        return new JSONArray(queue).length();
    }

    private static final AtomicInteger N = new AtomicInteger();

    private static String next() {
        return "gen-" + N.incrementAndGet();
    }

    @Test
    public void anAppendedItemHasAnIdItsTextAndTheTime() throws Exception {
        String q = SharedQueue.append("[]", "https://www.instagram.com/reel/AAAAA1/", 5, "id-1");
        JSONObject o = new JSONArray(q).getJSONObject(0);
        assertEquals("id-1", o.getString("id"));
        assertEquals("https://www.instagram.com/reel/AAAAA1/", o.getString("text"));
        assertEquals(5, o.getLong("at"));
    }

    @Test
    public void anEmptyOrMissingListGrowsFromNothingAndTextIsCapped() throws Exception {
        assertEquals(1, size(SharedQueue.append(null, "a", 1, "x")));
        assertEquals(1, size(SharedQueue.append("", "a", 1, "x")));
        StringBuilder big = new StringBuilder();
        for (int i = 0; i < 25000; i++) big.append('z');
        String q = SharedQueue.append("[]", big.toString(), 1, "x");
        assertEquals(SharedQueue.MAX_TEXT, new JSONArray(q).getJSONObject(0).getString("text").length());
    }

    @Test
    public void peekLeavesEveryItemInTheList() throws Exception {
        String q = SharedQueue.append(SharedQueue.append("[]", "one", 1, "a"), "two", 2, "b");
        SharedQueue.Peeked p = SharedQueue.peek(q, SharedQueueTest::next);
        assertEquals(2, size(p.items));
        assertEquals(2, size(p.queue));
        assertFalse("nothing to rewrite when every item has an id", p.changed);
        assertEquals("a", new JSONArray(p.items).getJSONObject(0).getString("id"));
    }

    @Test
    public void itemsFromBeforeIdsExistedGetOneAndStayTheSameNextTime() throws Exception {
        String legacy = "[{\"text\":\"old\",\"at\":1},{\"text\":\"older\",\"at\":0}]";
        SharedQueue.Peeked p = SharedQueue.peek(legacy, SharedQueueTest::next);
        assertTrue(p.changed);
        JSONArray a = new JSONArray(p.queue);
        String id0 = a.getJSONObject(0).getString("id");
        assertFalse(id0.isEmpty());
        assertFalse(id0.equals(a.getJSONObject(1).getString("id")));
        SharedQueue.Peeked again = SharedQueue.peek(p.queue, () -> "must not be used");
        assertFalse(again.changed);
        assertEquals(id0, new JSONArray(again.items).getJSONObject(0).getString("id"));
    }

    @Test
    public void acknowledgeRemovesOnlyTheListedItems() throws Exception {
        String q = "[]";
        for (String id : new String[]{"a", "b", "c"}) q = SharedQueue.append(q, "text " + id, 1, id);
        String left = SharedQueue.acknowledge(q, ids("a", "c"));
        JSONArray a = new JSONArray(left);
        assertEquals(1, a.length());
        assertEquals("b", a.getJSONObject(0).getString("id"));
    }

    @Test
    public void acknowledgingTwiceOrFromTheOtherPageIsHarmless() throws Exception {
        String q = SharedQueue.append(SharedQueue.append("[]", "one", 1, "a"), "two", 2, "b");
        String once = SharedQueue.acknowledge(q, ids("a"));
        assertEquals(once, SharedQueue.acknowledge(once, ids("a")));
        assertEquals(1, size(SharedQueue.acknowledge(once, ids("nothing-like-this"))));
    }

    @Test
    public void itemsSharedBetweenPeekAndAcknowledgeAreKept() throws Exception {
        String q = SharedQueue.append("[]", "first", 1, "a");
        SharedQueue.Peeked p = SharedQueue.peek(q, SharedQueueTest::next);  // the page takes "first"
        String later = SharedQueue.append(p.queue, "second", 2, "b");  // the user shares again meanwhile
        String left = SharedQueue.acknowledge(later, ids("a"));  // the page saved and acknowledges
        JSONArray a = new JSONArray(left);
        assertEquals(1, a.length());
        assertEquals("second", a.getJSONObject(0).getString("text"));
    }

    @Test
    public void aFailedSaveMeansNoAcknowledgeAndTheItemsComeBack() throws Exception {
        String q = SharedQueue.append("[]", "one", 1, "a");
        SharedQueue.Peeked first = SharedQueue.peek(q, SharedQueueTest::next);
        SharedQueue.Peeked second = SharedQueue.peek(first.queue, SharedQueueTest::next);  // not acknowledged: next opening sees it again
        assertEquals(first.items, second.items);
    }

    @Test
    public void junkInTheListOrTheIdsChangesNothingAndNeverThrows() throws Exception {
        assertEquals("[]", SharedQueue.peek("not json", SharedQueueTest::next).items);
        assertEquals("[]", SharedQueue.acknowledge("not json", ids("a")));
        String q = SharedQueue.append("[]", "one", 1, "a");
        assertEquals(q, SharedQueue.acknowledge(q, "not json"));
        assertEquals(q, SharedQueue.acknowledge(q, null));
        assertEquals(1, size(SharedQueue.acknowledge(q, "[\"\", 7]")));
    }
}
