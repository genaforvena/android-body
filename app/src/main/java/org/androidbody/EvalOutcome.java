// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/**
 * Outcome text for the bounded {@code eval} action.
 *
 * Android-free on purpose: {@code BodyService.executeEval} is Android-coupled
 * (SystemClock), so the variable-length outcome text lives here where the
 * deterministic host tests can drive it against the real ObservationSpool.
 *
 * Every outcome is exactly two spool lines: the "requested" line and one result
 * line. The result line is clamped to {@link ObservationSpool#MAX_LINE_BYTES}
 * UTF-8 bytes (the observation-line budget) so a large command output or a long
 * client-supplied read path cannot produce a line the spool rejects, which would
 * otherwise fail the session. The epoch prefix from {@link Protocol#event} is
 * inside the budget, the LF is appended last, and the clamp never splits a code
 * point (a surrogate half is not a character).
 */
final class EvalOutcome {
    private EvalOutcome() { }

    static String requested(long id) {
        return Protocol.event("action " + id + " requested kind=eval");
    }

    static String succeeded(long id, BoundedEvaluator.Command c, BoundedEvaluator.Result r) {
        String body = "action " + id + " succeeded kind=eval command=" + canonical(c)
                + " identity=" + identity(c) + " status=" + r.status;
        String output = sanitize(r.output);
        if (output == null) output = "null"; // keeps the original null-concatenation text
        String unclamped = line(body + " truncated=false output=");
        String clamped = clamp(unclamped, output, ObservationSpool.MAX_LINE_BYTES);
        boolean truncated = r.truncated || clamped.length() < unclamped.length() + output.length() + 1;
        return requested(id) + clamp(line(body + " truncated=" + truncated + " output="), output,
                ObservationSpool.MAX_LINE_BYTES);
    }

    static String failed(long id, BoundedEvaluator.Command c, BoundedEvaluator.Result r) {
        return requested(id) + Protocol.event("action " + id + " failed kind=eval command=" + canonical(c)
                + " identity=" + identity(c) + " status=" + r.status + " error=" + r.error);
    }

    static String denied(long id, String path) {
        return requested(id) + clamp(line("action " + id + " failed reason=read_denied path="), path,
                ObservationSpool.MAX_LINE_BYTES);
    }

    static String invalid(long id) {
        return requested(id) + Protocol.event("action " + id + " failed reason=invalid_arguments");
    }

    private static String canonical(BoundedEvaluator.Command c) {
        return c.name + (c.argument != null ? " " + c.argument : "");
    }

    private static String identity(BoundedEvaluator.Command c) {
        String s = c.name + ":" + (c.argument != null ? c.argument : "");
        return Integer.toHexString(s.hashCode());
    }

    private static String sanitize(String o) {
        return o == null ? null : o.replaceAll("[\\r\\n]+", " ").replaceAll("\\p{Cntrl}", "");
    }

    /** {@link Protocol#event}'s line without its trailing LF, so a clamped tail stays on the same line. */
    private static String line(String content) {
        String s = Protocol.event(content);
        return s.endsWith("\n") ? s.substring(0, s.length() - 1) : s;
    }

    /** Copy as much of {@code variable} as keeps the whole line within {@code maxBytes} UTF-8 bytes. */
    private static String clamp(String prefixNoLf, String variable, int maxBytes) {
        StringBuilder sb = new StringBuilder(prefixNoLf);
        int used = utf8(prefixNoLf);
        for (int i = 0; i < variable.length(); ) {
            int codePoint = variable.codePointAt(i);
            int bytes = utf8(new String(Character.toChars(codePoint)));
            if (used + bytes > maxBytes) break;
            sb.appendCodePoint(codePoint);
            used += bytes;
            i += Character.charCount(codePoint);
        }
        return sb.append('\n').toString();
    }

    private static int utf8(String s) { return s.getBytes(Protocol.UTF8).length; }
}
