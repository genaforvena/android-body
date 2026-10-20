// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.FileOutputStream;

import java.nio.charset.Charset;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * Closed, bounded evaluator for the minimal-substrate investigation.
 * Fixed grammar, bounded output, timeout, and durable terminal state.
 * <p>
 * Wired into BodyService.execute as the eval branch (commit e69d798);
 * Witness review completed -- defects fixed, caveats recorded in the
 * minimal-substrate README. Pure Java (no Android dependencies) for
 * zero-dependency JVM tests.
 * <p>
 * Grammar (fixed allowlist -- no arbitrary code):
 * <ul>
 *   <li>{@code identity} -- report UID/groups (delegates to ExecutionProbe)</li>
 *   <li>{@code clock} -- report elapsedRealtime ms</li>
 *   <li>{@code read <path>} -- read a bounded file (from allowlist only)</li>
 *   <li>{@code env} -- report /proc/self/status (bounded)</li>
 *   <li>{@code write <path> <content>} -- persist a bounded script inside the
 *       app's own {@code files/} ({@code \n} escapes become newlines)</li>
 *   <li>{@code exec <path>} -- exec the app-written file itself (class-4 route:
 *       real app parent via {@link ProcessBuilder}, owner-exec set first)</li>
 * </ul>
 * Bounds: 1,024 bytes/output, 65,536 bytes/session, 10s timeout, 128
 * commands/session, 65,536 bytes cumulative write storage per session; exec
 * stdout ≤ 4096 B and exec duration ≤ 5 s via {@link BoundedExec}, with
 * destroy-on-timeout and a truthful {@code destroyed=} flag. A target that
 * still holds its merged output stream when the decision is taken (a
 * backgrounded descendant) is reported as an unavailable outcome naming the
 * open stream; a descendant that writes only after the direct child's exit can
 * be dropped, which is why exec targets must not background processes (see
 * {@link BoundedExec} for the measured reader contract).
 */
public final class BoundedEvaluator {
    public static final int MAX_OUTPUT_PER_COMMAND = 1024;
    public static final int MAX_TOTAL_OUTPUT = 65536;
    public static final int TIMEOUT_MS = 10000;
    public static final int MAX_COMMANDS_PER_SESSION = 128;
    /** Effective timeout in ms; defaults to TIMEOUT_MS, overridable for tests. */
    static int timeoutMs = TIMEOUT_MS;
    private static final int MAX_STATUS_BYTES = 4096;
    private static final Charset ASCII = Charset.forName("US-ASCII");
    private static final Set<String> ALLOWED_READS;
    static {
        Set<String> paths = new HashSet<String>();
        paths.add("/proc/self/status");
        paths.add("/proc/self/attr/current");
        paths.add("/proc/meminfo");
        ALLOWED_READS = paths;
    }
    private static final ExecutorService EXECUTOR = Executors.newCachedThreadPool(new java.util.concurrent.ThreadFactory() {
        @Override public Thread newThread(Runnable r) {
            Thread t = new Thread(r);
            t.setDaemon(true);
            return t;
        }
    });

    /** Clock abstraction for testability (defaults to SystemClock.elapsedRealtime()). */
    public interface Clock {
        long elapsedRealtime();
    }

    /** Parsed and validated command. */
    public static final class Command {
        public final String name;
        public final String argument;
        /** Unescaped write content; null unless {@code name} is {@code "write"}. */
        public final String writeContent;
        private Command(String name, String argument, String writeContent) {
            this.name = name;
            this.argument = argument;
            this.writeContent = writeContent;
        }
    }

    /** Execution result with durable terminal state. */
    public static final class Result {
        public final boolean ok;
        public final String output;
        public final String error;
        public final String status;
        public final long timestamp;
        public final boolean truncated;
        private Result(boolean ok, String output, String error, String status, long timestamp, boolean truncated) {
            this.ok = ok;
            this.output = output;
            this.error = error;
            this.status = status;
            this.timestamp = timestamp;
            this.truncated = truncated;
        }
    }

