// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.Arrays;
import java.util.Random;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.CRC32;

/** Zero-dependency JVM tests: run tools/test-spool.sh. No device durability claim. */
public final class ObservationSpoolTest {
    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static int assertions;
    private interface Checked { void run() throws Exception; }
    private static void equal(Object expected, Object actual) {
        assertions++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void check(boolean condition) {
        assertions++;
        if (!condition) throw new AssertionError("Condition failed");
    }
    private static void rejects(Class<? extends Exception> type, Checked action) throws Exception {
        assertions++;
        try { action.run(); }
        catch (Exception e) { if (type.isInstance(e)) return; throw e; }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
    private static String all(ObservationSpool spool) {
        ObservationSpool.Batch batch = spool.peekBatch(24576, 2097152);
        return batch == null ? "" : batch.text;
    }
    private static File child(File root, String name) { return new File(root, name); }
    private static byte[] read(File file) throws IOException { return Files.readAllBytes(file.toPath()); }
    private static void write(File file, byte[] bytes) throws IOException {
        FileOutputStream out = new FileOutputStream(file);
        try { out.write(bytes); } finally { out.close(); }
    }
    private static void remove(File file) throws IOException {
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children == null) throw new IOException("Cannot list test directory");
            for (File entry : children) remove(entry);
        }
        if (!file.delete()) throw new IOException("Cannot delete " + file);
    }
    public static void main(String[] args) throws Exception {
        if (args.length > 0 && "crash-writer".equals(args[0])) {
            ObservationSpool spool = new ObservationSpool(new File(args[1]));
            spool.enqueue("11 battery level=0.5\n12 light lux=8\n");
            // Deliberately bypass close/finalizers/shutdown hooks, emulating process termination.
            Runtime.getRuntime().halt(0);
        }
        File root = Files.createTempDirectory("android-body-spool-").toFile();
        try {
            persistence(root);
            acknowledgement(root);
            overflow(root);
            malformed(root);
            bounds(root);
            corruption(root);
            writeFailure(root);
            lockAndScope(root);
            clear(root);
            discard(root);
            concurrency(root);
            randomizedAcknowledgments(root);
            appendAndCompact(root);
            tornTransaction(root);
            processDeath(root);
            System.out.println("ObservationSpool: " + assertions + " assertions passed");
        } finally { remove(root); }
    }

    private static void persistence(File root) throws Exception {
        File directory = child(root, "persistence");
        ObservationSpool spool = new ObservationSpool(directory);
        equal(0, spool.lineCount());
        check(spool.peekBatch(128, 65536) == null);
        spool.enqueue("");
        check(!child(directory, "observations.spool").exists());
        spool.enqueue("1 battery level=0.5\n2 light lux=é");
        String expected = "1 battery level=0.5\n2 light lux=é\n";
        equal(expected, all(spool));
        equal(expected.getBytes(UTF8).length, spool.byteCount());
        equal(2, spool.lineCount());
        check(!child(directory, "observations.tmp").exists());
        spool.close();
        spool = new ObservationSpool(directory);
        equal(expected, all(spool));
        equal(0L, spool.dropCount());
        ObservationSpool.Batch first = spool.peekBatch(1, 65536);
        equal("1 battery level=0.5\n", first.text);
        equal(1, first.lineCount);
        equal(first.text.getBytes(UTF8).length, first.byteCount);
        equal(1, spool.acknowledge(first.token));
        spool.close();
        spool = new ObservationSpool(directory);
        equal("2 light lux=é\n", all(spool));
        equal(1, spool.acknowledge(spool.peekBatch(128, 65536).token));
        spool.close();
        spool = new ObservationSpool(directory);
        equal("", all(spool));
        spool.close();
    }

