// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileOutputStream;
import java.util.Set;

/**
 * Zero-dependency JVM regression tests for {@link BoundedExec}'s reader contract.
 *
 * <p>Guards two measured defects of the shipped pipe reader (research-methods
 * wake 118263, against the unmodified class): a target that writes and then
 * backgrounds a descendant holding the merged stream previously returned
 * {@code ok=true} with empty output, so "target printed nothing" and "target
 * output was dropped" were indistinguishable; and the reader thread was parked
 * in the pipe read for the descendant's lifetime.
 *
 * <p>These cases pin what the reader can observe, and nothing more (genome wake
 * 119604, measured on JDK 17.0.20.1 with {@code /bin/sh} = dash; the class doc
 * carries the evidence): bytes written before the direct child exits are always
 * reported; the open-stream reason is emitted exactly when the reader is still
 * blocked in the read at the decision, which means a writer was still open; and
 * the JVM ends the reader's view of the pipe at the direct child's exit, so a
 * descendant that writes only later can be dropped silently. The backgrounding
 * cases therefore accept either truthful rendering — the open-stream reason, or
 * a success carrying the bytes written before that exit — and never a success
 * that invents output or omits bytes the target wrote before it exited.
 *
 * <p>Run {@code gradle :app:testBoundedExec}. These cases are the same shape as
 * research-methods' three-case probe (echo baseline, write+background,
 * sleep-past-timeout) plus the over-bound case, which pins the check order: a
 * stream that filled the buffer is reported as over-bound, not as open.
 */
public final class BoundedExecTest {
    private static int count;

    private static void ok(boolean condition, String message) {
        count++;
        if (!condition) throw new AssertionError(message);
    }

    private static void contains(String haystack, String needle) {
        count++;
        if (haystack == null || !haystack.contains(needle))
            throw new AssertionError("Expected '" + haystack + "' to contain '" + needle + "'");
    }

    private static File writeScript(File dir, String name, String content) throws Exception {
        File file = new File(dir, name);
        FileOutputStream out = new FileOutputStream(file);
        try { out.write(content.getBytes("US-ASCII")); } finally { out.close(); }
        ok(file.setExecutable(true, true), "script is not owner-executable: " + file);
        return file;
    }

    private static int liveReaders() {
        int live = 0;
        Set<Thread> threads = Thread.getAllStackTraces().keySet();
        for (Thread thread : threads)
            if (thread.isAlive() && "bounded-exec-reader".equals(thread.getName())) live++;
        return live;
    }

    private static boolean noLiveReader(long budgetMs) throws Exception {
        long deadline = System.currentTimeMillis() + budgetMs;
        while (System.currentTimeMillis() < deadline) {
            if (liveReaders() == 0) return true;
            Thread.sleep(20);
        }
        return liveReaders() == 0;
    }

    private static long decided(BoundedExec.Outcome outcome, long startedAt) {
        return System.currentTimeMillis() - startedAt;
    }

