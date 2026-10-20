// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Bounded direct-exec machinery shared by {@link ExecProbe} (build-time probe)
 * and {@code BoundedEvaluator} (consumer write/exec verbs). Executes the
 * target file itself via {@link ProcessBuilder} — not a platform binary with
 * the file as an argument — reads merged stdout/stderr up to a bound, and
 * destroys a child that outlives its deadline, reporting the destroy result
 * truthfully. Never throws: every failure lands in {@link Outcome#reason}.
 *
 * <p>Bounds: output ≤ 4096 B, decision ≤ duration + destroy-wait + reader-join.
 * The decision is bounded; the reader thread's lifetime is bounded only by the
 * stream it reads. The target script is run by {@code /system/bin/sh};
 * if it backgrounds a descendant, {@code Process#destroy()} kills only the
 * direct child and the descendant is reparented. The consumer contract is
 * that exec targets must not background processes; {@code destroyed} reports
 * whether the direct child was reaped, not whether orphans remain.
 *
 * <p>The merged stream is read by one daemon reader thread, not by
 * {@code ProcessBuilder.redirectOutput(File)}: that API is level 26
 * ({@code api-versions.xml} on compileSdk 36 records {@code since="26"}) and
 * minSdk is 18, so there is no API-1 route to a file-backed stdout.
 *
 * <p>What the reader can observe, measured on JDK 17.0.20.1 with
 * {@code /bin/sh} = dash (genome wake 119604, 2026-10-20):
 * <ul>
 * <li>Bytes written before the direct child exits are always reported, so an
 * {@code ok=true} outcome carries everything the target wrote up to its exit
 * (up to the bound).</li>
 * <li>{@link Outcome#reason} names the open stream exactly when the reader is
 * still blocked in the read when the decision is taken. A blocked read means a
 * process still holds the write end, so that reason is sound.</li>
 * <li>{@code ok=true} does <em>not</em> prove every write end was closed: the
 * JVM's process-exit handling ends the reader's view of the pipe at the direct
 * child's exit (measured: {@code read} returns -1 within milliseconds of that
 * exit while the OS pipe is still held open by a descendant). A descendant's
 * later write is delivered only when the reader was already blocked in the read
 * at that exit, and dropped otherwise, so "target printed nothing" and "target
 * output was dropped" are not distinguishable in the dropped case (genome wake
 * 122050, JDK 17.0.20.1, {@code /bin/sh} = dash, one case per fresh JVM:
 * {@code READ_JOIN_MS} 5000 with the reader certainly parked delivered a 3 s
 * write 40/40; an immediate exit dropped it 120/120). With the shipped
 * {@code READ_JOIN_MS} 1000 such a write cannot arrive inside the join budget,
 * so it is reported as the open-stream failure below rather than as an empty
 * success. The consumer contract that exec targets must not background
 * processes is what keeps that residual out of reach.</li>
 * </ul>
 *
 * <p>The reader may stay parked in the read until the stream closes, so a
 * reader can outlive the decision it fed; being a daemon it cannot hold the
 * process open.
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

    /**
     * Immutable reader result, published once after the read loop. The decision
     * reads only this object: the join below may time out, so the fields the
     * reader writes cannot be read directly (and {@code buf} must not be read
     * without this publication).
     */
    private static final class ReadResult {
        final boolean eof;
        final int size;
        final Throwable error;
        ReadResult(boolean eof, int size, Throwable error) {
            this.eof = eof;
            this.size = size;
            this.error = error;
        }
    }

    private BoundedExec() { }

    /**
     * Execute {@code command} with {@code args} under the caller's identity.
     * Never throws: a spawn failure, read failure, over-bound output, a reader
     * still parked in the read when the decision is taken, or an interrupted
     * wait is returned as an Outcome with {@code reason} set.
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
            final AtomicReference<ReadResult> published = new AtomicReference<ReadResult>();
            // The reader is a daemon thread because the stream read can block
            // indefinitely: a descendant that holds the merged stream open keeps
            // the read parked until it exits. No deadline can interrupt a
            // blocking read, so this method bounds its decision (below) and
            // leaves the reader's lifetime to the stream. See the class doc.
            Thread reader = new Thread(new Runnable() {
                @Override public void run() {
                    int s = 0;
                    boolean eof = false;
                    Throwable error = null;
                    try {
                        while (s < buf.length) {
                            int count = stdout.read(buf, s, buf.length - s);
                            if (count < 0) { eof = true; break; }
                            if (count == 0) { error = new IOException("exec stdout read made no progress"); break; }
                            s += count;
                        }
                    } catch (IOException | RuntimeException e) {
                        error = e;
                    }
                    published.set(new ReadResult(eof, s, error));
                }
            }, "bounded-exec-reader");
            reader.setDaemon(true);
            reader.start();

            boolean exited = waitForExit(process, TIMEOUT_MS);
            if (!exited) {
                process.destroy();
                boolean destroyed = waitForExit(process, DESTROY_WAIT_MS);
                reader.join(READ_JOIN_MS);
                return new Outcome(false, true, destroyed, null, -1, null);
            }
            reader.join(READ_JOIN_MS);
            ReadResult read = published.get();
            if (read == null) return new Outcome(false, false, false, null, -1, reason(new IOException("exec stdout open at direct-child exit")));
            if (read.error != null) return new Outcome(false, false, false, null, -1, reason(read.error));
            if (read.size > MAX_OUTPUT_BYTES) return new Outcome(false, false, false, null, -1, reason(new IOException("exec output exceeds probe bound")));
            // Unreachable while the loop above ends only at EOF, no progress or
            // the bound; kept so a later loop change cannot report a read that
            // never reached EOF as complete.
            if (!read.eof) return new Outcome(false, false, false, null, -1, reason(new IOException("exec stdout open at direct-child exit")));
            return new Outcome(true, false, false, new String(buf, 0, read.size, ASCII), process.exitValue(), null);
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
