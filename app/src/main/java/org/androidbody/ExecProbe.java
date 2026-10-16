// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Bounded process-creation probe: writes a retained trivial shell script into the
 * app's own {@code files/}, makes it owner-executable, executes the script itself
 * (not a platform binary with the script as an argument), reads bounded stdout, and
 * reports output/exit/termination. Tests OS process creation, app-private file write
 * and {@code execve} of the app-written file under the installed app identity — the
 * class-4 in-process case, reachable at session start even while collect-only.
 *
 * <p>Bounds: stdout+stderr ≤ 4096 B (merged via {@code redirectErrorStream}),
 * duration ≤ 5 s, storage ≤ 1 file, child destroyed on timeout/OFF.
 * {@code /system/bin/sh} spawns no descendants, so a process-tree kill is not
 * required.
 *
 * <p>Attribution: {@code uid=} is the PARENT's {@code Process.myUid()} (inherited
 * by the child, no privilege change), not an independently-read child identity.
 *
 * <p>DAC/MAC isolation: the app umask writes the file 0600, so
 * {@code setExecutable(true, true)} (owner-only {@code x}, API 1 → 0700) runs before
 * the exec attempt; otherwise a DAC denial would be misattributed to the SELinux MAC
 * decision this probe exists to measure.
 */
public final class ExecProbe {
    private static final int MAX_OUTPUT_BYTES = 4096;
    private static final int TIMEOUT_MS = 5000;
    private static final int DESTROY_WAIT_MS = 1000;
    private static final int READ_JOIN_MS = 1000;
    private static final Charset ASCII = Charset.forName("US-ASCII");
    /** Shebang plus a fixed marker command: one exec measures both {@code app_data_file} and {@code shell_exec}. */
    private static final String PROBE_CONTENT = "#!/system/bin/sh\necho hello\n";
    private static final String PROBE_FILENAME = "probe.txt";

    private ExecProbe() { }

    /**
     * Execute the bounded probe against the app-written script itself. Writes
     * {@code probe.txt} to {@code filesDir}, makes it owner-executable, execs it,
     * and returns the observation line. Never throws.
     */
    public static String observation(int uid, File filesDir, String sessionId) {
        File probeFile = new File(filesDir, PROBE_FILENAME);
        return observation(uid, filesDir, sessionId, probeFile.getAbsolutePath());
    }

    /**
     * Execute the bounded probe with the given command and arguments.
     * Writes {@code probe.txt} to {@code filesDir}, executes the command, and
     * returns the observation line. Never throws — failures are reported as
     * unavailable/timeout lines.
     *
     * @param uid the parent app UID (inherited by the child; inference, not measurement)
     * @param filesDir the app's files directory (writable, bounded storage)
     * @param sessionId the session ID for attribution
     * @param command the fixed exec target (the app-written script by default)
     * @param args command arguments (typically the probe file path)
     */
    public static String observation(int uid, File filesDir, String sessionId, String command, String... args) {
        if (filesDir == null || sessionId == null || command == null)
            throw new IllegalArgumentException("Invalid exec probe input");
        File probeFile = new File(filesDir, PROBE_FILENAME);
        Process process = null;
        try {
            FileOutputStream out = new FileOutputStream(probeFile);
            try { out.write(PROBE_CONTENT.getBytes(ASCII)); }
            finally { out.close(); }
            if (!probeFile.setExecutable(true, true)) {
                return "probe exec unavailable reason=dac-setup session=" + sessionId;
            }

            List<String> cmd = new ArrayList<>();
            cmd.add(command);
            if (args != null) cmd.addAll(Arrays.asList(args));
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            process = pb.start();

            final InputStream stdout = process.getInputStream();
            final byte[] buf = new byte[MAX_OUTPUT_BYTES + 1];
            final int[] size = {0};
            final IOException[] readError = {null};
            Thread reader = new Thread(() -> {
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
            }, "exec-probe-reader");
            reader.start();

            boolean exited = waitForExit(process, TIMEOUT_MS);
            if (!exited) {
                process.destroy();
                boolean destroyed = waitForExit(process, DESTROY_WAIT_MS);
                reader.join(READ_JOIN_MS);
                return "probe exec timeout reason=no-exit destroyed=" + destroyed + " session=" + sessionId;
            }
            reader.join(READ_JOIN_MS);
            if (readError[0] != null) throw readError[0];
            if (size[0] > MAX_OUTPUT_BYTES) throw new IOException("exec output exceeds probe bound");
            String output = new String(buf, 0, size[0], ASCII).trim();
            int exit = process.exitValue();
            return "probe exec uid=" + uid + " cmd=" + command + " output=" + output + " exit=" + exit + " session=" + sessionId;
        } catch (IOException | InterruptedException | RuntimeException e) {
            if (process != null) process.destroy();
            return "probe exec unavailable reason=" + reason(e) + " session=" + sessionId;
        }
    }

    /**
     * Bounded, control-char-free failure reason: the exception class plus its
     * message, so a denial can be told apart from a missing target (EACCES vs
     * ENOENT) instead of collapsing to one opaque token.
     */
    private static String reason(Throwable e) {
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
     */
    private static boolean waitForExit(Process process, long timeoutMs) throws InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            try {
                process.exitValue();
                return true;
            } catch (IllegalThreadStateException e) {
                Thread.sleep(50);
            }
        }
        return false;
    }
}
