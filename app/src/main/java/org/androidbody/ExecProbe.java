// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.Charset;

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
 * {@code /system/bin/sh} spawns no descendants of its own, so a process-tree
 * kill is not required; if the target script backgrounds one and that
 * descendant still holds the merged stream when the decision is taken, the
 * probe reports {@code unavailable reason=exec stdout open at direct-child
 * exit} when the reader's blocking read had already begun at that exit, and a
 * silent empty success otherwise (see {@link BoundedExec} for the measured
 * reader contract). A descendant that writes only after the direct child's
 * exit can be dropped, so exec targets must not background processes. The
 * exec machinery itself is shared with the consumer write/exec verbs in
 * {@link BoundedExec}.
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
        try {
            FileOutputStream out = new FileOutputStream(probeFile);
            try { out.write(PROBE_CONTENT.getBytes(ASCII)); }
            finally { out.close(); }
            if (!probeFile.setExecutable(true, true)) {
                return "probe exec unavailable reason=dac-setup session=" + sessionId;
            }
            BoundedExec.Outcome outcome = BoundedExec.run(command, args);
            if (outcome.ok) {
                return "probe exec uid=" + uid + " cmd=" + command + " output=" + outcome.output.trim() + " exit=" + outcome.exit + " session=" + sessionId;
            }
            if (outcome.timedOut) {
                return "probe exec timeout reason=no-exit destroyed=" + outcome.destroyed + " session=" + sessionId;
            }
            return "probe exec unavailable reason=" + outcome.reason + " session=" + sessionId;
        } catch (IOException | RuntimeException e) {
            return "probe exec unavailable reason=" + BoundedExec.reason(e) + " session=" + sessionId;
        }
    }
}