    /** Session with bounded total output, command count and write storage. */
    public static final class Session {
        final File filesDir;
        private final int uid;
        private int totalOutput;
        private int commandCount;
        private long writtenBytes;

        /** Read-only session: write/exec are rejected (no files dir). */
        public Session() { this(null, -1); }

        /**
         * @param filesDir the app's own files directory; write/exec paths are
         *                 restricted to it (canonical-prefix check)
         * @param uid      the parent app UID, reported on exec rows; -1 omits it
         */
        public Session(File filesDir, int uid) {
            this.filesDir = filesDir;
            this.uid = uid;
        }

        public Result execute(Command command, Clock clock) {
            if (commandCount >= MAX_COMMANDS_PER_SESSION) {
                return new Result(false, null, "session command limit exceeded", "error", clock.elapsedRealtime(), false);
            }
            commandCount++;
            long writeSize = writeSize(command);
            if (writeSize >= 0 && writtenBytes + writeSize > MAX_TOTAL_OUTPUT) {
                return new Result(false, null, "session storage limit exceeded", "error", clock.elapsedRealtime(), false);
            }
            Result result = BoundedEvaluator.execute(command, clock, filesDir, uid);
            if (result.ok && writeSize >= 0) writtenBytes += writeSize;
            if (result.ok && result.output != null) {
                totalOutput += result.output.getBytes(ASCII).length;
                if (totalOutput > MAX_TOTAL_OUTPUT) {
                    return new Result(false, null, "session output limit exceeded", "error", clock.elapsedRealtime(), false);
                }
            }
            return result;
        }

        /** Bytes a write would persist, or -1 for non-write commands. */
        private static long writeSize(Command command) {
            if (!"write".equals(command.name) || command.writeContent == null) return -1;
            return command.writeContent.getBytes(ASCII).length;
        }

        public void close() {
            // No resources to release; marks session as closed
        }
    }

    private BoundedEvaluator() { }

    /**
     * Parse and validate a command string against the fixed grammar.
     * Write/exec require a files dir and are rejected without one.
     * @throws IllegalArgumentException if the command is invalid
     */
    public static Command parse(String input) {
        return parse(input, null);
    }

    /**
     * Parse and validate a command string against the fixed grammar, with
     * write/exec paths resolved against {@code filesDir} (null rejects them).
     * @throws IllegalArgumentException if the command is invalid
     */
    public static Command parse(String input, File filesDir) {
        if (input == null) throw new IllegalArgumentException("eval input is null");
        String trimmed = input.trim();
        if (trimmed.isEmpty()) throw new IllegalArgumentException("eval input is empty");
        if (trimmed.length() > 1007) throw new IllegalArgumentException("eval input exceeds 1007 bytes");
        String[] parts = trimmed.split("\\s+", 2);
        String name = parts[0];
        String argument = parts.length > 1 ? parts[1].trim() : null;
        if (name.equals("identity") || name.equals("clock") || name.equals("env")) {
            if (argument != null && !argument.isEmpty())
                throw new IllegalArgumentException(name + " takes no argument");
            return new Command(name, null, null);
        }
        if (name.equals("read")) {
            if (argument == null || argument.isEmpty())
                throw new IllegalArgumentException("read requires a path argument");
            if (!ALLOWED_READS.contains(argument))
                throw new IllegalArgumentException("read path not in allowlist: " + argument);
            return new Command(name, argument, null);
        }
        if (name.equals("write")) {
            if (argument == null || argument.isEmpty())
                throw new IllegalArgumentException("write requires path and content");
            String[] sub = argument.split("\\s+", 2);
            String path = sub[0];
            if (sub.length < 2 || sub[1].isEmpty())
                throw new IllegalArgumentException("write requires content");
            try { resolveInFilesDir(filesDir, path); } catch (IllegalArgumentException e) { throw new IllegalArgumentException("write " + e.getMessage()); }
            String content = unescape(sub[1]);
            return new Command(name, path + " " + sub[1], content);
        }
        if (name.equals("exec")) {
            if (argument == null || argument.isEmpty())
                throw new IllegalArgumentException("exec requires a path argument");
            try { resolveInFilesDir(filesDir, argument); } catch (IllegalArgumentException e) { throw new IllegalArgumentException("exec " + e.getMessage()); }
            return new Command(name, argument, null);
        }
        throw new IllegalArgumentException("unknown eval command: " + name);
    }

