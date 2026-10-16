// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.IOException;
import java.io.FileInputStream;

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
    private static String readFile(File file) throws IOException {
        FileInputStream in = new FileInputStream(file);
        try {
            byte[] buf = new byte[(int) file.length()];
            int off = 0;
            while (off < buf.length) {
                int n = in.read(buf, off, buf.length - off);
                if (n < 0) break;
                off += n;
            }
            return new String(buf, 0, off, "US-ASCII");
        } finally { in.close(); }
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

        // Truncation: output exceeding 1024 bytes is marked truncated
        File longFile = File.createTempFile("test", ".long");
        longFile.deleteOnExit();
        StringBuilder longContent = new StringBuilder();
        for (int i = 0; i < 2000; i++) longContent.append('x');
        java.io.FileWriter fw = new java.io.FileWriter(longFile);
        fw.write(longContent.toString());
        fw.close();
        BoundedEvaluator.addAllowedPath(longFile.getAbsolutePath());
        BoundedEvaluator.Result longResult = execOk("read " + longFile.getAbsolutePath(), clock);
        ok(longResult.truncated, "long output should be marked truncated");
        ok(longResult.output.length() == BoundedEvaluator.MAX_OUTPUT_PER_COMMAND, "truncated output should be exactly 1024 bytes");
        longFile.delete();

        // Truncation: short output is not marked truncated
        BoundedEvaluator.Result shortResult = execOk("clock", clock);
        ok(!shortResult.truncated, "short output should not be marked truncated");

        // write/exec: bounded verbs inside a temp files dir (Option A substrate)
        File bodyDir = new File(System.getProperty("java.io.tmpdir"), "eval-write-exec-" + System.nanoTime());
        ok(bodyDir.mkdirs(), "bodyDir should be created");
        BoundedEvaluator.Session body = new BoundedEvaluator.Session(bodyDir, 1000);

        // write: \n escapes become real newlines on disk; row reports path+bytes
        BoundedEvaluator.Result w1 = body.execute(BoundedEvaluator.parse("write s.sh #!/bin/sh\\necho genome-marker-42\\n", bodyDir), clock);
        ok(w1.ok, "write should succeed");
        ok(w1.output.startsWith("wrote path=s.sh bytes="), "write row: " + w1.output);
        File sFile = new File(bodyDir, "s.sh");
        ok(sFile.isFile(), "write should persist the script");
        ok(readFile(sFile).equals("#!/bin/sh\necho genome-marker-42\n"), "write should unescape \\n");

        // exec: the persisted script is the exec target; marker + rc reported
        BoundedEvaluator.Result e1 = body.execute(BoundedEvaluator.parse("exec s.sh", bodyDir), clock);
        ok(e1.ok, "exec should succeed");
        ok(e1.output.contains("uid=1000"), "exec row should carry parent uid: " + e1.output);
        ok(e1.output.contains("cmd=s.sh"), "exec row should name the target: " + e1.output);
        ok(e1.output.contains("output=genome-marker-42"), "exec marker: " + e1.output);
        ok(e1.output.contains("exit=0"), "exec rc: " + e1.output);

        // rerun: same target, no rewrite before the second exec, same marker+rc
        BoundedEvaluator.Result e2 = body.execute(BoundedEvaluator.parse("exec s.sh", bodyDir), clock);
        ok(e2.ok && e2.output.contains("output=genome-marker-42") && e2.output.contains("exit=0"), "rerun row: " + e2.output);

        // exec output bound: command output clamps to 1024 bytes
        body.execute(BoundedEvaluator.parse("write big.sh #!/bin/sh\\nyes genome-big-marker | head -c 2000\\n", bodyDir), clock);
        BoundedEvaluator.Result big = body.execute(BoundedEvaluator.parse("exec big.sh", bodyDir), clock);
        ok(big.ok, "big exec should succeed");
        ok(big.output.length() <= BoundedEvaluator.MAX_OUTPUT_PER_COMMAND, "exec output within 1024 bound");
        ok(big.truncated, "big exec output should be marked truncated");

        // exec timeout: child past the deadline is destroyed, truthful destroyed=
        body.execute(BoundedEvaluator.parse("write t.sh #!/bin/sh\\nsleep 10\\n", bodyDir), clock);
        BoundedExec.TIMEOUT_MS = 100;
        BoundedExec.DESTROY_WAIT_MS = 50;
        BoundedExec.READ_JOIN_MS = 50;
        BoundedEvaluator.Result to;
        try {
            to = body.execute(BoundedEvaluator.parse("exec t.sh", bodyDir), clock);
        } finally {
            BoundedExec.TIMEOUT_MS = 5000;
            BoundedExec.DESTROY_WAIT_MS = 1000;
            BoundedExec.READ_JOIN_MS = 1000;
        }
        ok(to.ok, "exec timeout is an observed outcome, not a command error");
        ok(to.output.contains("timeout reason=no-exit destroyed=true"), "timeout row: " + to.output);

        // exec missing target: truthful unavailable reason
        BoundedEvaluator.Result missing = body.execute(BoundedEvaluator.parse("exec nope.sh", bodyDir), clock);
        ok(missing.ok, "missing target is an observed outcome");
        ok(missing.output.contains("unavailable reason="), "missing row: " + missing.output);
        ok(missing.output.contains("No such file or directory"), "missing row should name ENOENT: " + missing.output);

        // exec without uid: token omitted
        BoundedEvaluator.Session anon = new BoundedEvaluator.Session(bodyDir, -1);
        BoundedEvaluator.Result e3 = anon.execute(BoundedEvaluator.parse("exec s.sh", bodyDir), clock);
        ok(e3.ok && !e3.output.contains("uid="), "uid omitted when unknown: " + e3.output);

        // denials: paths outside the app files dir are rejected at parse
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("write ../escape.sh x", bodyDir); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("write /etc/passwd x", bodyDir); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("exec ../s.sh", bodyDir); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("exec /etc/passwd", bodyDir); } });
        try {
            BoundedEvaluator.parse("write /etc/passwd x", bodyDir);
            throw new AssertionError("traversal should be rejected");
        } catch (IllegalArgumentException e) {
            ok(e.getMessage().contains("write path not in allowlist: /etc/passwd"), "denial message: " + e.getMessage());
        }

        // write grammar: content and escapes are validated
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("write s.sh", bodyDir); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("write s.sh \\q", bodyDir); } });
        rejects(new Runnable() { public void run() { BoundedEvaluator.parse("exec", bodyDir); } });

        // write/exec without a files dir: rejected, not executed
        BoundedEvaluator.Session noDir = new BoundedEvaluator.Session();
        BoundedEvaluator.Result nd = noDir.execute(BoundedEvaluator.parse("write x.sh echo hi", bodyDir), clock);
        ok(!nd.ok, "write without files dir should fail");
        BoundedEvaluator.Result nde = noDir.execute(BoundedEvaluator.parse("exec s.sh", bodyDir), clock);
        ok(!nde.ok, "exec without files dir should fail");

        // storage bound: cumulative writes capped at 65536 bytes/session
        StringBuilder content = new StringBuilder();
        for (int i = 0; i < 990; i++) content.append('x');
        BoundedEvaluator.Session st = new BoundedEvaluator.Session(bodyDir, -1);
        int writes = 0;
        boolean storageLimitHit = false;
        for (int i = 0; i < 70; i++) {
            BoundedEvaluator.Result r = st.execute(BoundedEvaluator.parse("write f" + i + ".txt " + content, bodyDir), clock);
            if (!r.ok && r.error.equals("session storage limit exceeded")) { storageLimitHit = true; break; }
            writes++;
        }
        ok(storageLimitHit, "session storage limit should be hit");
        equal(66, writes);

        // cleanup
        File[] leftovers = bodyDir.listFiles();
        if (leftovers != null) for (File f : leftovers) f.delete();
        bodyDir.delete();

        // Summary
        System.out.println("BoundedEvaluatorTest: " + count + " tests passed");
        BoundedEvaluator.shutdown();
    }
}
