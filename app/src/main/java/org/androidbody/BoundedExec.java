// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Bounded direct-exec machinery shared by {@link ExecProbe} (build-time probe)
 * and {@code BoundedEvaluator} (consumer write/exec verbs). Executes the
 * target file itself via {@link ProcessBuilder} — not a platform binary with
 * the file as an argument — reads merged stdout/stderr up to a bound, and
 * destroys a child that outlives its deadline, reporting the destroy result
 * truthfully. Never throws: every failure lands in {@link Outcome#reason}.
 *
 * <p>Bounds: output ≤ 4096 B, duration ≤ 5 s, destroy-wait ≤ 1 s,
 * reader-join ≤ 1 s. The target script is run by {@code /system/bin/sh};
 * if it backgrounds a descendant, {@code Process#destroy()} kills only the
 * direct child and the descendant is reparented. The consumer contract is
 * that exec targets must not background processes; {@code destroyed} reports
 * whether the direct child was reaped, not whether orphans remain.
 */
final class BoundedExec {
    static final int MAX_OUTPUT_BYTES = 4096;
    static int TIMEOUT_MS = 5000;
    static int DESTROY_WAIT_MS = 1000;
    static int READ_JOIN_MS = 1000;
    static int POLL_MS = 50;
    private static final Charset ASCII = Charset.forName("US-ASCII");

    /** Bounded exec result; exactly one of ok / timedOut / reason is set. */
    static final class Outcome {
        final boolean ok;
        final boolean timedOut;
        final boolean destroyed;
        final String output;
        final int exit;
        final String reason;
        private Outcome(boolean ok, boolean timedOut, boolean destroyed, String output, int exit, String reason) {
            this.ok = ok;
            this.timedOut = timedOut;
            this.destroyed = destroyed;
            this.output = output;
            this.exit = exit;
            this.reason = reason;
        }
    }

    private BoundedExec() { }

    /**
     * Execute {@code command} with {@code args} under the caller's identity.
     * Never throws: a spawn failure, read failure, over-bound output or an
     * interrupted wait is returned as an Outcome with {@code reason} set.
     */
    static Outcome run(String command, String... args) {
        Process process = null;
        try {
            List<String> cmd = new ArrayList<String>();
            cmd.add(command);
            if (args != null) cmd.addAll(Arrays.asList(args));
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            process = pb.start();

            final InputStream stdout = process.getInputStream();
            final byte[] buf = new byte[MAX_OUTPUT_BYTES + 1];
            final int[] size = {0};
            final IOException[] readError = {null};
            Thread reader = new Thread(new Runnable() {
                @Override public void run() {
                    try {
                        int s = 0;
                        while (s < buf.length) {
                            int count = stdout.read(buf, s, buf.length - s);
                            if (count < 0) break;
                            if (count == 0) { readError[0] = new IOException("exec stdout read made no progress"); return; }
                            s += count;
                        }
                        size[0] = s;
                    } catch (IOException e) {
                        readError[0] = e;
                    }
                }
            }, "bounded-exec-reader");
            reader.start();

            boolean exited = waitForExit(process, TIMEOUT_MS);
            if (!exited) {
                process.destroy();
                boolean destroyed = waitForExit(process, DESTROY_WAIT_MS);
                reader.join(READ_JOIN_MS);
                return new Outcome(false, true, destroyed, null, -1, null);
            }
            reader.join(READ_JOIN_MS);
            if (readError[0] != null) return new Outcome(false, false, false, null, -1, reason(readError[0]));
            if (size[0] > MAX_OUTPUT_BYTES) return new Outcome(false, false, false, null, -1, reason(new IOException("exec output exceeds probe bound")));
            return new Outcome(true, false, false, new String(buf, 0, size[0], ASCII), process.exitValue(), null);
        } catch (IOException | InterruptedException | RuntimeException e) {
            if (process != null) process.destroy();
            return new Outcome(false, false, false, null, -1, reason(e));
        }
    }

    /**
     * Bounded, control-char-free failure reason: the exception class plus its
     * message, so a denial can be told apart from a missing target (EACCES vs
     * ENOENT) instead of collapsing to one opaque token.
     */
    static String reason(Throwable e) {
        String message = e.getMessage();
        if (message == null) return e.getClass().getSimpleName();
        String cleaned = message.replaceAll("\\p{Cntrl}+", " ").trim();
        if (cleaned.length() > 160) cleaned = cleaned.substring(0, 160);
        return e.getClass().getSimpleName() + " " + cleaned;
    }

    /**
     * API-1-safe bounded wait: polls {@link Process#exitValue()} until the
     * deadline. Returns true once the child has exited, false on timeout.
     * {@code waitFor(long, TimeUnit)} is API 26 and cannot be used at minSdk 18.
     *
     * <p>The deadline is checked only after a poll, and the final sleep is
     * capped to the remaining time, so a poll always happens at or after the
     * deadline. Checking the deadline before sleeping instead (and sleeping a
     * full {@link #POLL_MS}) returns false without ever observing an exit that
     * lands in the last poll window — {@code destroyed=false} for a child that
     * was in fact reaped.
     */
    static boolean waitForExit(Process process, long timeoutMs) throws InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (true) {
            try {
                process.exitValue();
                return true;
            } catch (IllegalThreadStateException e) {
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0) return false;
                Thread.sleep(Math.min(POLL_MS, remaining));
            }
        }
    }
}
