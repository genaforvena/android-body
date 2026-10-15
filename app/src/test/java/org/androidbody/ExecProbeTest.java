// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileOutputStream;

/** Zero-dependency JVM tests for the bounded exec probe contract. Run gradle :app:testExecProbe. */
public final class ExecProbeTest {
    private static int count;
    private static void equal(Object expected, Object actual) {
        count++;
        if (expected == null ? actual != null : !expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void contains(String haystack, String needle) {
        count++;
        if (haystack == null || !haystack.contains(needle)) throw new AssertionError("Expected '" + haystack + "' to contain '" + needle + "'");
    }
    public static void main(String[] ignored) throws Exception {
        File dir = new File(System.getProperty("java.io.tmpdir"), "execprobe-test");
        dir.mkdirs();

        // 1. Normal execution: /bin/cat reads probe.txt
        String result = ExecProbe.observation(1000, dir, "test-session", "/bin/cat", dir + "/probe.txt");
        contains(result, "output=hello");
        contains(result, "exit=0");
        contains(result, "uid=1000");
        contains(result, "session=test-session");
        contains(result, "cmd=/bin/cat");

        // 2. Timeout: /bin/sleep 10 should timeout at 5s
        long start = System.currentTimeMillis();
        String timeoutResult = ExecProbe.observation(1000, dir, "timeout-session", "/bin/sleep", "10");
        long elapsed = System.currentTimeMillis() - start;
        contains(timeoutResult, "probe exec timeout reason=no-exit");
        contains(timeoutResult, "destroyed=true");
        contains(timeoutResult, "session=timeout-session");
        count++;
        if (elapsed > 15000) throw new AssertionError("Timeout took too long: " + elapsed + "ms");

        // 3. Unavailable: nonexistent command
        String unavailableResult = ExecProbe.observation(1000, dir, "unavailable-session", "/nonexistent/binary");
        contains(unavailableResult, "probe exec unavailable reason=");
        contains(unavailableResult, "session=unavailable-session");

        // 4. Default command (just verify it returns a probe exec line)
        String defaultResult = ExecProbe.observation(1000, dir, "default-session");
        count++;
        if (!defaultResult.startsWith("probe exec ")) throw new AssertionError("Expected probe exec line, got: " + defaultResult);

        System.out.println("ExecProbe: " + count + " assertions passed");
    }
}
