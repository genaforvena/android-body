// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
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
 * NOT wired into the live session -- candidate for Witness/Research-methods
 * review before any phone trial. Pure Java (no Android dependencies) for
 * zero-dependency JVM tests.
 * <p>
 * Grammar (fixed allowlist -- no arbitrary code):
 * <ul>
 *   <li>{@code identity} -- report UID/groups (delegates to ExecutionProbe)</li>
 *   <li>{@code clock} -- report elapsedRealtime ms</li>
 *   <li>{@code read <path>} -- read a bounded file (from allowlist only)</li>
 *   <li>{@code env} -- report /proc/self/status (bounded)</li>
 * </ul>
 * Bounds: 1,024 bytes/output, 65,536 bytes/session, 10s timeout, 128 commands/session.
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
    private static final ExecutorService EXECUTOR = Executors.newCachedThreadPool();

    /** Clock abstraction for testability (defaults to SystemClock.elapsedRealtime()). */
    public interface Clock {
        long elapsedRealtime();
    }

    /** Parsed and validated command. */
    public static final class Command {
        public final String name;
        public final String argument;
        private Command(String name, String argument) {
            this.name = name;
            this.argument = argument;
        }
    }

    /** Execution result with durable terminal state. */
    public static final class Result {
        public final boolean ok;
        public final String output;
        public final String error;
        public final String status;
        public final long timestamp;
        private Result(boolean ok, String output, String error, String status, long timestamp) {
            this.ok = ok;
            this.output = output;
            this.error = error;
            this.status = status;
            this.timestamp = timestamp;
        }
    }

    /** Session with bounded total output and command count. */
    public static final class Session {
        private int totalOutput;
        private int commandCount;

        public Result execute(Command command, Clock clock) {
            if (commandCount >= MAX_COMMANDS_PER_SESSION) {
                return new Result(false, null, "session command limit exceeded", "error", clock.elapsedRealtime());
            }
            commandCount++;
            Result result = BoundedEvaluator.execute(command, clock);
            if (result.ok && result.output != null) {
                totalOutput += result.output.getBytes(ASCII).length;
                if (totalOutput > MAX_TOTAL_OUTPUT) {
                    return new Result(false, null, "session output limit exceeded", "error", clock.elapsedRealtime());
                }
            }
            return result;
        }
    }

    private BoundedEvaluator() { }

    /**
     * Parse and validate a command string against the fixed grammar.
     * @throws IllegalArgumentException if the command is invalid
     */
    public static Command parse(String input) {
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
            return new Command(name, null);
        }
        if (name.equals("read")) {
            if (argument == null || argument.isEmpty())
                throw new IllegalArgumentException("read requires a path argument");
            if (!ALLOWED_READS.contains(argument))
                throw new IllegalArgumentException("read path not in allowlist: " + argument);
            return new Command(name, argument);
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
        if (command == null) throw new IllegalArgumentException("command is null");
        if (clock == null) throw new IllegalArgumentException("clock is null");
        long timestamp = clock.elapsedRealtime();
        Future<String> future = EXECUTOR.submit(new Callable<String>() {
            @Override public String call() throws Exception {
                return runCommand(command, clock);
            }
        });
        try {
            String output = future.get(timeoutMs, TimeUnit.MILLISECONDS);
            String bounded = bound(output);
            return new Result(true, bounded, null, "ok", timestamp);
        } catch (TimeoutException e) {
            future.cancel(true);
            return new Result(false, null, "command exceeded " + TIMEOUT_MS + "ms timeout", "timeout", timestamp);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new Result(false, null, "interrupted: " + e.getClass().getSimpleName(), "error", timestamp);
        } catch (ExecutionException e) {
            String msg = e.getCause() != null ? e.getCause().getClass().getSimpleName() : e.getClass().getSimpleName();
            return new Result(false, null, msg, "error", timestamp);
        } catch (RuntimeException e) {
            return new Result(false, null, e.getClass().getSimpleName(), "error", timestamp);
        }
    }

    private static String runCommand(Command command, final Clock clock) throws Exception {
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
