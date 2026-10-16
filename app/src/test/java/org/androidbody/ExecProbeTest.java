// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileInputStream;

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
    private static String read(File file) throws Exception {
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
    public static void main(String[] ignored) throws Exception {
        File dir = new File(System.getProperty("java.io.tmpdir"), "execprobe-test");
        dir.mkdirs();
        File probeFile = new File(dir, "probe.txt");

        // 1. Class-4 default shape: the app-written script is the exec target itself, not an
        //    argument to a platform binary. On this JVM the shebang interpreter /system/bin/sh is
        //    absent, so the run is expected to fail — but the probe's own path must be the target
        //    named in the line (cmd= on success, the exception message on failure). A regression
        //    back to `/system/bin/cat <path>` would name a different program here.
        String result = ExecProbe.observation(1000, dir, "test-session");
        contains(result, probeFile.getAbsolutePath());
        // uid= is only on the success line; on this JVM the run fails before that, so the
        // target assertion above is the class-4 regression.
        contains(result, "session=test-session");
        count++;
        if (!result.startsWith("probe exec ")) throw new AssertionError("Expected probe exec line, got: " + result);
        count++;
        if (result.contains("cmd=/system/bin/cat")) throw new AssertionError("Default still execs a platform binary: " + result);
        // The retained file is an owner-executable shebang script, and it is the file just exec'd.
        count++;
        if (!probeFile.isFile()) throw new AssertionError("Probe file was not written: " + probeFile);
        count++;
        if (!probeFile.canExecute()) throw new AssertionError("Probe file is not owner-executable (DAC setup failed): " + probeFile);
        equal("#!/system/bin/sh\necho hello\n", read(probeFile));

        // 2. Explicit command still reads the same retained script (multi-line output is the script).
        String catResult = ExecProbe.observation(1000, dir, "read-session", "/bin/cat", probeFile.getAbsolutePath());
        contains(catResult, "cmd=/bin/cat");
        contains(catResult, "#!/system/bin/sh");
        contains(catResult, "echo hello");
        contains(catResult, "exit=0");

        // 3. Timeout: /bin/sleep 10 should timeout at 5s
        long start = System.currentTimeMillis();
        String timeoutResult = ExecProbe.observation(1000, dir, "timeout-session", "/bin/sleep", "10");
        long elapsed = System.currentTimeMillis() - start;
        contains(timeoutResult, "probe exec timeout reason=no-exit");
        contains(timeoutResult, "destroyed=true");
        contains(timeoutResult, "session=timeout-session");
        count++;
        if (elapsed > 15000) throw new AssertionError("Timeout took too long: " + elapsed + "ms");

        // 4. Unavailable: nonexistent command, with the failure reason carrying the message
        //    (ENOENT here) so a MAC denial is not collapsed into the same opaque token.
        String unavailableResult = ExecProbe.observation(1000, dir, "unavailable-session", "/nonexistent/binary");
        contains(unavailableResult, "probe exec unavailable reason=");
        contains(unavailableResult, "session=unavailable-session");
        contains(unavailableResult, "IOException");
        contains(unavailableResult, "No such file or directory");

        System.out.println("ExecProbe: " + count + " assertions passed");
    }
}