    /**
     * Execute a parsed command with bounds and timeout.
     * @param command the parsed command (from {@link #parse})
     * @param clock the clock to use for timestamp
     * @return the execution result with durable terminal state
     */
    public static Result execute(Command command, final Clock clock) {
        return execute(command, clock, null, -1);
    }

    /**
     * Execute a parsed command with bounds, timeout and write/exec context.
     * @param filesDir the app's own files directory (null: write/exec fail)
     * @param uid the parent app UID for exec rows (-1: omitted)
     */
    static Result execute(Command command, final Clock clock, final File filesDir, final int uid) {
        if (command == null) throw new IllegalArgumentException("command is null");
        if (clock == null) throw new IllegalArgumentException("clock is null");
        long timestamp = clock.elapsedRealtime();
        Future<String> future = EXECUTOR.submit(new Callable<String>() {
            @Override public String call() throws Exception {
                return runCommand(command, clock, filesDir, uid);
            }
        });
        try {
            String output = future.get(timeoutMs, TimeUnit.MILLISECONDS);
            String bounded = bound(output);
            boolean truncated = output != null && bounded != null && output.length() > bounded.length();
            return new Result(true, bounded, null, "ok", timestamp, truncated);
        } catch (TimeoutException e) {
            future.cancel(true);
            return new Result(false, null, "command exceeded " + TIMEOUT_MS + "ms timeout", "timeout", timestamp, false);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new Result(false, null, "interrupted: " + e.getClass().getSimpleName(), "error", timestamp, false);
        } catch (ExecutionException e) {
            String msg = e.getCause() != null ? e.getCause().getClass().getSimpleName() : e.getClass().getSimpleName();
            return new Result(false, null, msg, "error", timestamp, false);
        } catch (RuntimeException e) {
            return new Result(false, null, e.getClass().getSimpleName(), "error", timestamp, false);
        }
    }

    private static String runCommand(Command command, final Clock clock, final File filesDir, final int uid) throws Exception {
        if (command.name.equals("identity")) {
            return identity();
        }
        if (command.name.equals("clock")) {
            return "elapsed_ms=" + clock.elapsedRealtime();
        }
        if (command.name.equals("read")) {
            return read(command.argument);
        }
        if (command.name.equals("env")) {
            return read("/proc/self/status");
        }
        if (command.name.equals("write")) {
            return write(command, filesDir);
        }
        if (command.name.equals("exec")) {
            return exec(command, filesDir, uid);
        }
        throw new IllegalArgumentException("unknown command: " + command.name);
    }

    private static String identity() {
        try {
            byte[] bytes = readBoundedBytes("/proc/self/status", MAX_STATUS_BYTES);
            String text = new String(bytes, ASCII);
            int uid = -1;
            for (String line : text.split("\\n")) {
                if (line.startsWith("Uid:\t")) {
                    String[] parts = line.substring("Uid:\t".length()).split("\\s+");
                    uid = Integer.parseInt(parts[0]);
                    break;
                }
            }
            if (uid < 0) return "identity unavailable reason=uid_not_found";
            return ExecutionProbe.observation(uid, new ByteArrayInputStream(bytes));
        } catch (IOException e) {
            return "identity unavailable reason=" + e.getClass().getSimpleName();
        }
    }