    private static void acknowledgement(File root) throws Exception {
        ObservationSpool spool = new ObservationSpool(child(root, "ack"));
        spool.enqueue("1 a\n2 b\n3 c\n");
        ObservationSpool.Batch one = spool.peekBatch(1, 100);
        ObservationSpool.Batch two = spool.peekBatch(2, 100);
        spool.enqueue("4 d\n");
        equal(2, spool.acknowledge(two.token));
        equal(0, spool.acknowledge(one.token));
        equal(0, spool.acknowledge(two.token));
        equal("3 c\n4 d\n", all(spool));
        final ObservationSpool other = new ObservationSpool(child(root, "other"));
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { other.acknowledge(one.token); } });
        spool.close();
        other.close();
        final ObservationSpool reopened = new ObservationSpool(child(root, "ack"));
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { reopened.acknowledge(two.token); } });
        reopened.close();
    }

    private static void overflow(File root) throws Exception {
        File directory = child(root, "overflow");
        ObservationSpool spool = new ObservationSpool(directory, 1024, 4);
        spool.enqueue("1 a\n2 b\n3 c\n4 d\n");
        ObservationSpool.Batch sent = spool.peekBatch(3, 100);
        spool.enqueue("5 e\n6 f\n");
        equal(3L, spool.dropCount());
        equal(4, spool.lineCount());
        String pending = all(spool);
        check(pending.startsWith("4 d\n5 e\n6 f\n"));
        check(pending.contains(" spool overflow dropped=3 policy=oldest\n"));
        equal(0, spool.acknowledge(sent.token));
        equal(pending, all(spool));
        equal("1 a\n2 b\n3 c\n", sent.text);
        ObservationSpool.Batch includingMarker = spool.peekBatch(4, 1024);
        spool.enqueue("7 g\n8 h\n");
        equal(5L, spool.dropCount());
        check(all(spool).startsWith("6 f\n7 g\n8 h\n"));
        equal(1, spool.acknowledge(includingMarker.token));
        check(all(spool).startsWith("7 g\n8 h\n"));
        check(all(spool).contains(" spool overflow dropped=5 policy=oldest\n"));
        pending = all(spool);
        spool.close();
        spool = new ObservationSpool(directory, 1024, 4);
        equal(pending, all(spool));
        equal(5L, spool.dropCount());
        spool.acknowledge(spool.peekBatch(128, 65536).token);
        equal(0, spool.lineCount());
        equal(5L, spool.dropCount());
        spool.close();
        spool = new ObservationSpool(directory, 1024, 4);
        equal(5L, spool.dropCount());
        equal("", all(spool));
        spool.close();
    }

    private static void malformed(File root) throws Exception {
        final ObservationSpool spool = new ObservationSpool(child(root, "invalid"));
        spool.enqueue("1 original\n");
        String[] bad = {null, " ", "   \n", "\u00a0", "\u1680", "\u2000", "\u200a", "\u202f", "\u205f", "\u3000", "1 valid\n \n", "\n", "1 a\n\n", "\n1 a", "1 a\r\n", "1 a\tb", "1 a\u0000", "1 a\u007f", "1 a\u0080", "1 a\u009f", "1 a\u2028", "1 a\u2029", "1 a\ufeff", "1 a\ud800", "1 a\udc00"};
        for (final String text : bad) {
            rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { spool.enqueue(text); } });
            equal("1 original\n", all(spool));
        }
        StringBuilder line = new StringBuilder();
        for (int i = 0; i < 1007; i++) line.append('a');
        spool.enqueue(line.toString());
        final String tooLong = line.append('a').toString();
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { spool.enqueue(tooLong); } });
        final String unicodeTooLong = tooLong.substring(0, 1006) + "é";
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { spool.enqueue(unicodeTooLong); } });
        rejects(IllegalArgumentException.class, new Checked() { public void run() { spool.peekBatch(0, 100); } });
        rejects(IllegalArgumentException.class, new Checked() { public void run() { spool.peekBatch(1, 0); } });
        rejects(IllegalArgumentException.class, new Checked() { public void run() { spool.peekBatch(1, 1); } });
        equal(2, spool.lineCount());
        spool.close();
        final ObservationSpool tiny = new ObservationSpool(child(root, "small-line"), 256, 2);
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { tiny.enqueue(tooLong.substring(0, 200)); } });
        equal(0, tiny.lineCount());
        tiny.close();
        final ObservationSpool transaction = new ObservationSpool(child(root, "invalid-batch"), 1024, 2);
        transaction.enqueue("1 initial\n");
        rejects(IllegalArgumentException.class, new Checked() { public void run() throws Exception { transaction.enqueue("2 a\n3 b\n4 c\n\n"); } });
        equal("1 initial\n", all(transaction));
        equal(0L, transaction.dropCount());
        transaction.close();
    }

    private static void bounds(File root) throws Exception {
        File directory = child(root, "bounds");
        ObservationSpool spool = new ObservationSpool(directory, 400, 20);
        StringBuilder input = new StringBuilder();
        for (int i = 0; i < 1000; i++) input.append(i).append(" light lux=12345678901234567890\n");
        spool.enqueue(input.toString());
        check(child(directory, "observations.spool").length() <= 400);
        check(spool.lineCount() <= 20);
        check(all(spool).contains("999 light lux=12345678901234567890\n"));
        equal(1000L, spool.dropCount() + spool.lineCount() - 1);
        String pending = all(spool);
        spool.close();
        spool = new ObservationSpool(directory, 400, 20);
        equal(pending, all(spool));
        spool.close();
        directory = child(root, "line-limit");
        spool = new ObservationSpool(directory);
        input.setLength(0);
        for (int i = 0; i < 25384; i++) input.append(i).append(" a\n");
        spool.enqueue(input.toString());
        equal(24576, spool.lineCount());
        equal(809L, spool.dropCount());
        check(child(directory, "observations.spool").length() <= 2097152);
        check(all(spool).contains("25383 a\n"));
        spool.close();
        directory = child(root, "default-byte-limit");
        spool = new ObservationSpool(directory);
        StringBuilder line = new StringBuilder();
        for (int i = 0; i < 1000; i++) line.append('a');
        input.setLength(0);
        for (int i = 0; i < 3000; i++) input.append(line).append('\n');
        spool.enqueue(input.toString());
        check(child(directory, "observations.spool").length() <= 2097152);
        equal(3000L, spool.dropCount() + spool.lineCount() - 1);
        spool.close();
    }

    private static void corruption(File root) throws Exception {
        final File directory = child(root, "corrupt");
        ObservationSpool spool = new ObservationSpool(directory);
        spool.enqueue("1 original\n");
        spool.close();
        File file = child(directory, "observations.spool");
        byte[] valid = read(file);
        int[] offsets = {0, 7, 12, 25, 40, valid.length - 1};
        for (int offset : offsets) {
            byte[] damaged = valid.clone();
            damaged[offset] ^= 0x21;
            write(file, damaged);
            rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(directory); } });
            check(Arrays.equals(damaged, read(file)));
        }
        write(file, new byte[] {1, 2, 3});
        rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(directory); } });
        write(file, valid);
        write(child(directory, "observations.tmp"), new byte[] {4, 5, 6});
        spool = new ObservationSpool(directory);
        equal("1 original\n", all(spool));
        check(!child(directory, "observations.tmp").exists());
        spool.close();
        final File firstWrite = child(root, "uncommitted-first-write");
        check(firstWrite.mkdir());
        write(child(firstWrite, "observations.tmp"), valid);
        spool = new ObservationSpool(firstWrite);
        equal("", all(spool));
        check(!child(firstWrite, "observations.tmp").exists());
        spool.close();
        // A well-checksummed unknown version still fails closed.
        byte[] unknown = valid.clone();
        unknown[7] = 3;
        CRC32 crc = new CRC32();
        crc.update(unknown, 0, unknown.length - 8);
        long checksum = crc.getValue();
        for (int i = 0; i < 8; i++) unknown[unknown.length - 1 - i] = (byte) (checksum >>> (8 * i));
        write(file, unknown);
        rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(directory); } });
    }

    private static void writeFailure(File root) throws Exception {
        File directory = child(root, "write-failure");
        final ObservationSpool spool = new ObservationSpool(directory);
        spool.enqueue("1 committed\n");
        final ObservationSpool.Batch batch = spool.peekBatch(1, 100);
        File committed = child(directory, "observations.spool");
        File backup = child(directory, "test-backup");
        check(committed.renameTo(backup));
        check(committed.mkdir());
        rejects(IOException.class, new Checked() { public void run() throws Exception { spool.enqueue("2 rejected\n"); } });
        equal("1 committed\n", all(spool));
        rejects(IOException.class, new Checked() { public void run() throws Exception { spool.acknowledge(batch.token); } });
        equal("1 committed\n", all(spool));
        rejects(IOException.class, new Checked() { public void run() throws Exception { spool.clear(); } });
        equal("1 committed\n", all(spool));
        check(committed.delete());
        check(backup.renameTo(committed));
        spool.close();
        ObservationSpool reopened = new ObservationSpool(directory);
        equal("1 committed\n", all(reopened));
        reopened.close();
    }

    private static void lockAndScope(File root) throws Exception {
        final File directory = child(root, "lock");
        final ObservationSpool spool = new ObservationSpool(directory);
        spool.enqueue("1 first endpoint\n");
        rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(directory); } });
        ObservationSpool other = new ObservationSpool(child(root, "different-scope"));
        equal("", all(other));
        other.enqueue("2 other endpoint\n");
        equal("1 first endpoint\n", all(spool));
        equal("2 other endpoint\n", all(other));
        other.close();
        spool.close();
        spool.close();
        rejects(IllegalStateException.class, new Checked() { public void run() throws Exception { spool.enqueue("3 closed\n"); } });
        ObservationSpool reopened = new ObservationSpool(directory);
        equal("1 first endpoint\n", all(reopened));
        reopened.close();
    }

    private static void clear(File root) throws Exception {
        File directory = child(root, "clear");
        ObservationSpool spool = new ObservationSpool(directory, 1024, 3);
        spool.enqueue("1 a\n2 b\n3 c\n4 d\n");
        long drops = spool.dropCount();
        ObservationSpool.Batch stale = spool.peekBatch(128, 65536);
        equal(3, spool.clear());
        equal(0, spool.clear());
        equal(drops, spool.dropCount());
        spool.enqueue("5 new\n");
        equal(0, spool.acknowledge(stale.token));
        equal("5 new\n", all(spool));
        spool.close();
        spool = new ObservationSpool(directory, 1024, 3);
        equal("5 new\n", all(spool));
        equal(drops, spool.dropCount());
        spool.close();
    }

    private static void discard(File root) throws Exception {
        final File directory = child(root, "discard");
        ObservationSpool spool = new ObservationSpool(directory);
        spool.enqueue("1 retain until confirmed delete\n");
        rejects(IOException.class, new Checked() { public void run() throws Exception { ObservationSpool.discard(directory); } });
        equal("1 retain until confirmed delete\n", all(spool));
        spool.close();
        File file = child(directory, "observations.spool");
        byte[] corrupt = new byte[] {1, 2, 3};
        write(file, corrupt);
        File unexpected = child(directory, "unexpected");
        write(unexpected, new byte[] {4});
        rejects(IOException.class, new Checked() { public void run() throws Exception { ObservationSpool.discard(directory); } });
        check(Arrays.equals(corrupt, read(file)));
        check(unexpected.delete());
        write(child(directory, "observations.tmp"), new byte[] {5, 6});
        ObservationSpool.discard(directory);
        check(!file.exists());
        check(!child(directory, "observations.tmp").exists());
        check(child(directory, "observations.lock").isFile());
        spool = new ObservationSpool(directory);
        equal("", all(spool));
        equal(0L, spool.dropCount());
        spool.close();
        ObservationSpool.discard(child(root, "nonexistent"));
        File nested = child(directory, "observations.spool");
        check(nested.mkdir());
        write(child(nested, "must-remain"), new byte[] {7});
        rejects(IOException.class, new Checked() { public void run() throws Exception { ObservationSpool.discard(directory); } });
        check(child(nested, "must-remain").isFile());
    }

    private static void concurrency(File root) throws Exception {
        final ObservationSpool spool = new ObservationSpool(child(root, "concurrent"));
        final AtomicReference<Throwable> failure = new AtomicReference<Throwable>();
        final List<String> received = new ArrayList<String>();
        final Thread producer = new Thread(new Runnable() { public void run() {
            try { for (int i = 0; i < 150; i++) spool.enqueue(i + " sample\n"); }
            catch (Throwable e) { failure.set(e); }
        }});
        Thread consumer = new Thread(new Runnable() { public void run() {
            try {
                while (producer.isAlive() || spool.lineCount() > 0) {
                    ObservationSpool.Batch batch = spool.peekBatch(7, 1000);
                    if (batch == null) { Thread.yield(); continue; }
                    for (String line : batch.text.split("\n")) received.add(line);
                    spool.acknowledge(batch.token);
                }
            } catch (Throwable e) { failure.set(e); }
        }});
        producer.start();
        consumer.start();
        producer.join();
        consumer.join();
        if (failure.get() != null) throw new AssertionError("Concurrent operation failed", failure.get());
        equal(150, received.size());
        for (int i = 0; i < 150; i++) equal(i + " sample", received.get(i));
        equal(0, spool.lineCount());
        equal(0L, spool.dropCount());
        spool.close();
    }

    private static void randomizedAcknowledgments(File root) throws Exception {
        File directory = child(root, "randomized");
        ObservationSpool spool = new ObservationSpool(directory, 450, 6);
        Random random = new Random(44521);
        List<ObservationSpool.Batch> inFlight = new ArrayList<ObservationSpool.Batch>();
        int sequence = 0;
        File mirror = child(root, "randomized-mirror");
        check(mirror.mkdir());
        for (int iteration = 0; iteration < 300; iteration++) {
            if (random.nextInt(3) != 0 || inFlight.isEmpty()) {
                StringBuilder events = new StringBuilder();
                int count = random.nextInt(9) + 1;
                for (int i = 0; i < count; i++) events.append(++sequence).append(" reading=1234567890123456789\n");
                spool.enqueue(events.toString());
                check(all(spool).contains(sequence + " reading=1234567890123456789\n"));
            } else {
                ObservationSpool.Batch batch = inFlight.get(random.nextInt(inFlight.size()));
                List<String> acknowledged = Arrays.asList(batch.text.split("\n"));
                StringBuilder expected = new StringBuilder();
                for (String line : all(spool).split("\n")) {
                    if (!line.isEmpty() && !acknowledged.contains(line)) expected.append(line).append('\n');
                }
                spool.acknowledge(batch.token);
                equal(expected.toString(), all(spool));
            }
            ObservationSpool.Batch pending = spool.peekBatch(random.nextInt(6) + 1, 450);
            if (pending != null) inFlight.add(pending);
            check(spool.lineCount() <= 6);
            check(child(directory, "observations.spool").length() <= 900);
            check(!child(directory, "observations.tmp").exists());
            write(child(mirror, "observations.spool"), read(child(directory, "observations.spool")));
            ObservationSpool replayed = new ObservationSpool(mirror, 450, 6);
            equal(all(spool), all(replayed));
            equal(spool.dropCount(), replayed.dropCount());
            replayed.close();
        }
        String pending = all(spool);
        long dropped = spool.dropCount();
        spool.close();
        spool = new ObservationSpool(directory, 450, 6);
        equal(pending, all(spool));
        equal(dropped, spool.dropCount());
        spool.close();
    }

    private static void appendAndCompact(File root) throws Exception {
        File directory = child(root, "append-compaction");
        ObservationSpool spool = new ObservationSpool(directory, 512, 5);
        File file = child(directory, "observations.spool");
        spool.enqueue("1 first\n");
        byte[] original = read(file);
        FileInputStream sameFile = new FileInputStream(file);
        spool.enqueue("2 second\n");
        byte[] appended = read(file);
        check(appended.length > original.length);
        equal((long) appended.length, sameFile.getChannel().size());
        check(Arrays.equals(original, Arrays.copyOf(appended, original.length)));
        ObservationSpool.Batch first = spool.peekBatch(1, 100);
        spool.acknowledge(first.token);
        byte[] acknowledged = read(file);
        check(acknowledged.length > appended.length);
        check(Arrays.equals(appended, Arrays.copyOf(acknowledged, appended.length)));
        equal((long) acknowledged.length, sameFile.getChannel().size());
        sameFile.close();
        spool.close();
        spool = new ObservationSpool(directory, 512, 5);
        equal("2 second\n", all(spool));
        int compactions = 0;
        long previousLength = file.length();
        for (int i = 3; i < 80; i++) {
            spool.enqueue(i + " third_and_later\n");
            long length = file.length();
            if (length < previousLength) compactions++;
            check(length <= 1024);
            previousLength = length;
            String expected = all(spool);
            long dropped = spool.dropCount();
            spool.close();
            spool = new ObservationSpool(directory, 512, 5);
            equal(expected, all(spool));
            equal(dropped, spool.dropCount());
        }
        check(compactions > 0);
        check(compactions < 30);
        spool.close();
        // A failed compaction preserves the existing committed journal and in-memory queue.
        directory = child(root, "compaction-failure");
        spool = new ObservationSpool(directory, 256, 2);
        spool.enqueue("1 base\n");
        File temporary = child(directory, "observations.tmp");
        check(temporary.mkdir());
        boolean failed = false;
        for (int i = 2; i < 30; i++) {
            String before = all(spool);
            byte[] beforeFile = read(child(directory, "observations.spool"));
            try { spool.enqueue(i + " appended\n"); }
            catch (IOException expected) {
                equal(before, all(spool));
                check(Arrays.equals(beforeFile, read(child(directory, "observations.spool"))));
                failed = true;
                break;
            }
        }
        check(failed);
        check(temporary.delete());
        spool.close();
    }

    private static void tornTransaction(File root) throws Exception {
        File source = child(root, "torn-source");
        ObservationSpool spool = new ObservationSpool(source);
        File sourceFile = child(source, "observations.spool");
        spool.enqueue("1 durable\n2 retained\n");
        byte[] base = read(sourceFile);
        spool.enqueue("3 uncertain\n");
        byte[] enqueued = read(sourceFile);
        ObservationSpool.Batch acknowledged = spool.peekBatch(1, 100);
        spool.acknowledge(acknowledged.token);
        byte[] acked = read(sourceFile);
        spool.close();
        File recovery = child(root, "torn-recovery");
        check(recovery.mkdir());
        File file = child(recovery, "observations.spool");
        for (int cut = base.length + 1; cut < enqueued.length; cut++) {
            write(file, Arrays.copyOf(enqueued, cut));
            spool = new ObservationSpool(recovery);
            String recovered = all(spool);
            check(recovered.startsWith("1 durable\n2 retained\n"));
            check(!recovered.contains("3 uncertain"));
            check(recovered.contains(" spool recovery reason=incomplete_write loss=unknown\n"));
            spool.close();
            spool = new ObservationSpool(recovery);
            equal(recovered, all(spool));
            spool.close();
        }
        for (int cut = enqueued.length + 1; cut < acked.length; cut++) {
            write(file, Arrays.copyOf(acked, cut));
            spool = new ObservationSpool(recovery);
            check(all(spool).startsWith("1 durable\n2 retained\n3 uncertain\n"));
            check(all(spool).contains(" spool recovery reason=incomplete_write loss=unknown\n"));
            spool.close();
        }
        write(file, acked);
        spool = new ObservationSpool(recovery);
        equal("2 retained\n3 uncertain\n", all(spool));
        spool.close();
        // A complete damaged transaction is corruption, never an assumed torn write.
        byte[] corrupt = enqueued.clone();
        corrupt[corrupt.length - 1] ^= 1;
        write(file, corrupt);
        final File corruptDirectory = recovery;
        rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(corruptDirectory); } });
        check(Arrays.equals(corrupt, read(file)));
        // Repair itself is atomic: failure to create its replacement leaves the torn evidence.
        byte[] torn = Arrays.copyOf(enqueued, enqueued.length - 1);
        write(file, torn);
        File temporary = child(recovery, "observations.tmp");
        check(temporary.mkdir());
        write(child(temporary, "obstruction"), new byte[] {1});
        rejects(IOException.class, new Checked() { public void run() throws Exception { new ObservationSpool(corruptDirectory); } });
        check(Arrays.equals(torn, read(file)));
        remove(temporary);
        spool = new ObservationSpool(recovery);
        check(all(spool).contains(" spool recovery reason=incomplete_write loss=unknown\n"));
        spool.close();
        // A version-1 complete snapshot is accepted and atomically upgraded on a new enqueue.
        byte[] legacy = base.clone();
        legacy[7] = 1;
        CRC32 crc = new CRC32();
        crc.update(legacy, 0, legacy.length - 8);
        long checksum = crc.getValue();
        for (int i = 0; i < 8; i++) legacy[legacy.length - 1 - i] = (byte) (checksum >>> (8 * i));
        write(file, legacy);
        spool = new ObservationSpool(recovery);
        equal("1 durable\n2 retained\n", all(spool));
        spool.enqueue("3 upgraded\n");
        spool.close();
        spool = new ObservationSpool(recovery);
        equal("1 durable\n2 retained\n3 upgraded\n", all(spool));
        equal(2, (int) read(file)[7]);
        spool.close();
    }

    private static void processDeath(File root) throws Exception {
        File directory = child(root, "crash");
        String java = child(new File(System.getProperty("java.home")), "bin/java").getAbsolutePath();
        Process process = new ProcessBuilder(java, "-cp", System.getProperty("java.class.path"),
                ObservationSpoolTest.class.getName(), "crash-writer", directory.getAbsolutePath()).inheritIO().start();
        equal(0, process.waitFor());
        ObservationSpool spool = new ObservationSpool(directory);
        equal("11 battery level=0.5\n12 light lux=8\n", all(spool));
        spool.close();
    }
}
