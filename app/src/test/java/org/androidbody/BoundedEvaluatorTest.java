// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.IOException;

/** Zero-dependency JVM tests for BoundedEvaluator: run tools/test-protocol.sh. */
public final class BoundedEvaluatorTest {
    private static int count;
    private static void equal(Object expected, Object actual) {
        count++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void rejects(Runnable block) {
        count++;
        try { block.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    private static void ok(boolean condition, String message) {
        count++;
        if (!condition) throw new AssertionError(message);
    }
    private static BoundedEvaluator.Command parseOk(String input) {
        count++;
        return BoundedEvaluator.parse(input);
    }
    private static BoundedEvaluator.Result execOk(String input, BoundedEvaluator.Clock clock) {
        count++;
        BoundedEvaluator.Command command = BoundedEvaluator.parse(input);
        return BoundedEvaluator.execute(command, clock);
    }

    public static void main(String[] ignored) throws IOException {
        // Grammar: valid commands
        equal("identity", parseOk("identity").name);
        equal("clock", parseOk("clock").name);
        equal("env", parseOk("env").name);
        equal("read", parseOk("read /proc/self/status").name);
        equal("/proc/self/status", parseOk("read /proc/self/status").argument);
        equal("/proc/self/attr/current", parseOk("read /proc/self/attr/current").argument);
        equal("/proc/meminfo", parseOk("read /proc/meminfo").argument);

        // Grammar: invalid commands
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse(null); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse(""); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("   "); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("unknown"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("identity extra"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("clock extra"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("env extra"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("read"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("read "); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("read /etc/passwd"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("read /data/data/com.android.settings/databases/settings.db"); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("read /proc/self/maps"); } });

        // Clock for testing
        BoundedEvaluator.Clock clock = new BoundedEvaluator.Clock() {
            @Override public long elapsedRealtime() { return 12345L; }
        };

        // identity: real UID from /proc/self/status, not hardcoded
        BoundedEvaluator.Result r1 = execOk("identity", clock);
        ok(r1.ok, "identity should succeed");
        ok(r1.output != null, "identity output should not be null");
        ok(r1.output.length() <= BoundedEvaluator.MAX_OUTPUT_PER_COMMAND, "identity output within bound");
        ok(r1.output.contains("uid="), "identity should contain uid");
        ok(r1.output.contains("groups="), "identity should contain groups");
        ok(!r1.output.contains("10221"), "identity should not contain stale hardcoded UID 10221");
        equal("ok", r1.status);
        equal(12345L, r1.timestamp);

        // clock: elapsedRealtime from Clock, not wall clock
        BoundedEvaluator.Clock knownClock = new BoundedEvaluator.Clock() {
            @Override public long elapsedRealtime() { return 42L; }
        };
        BoundedEvaluator.Result r2 = execOk("clock", knownClock);
        ok(r2.ok, "clock should succeed");
        equal("elapsed_ms=42", r2.output);
        equal("ok", r2.status);

        // env: reads /proc/self/status via read()
        BoundedEvaluator.Result r3 = execOk("env", clock);
        ok(r3.ok, "env should succeed");
        ok(r3.output != null, "env output should not be null");
        ok(r3.output.length() <= BoundedEvaluator.MAX_OUTPUT_PER_COMMAND, "env output within bound");
        ok(r3.output.contains("Uid:"), "env should contain file content");
        equal("ok", r3.status);

        // read: actual file content, not path string
        BoundedEvaluator.Result r4 = execOk("read /proc/self/status", clock);
        ok(r4.ok, "read /proc/self/status should succeed");
        ok(r4.output != null, "read output should not be null");
        ok(r4.output.contains("Uid:"), "read should return file content");
        ok(!r4.output.equals("/proc/self/status"), "read should not return path string");
        equal("ok", r4.status);

        // Bounds: output truncation
        ok(BoundedEvaluator.MAX_OUTPUT_PER_COMMAND == 1024, "max output per command is 1024");
        ok(BoundedEvaluator.MAX_TOTAL_OUTPUT == 65536, "max total output is 65536");
        ok(BoundedEvaluator.TIMEOUT_MS == 10000, "timeout is 10000ms");
        ok(BoundedEvaluator.MAX_COMMANDS_PER_SESSION == 128, "max commands per session is 128");

        // Session: command count limit
        BoundedEvaluator.Session session1 = new BoundedEvaluator.Session();
        int cmds1 = 0;
        boolean cmdLimitHit = false;
        for (int i = 0; i < 200; i++) {
            BoundedEvaluator.Result r = session1.execute(BoundedEvaluator.parse("clock"), clock);
            if (!r.ok && r.error.equals("session command limit exceeded")) {
                cmdLimitHit = true;
                break;
            }
            cmds1++;
        }
        ok(cmdLimitHit, "session command limit should be hit");
        equal(BoundedEvaluator.MAX_COMMANDS_PER_SESSION, cmds1);

        // Session: total output limit
        BoundedEvaluator.Session session2 = new BoundedEvaluator.Session();
        int cmds2 = 0;
        boolean outLimitHit = false;
        for (int i = 0; i < 200; i++) {
            BoundedEvaluator.Result r = session2.execute(BoundedEvaluator.parse("read /proc/self/status"), clock);
            if (!r.ok && r.error.equals("session output limit exceeded")) {
                outLimitHit = true;
                break;
            }
            cmds2++;
        }
        ok(outLimitHit, "session output limit should be hit");
        ok(cmds2 < 200, "should hit output limit before 200 commands");

        // Timeout: genuinely blocking command (FIFO)
        File fifo = File.createTempFile("test", ".fifo");
        fifo.delete();
        try {
            Process mkfifo = Runtime.getRuntime().exec(new String[]{"mkfifo", fifo.getAbsolutePath()});
            mkfifo.waitFor();
            BoundedEvaluator.addAllowedPath(fifo.getAbsolutePath());
            BoundedEvaluator.timeoutMs = 100; // short timeout for testing
            BoundedEvaluator.Clock fastClock = new BoundedEvaluator.Clock() {
                @Override public long elapsedRealtime() { return 1L; }
            };
            BoundedEvaluator.Command fifoCmd = BoundedEvaluator.parse("read " + fifo.getAbsolutePath());
            BoundedEvaluator.Result fifoResult = BoundedEvaluator.execute(fifoCmd, fastClock);
            ok(!fifoResult.ok, "FIFO read should timeout");
            equal("timeout", fifoResult.status);
        } catch (IOException e) {
            throw new AssertionError("FIFO test setup failed: " + e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("FIFO test interrupted: " + e);
        } finally {
            BoundedEvaluator.timeoutMs = BoundedEvaluator.TIMEOUT_MS; // restore
            fifo.delete();
        }

        // Terminal semantics: result has all fields
        ok(r1.timestamp == 12345L, "timestamp is recorded");
        ok(r1.status != null, "status is recorded");
        ok(r1.error == null, "error is null on success");

        // Null command/clock rejection
        rejects(new Runnable() { public void run() { BoundedEvaluator.execute(null, clock); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.execute(parseOk("identity"), null); } });

        // Summary
        System.out.println("BoundedEvaluatorTest: " + count + " tests passed");
        BoundedEvaluator.shutdown();
    }
}
