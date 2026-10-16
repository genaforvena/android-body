// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileOutputStream;
import java.util.Arrays;

/**
 * Zero-dependency JVM tests for the eval outcome line bound: run tools/test-protocol.sh.
 *
 * Drives the real {@link EvalOutcome} against the real {@link ObservationSpool#enqueue}
 * so a line the spool would reject is caught here, not on the phone.
 */
public final class EvalOutcomeTest {
    private static final BoundedEvaluator.Clock CLOCK = new BoundedEvaluator.Clock() {
        @Override public long elapsedRealtime() { return 123456L; }
    };
    private static int assertions;

    private static void check(boolean condition, String what) {
        assertions++;
        if (!condition) throw new AssertionError(what);
    }

    private static File writeFile(File dir, String name, byte[] bytes) throws Exception {
        File file = new File(dir, name);
        FileOutputStream out = new FileOutputStream(file);
        try { out.write(bytes); } finally { out.close(); }
        return file;
    }

    /** Enqueue a built outcome; assert exactly {@code records} non-empty lines, each within the spool bound. */
    private static void enqueue(File dir, String outcome, int records) throws Exception {
        int lines = 0;
        int maxLine = 0;
        int start = 0;
        while (start < outcome.length()) {
            int end = outcome.indexOf('\n', start);
            if (end < 0) end = outcome.length();
            int bytes = outcome.substring(start, end).getBytes(Protocol.UTF8).length;
            if (bytes > 0) { lines++; if (bytes > maxLine) maxLine = bytes; }
            start = end + 1;
        }
        check(lines == records, "expected " + records + " outcome lines, got " + lines);
        check(maxLine <= ObservationSpool.MAX_LINE_BYTES,
                "line " + maxLine + " exceeds " + ObservationSpool.MAX_LINE_BYTES);
        ObservationSpool spool = new ObservationSpool(dir);
        try {
            spool.enqueue(outcome);
            check(spool.lineCount() == records, "spool stored " + spool.lineCount() + " != " + records);
        } finally {
            spool.close();
        }
    }

