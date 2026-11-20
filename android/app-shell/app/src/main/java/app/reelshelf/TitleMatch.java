package app.reelshelf;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TreeSet;

/**
 * Fuzzy title matching with plain maths (no AI): text clean-up, edit distance and word-set overlap.
 * Pure Java so it is tested on a computer and shared by the Process button and the nightly check.
 */
final class TitleMatch {
    private TitleMatch() {}

    /** Words that screenshots and reels add around a title and that are never part of it. */
    private static final Set<String> NOISE = new HashSet<>(Arrays.asList(
            "official", "trailer", "teaser", "full", "movie", "film", "hd", "4k", "1080p", "720p", "netflix", "prime",
            "video", "hotstar", "disney", "hulu", "crunchyroll", "watch", "now", "streaming", "online", "free", "eng", "sub",
            "dub", "dubbed", "subbed", "hindi", "tamil", "telugu", "season", "episode", "ep", "chapter", "ch", "vol",
            "volume", "manga", "anime", "series", "webtoon", "manhwa", "manhua", "must", "recommendation", "recommended",
            "reels", "reel", "shorts", "fyp", "viral", "explained", "review", "scene", "edit", "clip", "clips"));

    private static final String[][] ROMAN = {{"ii", "2"}, {"iii", "3"}, {"iv", "4"}, {"v", "5"}, {"vi", "6"}, {"vii", "7"}};

    /** Lower case, no accents, "&" as "and", no punctuation, roman numerals as digits, single spaces. */
    static String norm(String s) {
        if (s == null) return "";
        String t = Normalizer.normalize(s, Normalizer.Form.NFKD).replaceAll("\\p{M}+", "");
        t = t.toLowerCase(Locale.ROOT).replace("&", " and ").replace("'", "").replace("’", "");
        t = t.replaceAll("[^\\p{L}\\p{N}]+", " ").trim().replaceAll("\\s+", " ");
        if (t.isEmpty()) return t;
        String[] w = t.split(" ");
        for (int i = 0; i < w.length; i++) for (String[] r : ROMAN) if (i > 0 && w[i].equals(r[0])) w[i] = r[1];
        return String.join(" ", w);
    }

    /** Cleans what was read off a screenshot: drops a trailing "(2010)", hashtags' "#", and noise words at the ends. */
    static String clean(String raw) {
        if (raw == null) return "";
        String s = raw.replace('#', ' ').replace('_', ' ');
        s = s.replaceAll("(?i)\\(\\s*(19|20)\\d\\d\\s*\\)", " ");
        // camelCase hashtags like #TheDarkKnight
        s = s.replaceAll("(?<=\\p{Ll})(?=\\p{Lu})", " ");
        List<String> w = new ArrayList<>(Arrays.asList(norm(s).split(" ")));
        while (!w.isEmpty() && NOISE.contains(w.get(w.size() - 1))) w.remove(w.size() - 1);
        while (!w.isEmpty() && NOISE.contains(w.get(0))) w.remove(0);
        return String.join(" ", w).trim();
    }

    /** A 4-digit year 1900..2039 written in the text, or 0. */
    static int yearIn(String raw) {
        if (raw == null) return 0;
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("(?<!\\d)(19\\d\\d|20[0-3]\\d)(?!\\d)").matcher(raw);
        return m.find() ? Integer.parseInt(m.group(1)) : 0;
    }

    static int levenshtein(String a, String b) {
        int[] prev = new int[b.length() + 1];
        int[] cur = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) prev[j] = j;
        for (int i = 1; i <= a.length(); i++) {
            cur[0] = i;
            for (int j = 1; j <= b.length(); j++) {
                int c = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + c);
            }
            int[] t = prev;
            prev = cur;
            cur = t;
        }
        return prev[b.length()];
    }

    /** 1 for the same text, 0 for nothing in common (edit distance relative to length). */
    static double ratio(String a, String b) {
        if (a.isEmpty() && b.isEmpty()) return 1;
        int n = Math.max(a.length(), b.length());
        return n == 0 ? 0 : 1.0 - (double) levenshtein(a, b) / n;
    }

    private static TreeSet<String> words(String s) {
        TreeSet<String> t = new TreeSet<>();
        for (String w : s.split(" ")) if (!w.isEmpty()) t.add(w);
        return t;
    }

    /**
     * How alike two titles are, 0..1. The best of: edit distance on the whole text, on the words sorted, and on the
     * words both share (so "Attack on Titan" still matches "Attack on Titan Final Season" well, but not perfectly).
     */
    static double similarity(String x, String y) {
        String a = norm(x);
        String b = norm(y);
        if (a.isEmpty() || b.isEmpty()) return 0;
        if (a.equals(b)) return 1;
        double best = ratio(a, b);
        TreeSet<String> wa = words(a);
        TreeSet<String> wb = words(b);
        best = Math.max(best, ratio(String.join(" ", wa), String.join(" ", wb)));
        TreeSet<String> both = new TreeSet<>(wa);
        both.retainAll(wb);
        if (!both.isEmpty()) {
            TreeSet<String> onlyA = new TreeSet<>(wa);
            onlyA.removeAll(both);
            TreeSet<String> onlyB = new TreeSet<>(wb);
            onlyB.removeAll(both);
            String common = String.join(" ", both);
            String sa = (common + " " + String.join(" ", onlyA)).trim();
            String sb = (common + " " + String.join(" ", onlyB)).trim();
            // the shared words alone score high only when they are most of both titles
            double cover = (double) common.length() / Math.max(sa.length(), sb.length());
            double set = Math.max(ratio(sa, sb), 0.6 + 0.35 * cover);
            if (onlyA.isEmpty() || onlyB.isEmpty()) best = Math.max(best, Math.min(0.95, set));
            else best = Math.max(best, set * 0.9);
        }
        // a one-word title like "Up" must not match "Upgrade" by edit distance alone
        if (Math.min(a.length(), b.length()) <= 3 && !a.equals(b)) best = Math.min(best, 0.5);
        return Math.max(0, Math.min(1, best));
    }

    /** The highest similarity between any of the texts read and any of the names a title is known by. */
    static double bestSimilarity(List<String> queries, List<String> names) {
        double best = 0;
        for (String q : queries) for (String n : names) best = Math.max(best, similarity(q, n));
        return best;
    }
}