    /**
     * Read at most {@code maxBytes} from {@code path} using only API-1 classes.
     * @throws IOException if the file cannot be read or exceeds the bound
     */
    private static byte[] readBoundedBytes(String path, int maxBytes) throws IOException {
        InputStream in = new FileInputStream(path);
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] chunk = new byte[1024];
            int total = 0;
            int n;
            while ((n = in.read(chunk)) != -1) {
                total += n;
                if (total > maxBytes) throw new IOException("read exceeds bound");
                out.write(chunk, 0, n);
            }
            return out.toByteArray();
        } finally {
            in.close();
        }
    }

    private static String read(String path) throws IOException {
        byte[] bytes = readBoundedBytes(path, MAX_STATUS_BYTES);
        return new String(bytes, ASCII);
    }

    /**
     * Resolve a write/exec path inside the app's own files dir. Relative paths
     * resolve against {@code filesDir}; the canonical result must stay inside
     * it, so {@code ..} traversal and absolute paths outside are denials.
     * @throws IllegalArgumentException on null dir, empty path or escape
     */
    private static File resolveInFilesDir(File filesDir, String rawPath) {
        if (filesDir == null) throw new IllegalArgumentException("files dir unavailable");
        if (rawPath == null || rawPath.isEmpty()) throw new IllegalArgumentException("path required");
        File file = new File(rawPath);
        if (!file.isAbsolute()) file = new File(filesDir, rawPath);
        try {
            String base = filesDir.getCanonicalPath();
            if (!file.getCanonicalPath().startsWith(base + File.separator))
                throw new IllegalArgumentException("path not in allowlist: " + rawPath);
            return file;
        } catch (IOException e) {
            throw new IllegalArgumentException("path unavailable: " + rawPath);
        }
    }

    /**
     * Unescape write content: {@code \n} becomes a newline, {@code \\} a
     * backslash; any other escape is rejected. The wire protocol is
     * line-based, so a real newline cannot arrive in the command itself.
     */
    private static String unescape(String s) {
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c != '\\') { sb.append(c); continue; }
            if (i + 1 >= s.length()) throw new IllegalArgumentException("write content ends with escape");
            char next = s.charAt(++i);
            if (next == 'n') sb.append('\n');
            else if (next == '\\') sb.append('\\');
            else throw new IllegalArgumentException("write content invalid escape: \\" + next);
        }
        return sb.toString();
    }

    /** Persist an already-validated write inside the app's files dir. */
    private static String write(Command command, File filesDir) throws IOException {
        String path = command.argument.split("\\s+", 2)[0];
        File file = resolveInFilesDir(filesDir, path);
        FileOutputStream out = new FileOutputStream(file);
        try { out.write(command.writeContent.getBytes(ASCII)); } finally { out.close(); }
        return "wrote path=" + path + " bytes=" + command.writeContent.getBytes(ASCII).length;
    }

    /**
     * Exec the app-written file itself under the app identity (class-4 route).
     * The owner-only exec bit is set first so a DAC denial is not misattributed
     * to the SELinux MAC decision; a child past its deadline is destroyed and
     * the destroy result is reported truthfully, and a target that still holds
     * the merged output stream at the direct child's exit is reported as an
     * unavailable outcome naming the open stream.
     */
    private static String exec(Command command, File filesDir, int uid) {
        String path = command.argument;
        File file = resolveInFilesDir(filesDir, path);
        try {
            if (file.isFile() && !file.setExecutable(true, true)) return "exec unavailable reason=dac-setup";
            BoundedExec.Outcome outcome = BoundedExec.run(file.getAbsolutePath());
            String id = uid >= 0 ? "uid=" + uid + " " : "";
            if (outcome.ok) return id + "exec cmd=" + path + " output=" + outcome.output.trim() + " exit=" + outcome.exit;
            if (outcome.timedOut) return id + "exec cmd=" + path + " timeout reason=no-exit destroyed=" + outcome.destroyed;
            return id + "exec cmd=" + path + " unavailable reason=" + outcome.reason;
        } catch (RuntimeException e) {
            return "exec unavailable reason=" + BoundedExec.reason(e);
        }
    }

    private static String bound(String output) {
        if (output == null) return null;
        byte[] bytes = output.getBytes(ASCII);
        if (bytes.length <= MAX_OUTPUT_PER_COMMAND) return output;
        return new String(bytes, 0, MAX_OUTPUT_PER_COMMAND, ASCII);
    }

    /** Test hook: add a path to the allowlist for timeout testing. */
    static void addAllowedPath(String path) {
        ALLOWED_READS.add(path);
    }

    /** Shutdown the executor (for tests). */
    static void shutdown() {
        EXECUTOR.shutdownNow();
    }
}