    public static void main(String[] args) throws Exception {
        File base = new File(System.getProperty("java.io.tmpdir"), "eval-outcome-test-" + System.nanoTime());
        check(base.mkdirs(), "cannot create " + base);

        // 1. A large allowlisted read clamps to the spool bound, reports truncated=true and keeps output=.
        byte[] ascii = new byte[2000];
        Arrays.fill(ascii, (byte) 'a');
        File big = writeFile(base, "big-ascii.txt", ascii);
        BoundedEvaluator.addAllowedPath(big.getAbsolutePath());
        BoundedEvaluator.Command readBig = BoundedEvaluator.parse("read " + big.getAbsolutePath());
        String succeeded = EvalOutcome.succeeded(1, readBig, BoundedEvaluator.execute(readBig, CLOCK));
        enqueue(new File(base, "t1"), succeeded, 2);
        check(succeeded.contains("truncated=true"), "1: truncated=true");
        check(succeeded.contains("output="), "1: output= present");

        // 2. Bytes >= 0x80 decode to U+FFFD (3 bytes each): the clamp must be byte-based, not char-based.
        byte[] high = new byte[2000];
        Arrays.fill(high, (byte) 0x80);
        File bigHigh = writeFile(base, "big-high.txt", high);
        BoundedEvaluator.addAllowedPath(bigHigh.getAbsolutePath());
        BoundedEvaluator.Command readHigh = BoundedEvaluator.parse("read " + bigHigh.getAbsolutePath());
        String highOut = EvalOutcome.succeeded(2, readHigh, BoundedEvaluator.execute(readHigh, CLOCK));
        enqueue(new File(base, "t2"), highOut, 2);
        check(highOut.contains("truncated=true"), "2: truncated=true");

        // 3. A short output is not clamped: truncated=false and the full output is preserved.
        File small = writeFile(base, "small.txt", "hello\n".getBytes(Protocol.UTF8));
        BoundedEvaluator.addAllowedPath(small.getAbsolutePath());
        BoundedEvaluator.Command readSmall = BoundedEvaluator.parse("read " + small.getAbsolutePath());
        String smallOut = EvalOutcome.succeeded(3, readSmall, BoundedEvaluator.execute(readSmall, CLOCK));
        enqueue(new File(base, "t3"), smallOut, 2);
        check(smallOut.contains("truncated=false"), "3: truncated=false");
        check(smallOut.contains("output=hello"), "3: full output preserved");

        // 4. A long denied path is clamped, not rejected; read_denied path= is retained.
        StringBuilder path = new StringBuilder("/");
        while (path.toString().getBytes(Protocol.UTF8).length < 1000) path.append('x');
        String denied = EvalOutcome.denied(4, path.toString());
        enqueue(new File(base, "t4"), denied, 2);
        check(denied.contains("read_denied path="), "4: read_denied path= present");

        // 5. A denied path of astral characters must not split a surrogate pair or overrun the bound.
        StringBuilder astral = new StringBuilder("/");
        for (int i = 0; i < 500; i++) astral.append("\uD83D\uDE00");
        String astralOut = EvalOutcome.denied(5, astral.toString());
        enqueue(new File(base, "t5"), astralOut, 2);
        check(astralOut.contains("read_denied path="), "5: read_denied path= present");

        // 6. The short failed and invalid branches stay within the bound.
        BoundedEvaluator.Command meminfo = BoundedEvaluator.parse("read /proc/meminfo");
        enqueue(new File(base, "t6"), EvalOutcome.failed(6, meminfo, BoundedEvaluator.execute(meminfo, CLOCK)), 2);
        enqueue(new File(base, "t7"), EvalOutcome.invalid(7), 2);

        // 7. A write echoes its content in command=; the receipt must still fit the spool
        // bound. Before the fix, a write at the parse limit produced a 1106-byte line that
        // ObservationSpool.enqueue rejected by throwing.
        File writeDir = new File(base, "write-dir");
        check(writeDir.mkdirs(), "cannot create " + writeDir);
        BoundedEvaluator.Session writes = new BoundedEvaluator.Session(writeDir, -1);
        StringBuilder writeInput = new StringBuilder("write big.txt ");
        while (writeInput.length() < 1007) writeInput.append('A');
        BoundedEvaluator.Command writeBig = BoundedEvaluator.parse(writeInput.toString(), writeDir);
        String writeOut = EvalOutcome.succeeded(7, writeBig, writes.execute(writeBig, CLOCK));
        enqueue(new File(base, "t8"), writeOut, 2);
        check(writeOut.contains("truncated=true"), "7: clamped command is marked truncated");

        // 8. A write that fails still bounds the echoed command value and marks the clamp.
        StringBuilder failInput = new StringBuilder("write missingdir/f.txt ");
        while (failInput.length() < 1007) failInput.append('A');
        BoundedEvaluator.Command writeFail = BoundedEvaluator.parse(failInput.toString(), writeDir);
        BoundedEvaluator.Result failResult = writes.execute(writeFail, CLOCK);
        check(!failResult.ok, "8: write to a missing parent dir should fail");
        String failOut = EvalOutcome.failed(8, writeFail, failResult);
        enqueue(new File(base, "t9"), failOut, 2);
        check(failOut.contains("truncated=true"), "8: clamped command is marked truncated");

        // 9. The parse limit is char-based but the line bound is byte-based: astral content at
        // the parse limit must still fit, and fit must not split a surrogate pair.
        StringBuilder astralInput = new StringBuilder("write astral.txt ");
        while (astralInput.length() + 2 <= 1007) astralInput.append("\uD83D\uDE00");
        BoundedEvaluator.Command writeAstral = BoundedEvaluator.parse(astralInput.toString(), writeDir);
        String astralWriteOut = EvalOutcome.succeeded(9, writeAstral, writes.execute(writeAstral, CLOCK));
        enqueue(new File(base, "t10"), astralWriteOut, 2);
        check(astralWriteOut.contains("truncated=true"), "9: clamped command is marked truncated");

        // 10. Both variable fields clamped on one line: a long allowlisted read path plus an
        // output larger than the clamp budget. The command value is cut, then the output.
        StringBuilder segment = new StringBuilder();
        while (segment.length() < 900) segment.append('r');
        File nested = base;
        for (int i = 0; i < 5; i++) nested = new File(nested, segment.substring(i * 180, (i + 1) * 180));
        check(nested.mkdirs(), "cannot create " + nested);
        File longFile = writeFile(nested, "big-ascii.txt", ascii);
        BoundedEvaluator.addAllowedPath(longFile.getAbsolutePath());
        BoundedEvaluator.Command readLong = BoundedEvaluator.parse("read " + longFile.getAbsolutePath());
        String bothOut = EvalOutcome.succeeded(10, readLong, BoundedEvaluator.execute(readLong, CLOCK));
        enqueue(new File(base, "t11"), bothOut, 2);
        check(bothOut.contains("truncated=true"), "10: both clamps are marked truncated");

        System.out.println("EvalOutcome: " + assertions + " assertions passed");
    }
}