    public static void main(String[] ignored) throws Exception {
        File dir = new File(System.getProperty("java.io.tmpdir"), "bounded-exec-test");
        dir.mkdirs();

        // 1. Baseline: a target that prints and exits reports its output and rc.
        BoundedExec.Outcome printed = BoundedExec.run("/bin/echo", "genome-roundtrip");
        ok(printed.ok, "printing target should succeed: " + printed.reason);
        contains(printed.output, "genome-roundtrip");
        ok(printed.exit == 0, "baseline exit: " + printed.exit);
        ok(printed.reason == null, "baseline carries no reason: " + printed.reason);
        BoundedExec.Outcome silent = BoundedExec.run("/bin/true");
        ok(silent.ok, "silent target should succeed: " + silent.reason);
        ok(silent.output != null && silent.output.isEmpty(), "silent output: '" + silent.output + "'");
        ok(silent.exit == 0, "silent exit: " + silent.exit);

        // Shrink the bounds so the remaining cases resolve in well under a second.
        BoundedExec.TIMEOUT_MS = 300;
        BoundedExec.DESTROY_WAIT_MS = 300;
        BoundedExec.READ_JOIN_MS = 200;
        // The decision must land inside the shrunk window (~0.8 s) and stay far
        // from the 4 s a descendant holds the stream open, so an unbounded join
        // cannot pass as bounded.
        final long decisionBoundMs = 3000;
        try {
            // 3. The parked rendering: a descendant holds the merged stream and
            //    writes only after the decision, so at decision time the pipe
            //    holds no bytes. Two renderings are legitimate and both are
            //    truthful: the reader was still blocked at the decision (the
            //    open-stream reason), or the JVM ended its view of the pipe at
            //    the direct child's exit, dropping the target's later write (a
            //    success carrying no output, because the target wrote nothing
            //    before that exit). A success must never invent output.
            File late = writeScript(dir, "late.sh", "#!/bin/sh\n{ sleep 3; echo late-marker; } &\nexit 0\n");
            long startedAt = System.currentTimeMillis();
            BoundedExec.Outcome lateOutcome = BoundedExec.run(late.getAbsolutePath());
            ok(decided(lateOutcome, startedAt) < decisionBoundMs,
               "decision was not bounded: " + decided(lateOutcome, startedAt) + " ms");
            if (lateOutcome.ok) {
                ok(lateOutcome.output != null && lateOutcome.output.isEmpty(),
                   "the target wrote nothing before its exit: '" + lateOutcome.output + "'");
            } else {
                contains(lateOutcome.reason, "exec stdout open at direct-child exit");
                ok(lateOutcome.output == null, "an unavailable outcome carries no output: " + lateOutcome.output);
            }

            // 3b. A target that closes its own merged stream is a real EOF, not
            //     the JVM's end-of-view at process exit: the success carries the
            //     complete output, deterministically.
            File closed = writeScript(dir, "closed.sh", "#!/bin/sh\necho done\nexec 1>&-\n");
            startedAt = System.currentTimeMillis();
            BoundedExec.Outcome closedOutcome = BoundedExec.run(closed.getAbsolutePath());
            ok(decided(closedOutcome, startedAt) < decisionBoundMs,
               "decision was not bounded: " + decided(closedOutcome, startedAt) + " ms");
            ok(closedOutcome.ok, "a target that closed its stream should succeed: " + closedOutcome.reason);
            contains(closedOutcome.output, "done");
            ok(closedOutcome.exit == 0, "closed-stream exit: " + closedOutcome.exit);

            // 4. write + background: the direct child exits 0 while a descendant
            //    holds the merged stream. Two renderings are legitimate and both
            //    are truthful — the reader was still blocked at the decision, or
            //    the JVM ended its view of the pipe at the direct child's exit.
            //    "target printed nothing" must stay distinct from "the output was
            //    dropped".
            File bg = writeScript(dir, "bg.sh", "#!/bin/sh\necho before\nsleep 4 &\nexit 0\n");
            startedAt = System.currentTimeMillis();
            BoundedExec.Outcome backgrounded = BoundedExec.run(bg.getAbsolutePath());
            ok(decided(backgrounded, startedAt) < decisionBoundMs,
               "decision was not bounded: " + decided(backgrounded, startedAt) + " ms");
            if (backgrounded.ok) {
                ok(backgrounded.output != null && backgrounded.output.contains("before"),
                   "ok=true must carry the target's output: '" + backgrounded.output + "'");
            } else {
                contains(backgrounded.reason, "exec stdout open at direct-child exit");
            }

            // 5. Timeout of a direct binary: no descendant, so the stream closes
            //    with the child and the destroy result is reported truthfully.
            startedAt = System.currentTimeMillis();
            BoundedExec.Outcome timedOut = BoundedExec.run("/bin/sleep", "30");
            ok(decided(timedOut, startedAt) < decisionBoundMs,
               "decision was not bounded: " + decided(timedOut, startedAt) + " ms");
            ok(!timedOut.ok && timedOut.timedOut, "sleep past the deadline should time out: " + timedOut.reason);
            ok(timedOut.destroyed, "destroyed= must be truthful: " + timedOut.reason);

            // 6. Over-bound: a stream that filled the buffer is over-bound even
            //    though the reader never reached EOF, so the open-stream reason
            //    must not mask the bound.
            File big = writeScript(dir, "big.sh", "#!/bin/sh\nyes genome-big-marker | head -c 5000\n");
            startedAt = System.currentTimeMillis();
            BoundedExec.Outcome overBound = BoundedExec.run(big.getAbsolutePath());
            ok(decided(overBound, startedAt) < decisionBoundMs,
               "decision was not bounded: " + decided(overBound, startedAt) + " ms");
            ok(!overBound.ok, "over-bound target must not report ok");
            contains(overBound.reason, "exec output exceeds probe bound");
        } finally {
            BoundedExec.TIMEOUT_MS = 5000;
            BoundedExec.DESTROY_WAIT_MS = 1000;
            BoundedExec.READ_JOIN_MS = 1000;
        }

        // 7. The backgrounded descendants outlive the decisions; they exit at
        //    4 s, which is what releases the parked reads. A reader lives only as
        //    long as the stream it reads.
        ok(noLiveReader(10000), "readers outlived their streams: " + liveReaders());

        File[] leftovers = dir.listFiles();
        if (leftovers != null) for (File file : leftovers) file.delete();
        dir.delete();

        System.out.println("BoundedExecTest: " + count + " assertions passed");
    }
}
