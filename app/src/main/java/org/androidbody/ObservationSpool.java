// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.CRC32;

/**
 * Bounded, process-death-safe observation queue. The caller supplies an app-private directory
 * scoped to one normalized endpoint (not its secret), and closes the queue before reopening it.
 * A file lock rejects simultaneous instances. All public operations are synchronized, so a
 * sampler can enqueue while a drainer holds an immutable Batch across a network request.
 *
 * Ordinary mutations append one checksummed transaction and fsync it before changing memory.
 * A snapshot replacement is written, fsynced and atomically renamed only on the first write or
 * when another append would exceed twice the configured logical byte bound. This avoids rewriting
 * the retained history every sampling interval. Java/API18 cannot fsync the parent directory, so
 * this is process-death resilience, not a guarantee against device/storage failure.
 * Complete corrupt/unknown records fail closed. A torn final transaction is never replayed: open
 * atomically replaces the valid prefix with a compacted queue including an explicit
 * "TIME spool recovery reason=incomplete_write loss=unknown" event. A crash during that repair
 * leaves the previous incomplete file or the repaired snapshot; no recovery marker is silently
 * omitted. A stale temporary file is discarded, never promoted to a committed observation.
 *
 * The default logical queue is at most 2 MiB, including snapshot metadata, and at most 24576 lines.
 * Its committed journal file is at most 4 MiB. Atomic compaction temporarily adds at most 2 MiB,
 * plus a zero-byte lock file. The caller must budget this bounded 6 MiB peak per endpoint.
 * Oldest observations are discarded when necessary to retain newest ones. A reserved internal
 * record reports cumulative dropped observation lines as "TIME spool overflow dropped=N
 * policy=oldest". Its original timestamp/text persist; updating the count replaces that record
 * with a new internal ID. Overflow records themselves are not counted as lost observations.
 * Disk corruption or an I/O failure is an error, never an invented sensor value.
 *
 * Delivery is at least once: keep the exact Batch for retries and acknowledge its token only
 * after validating the server's POST acknowledgment. Local IDs are never added to wire text.
 * An acknowledgment removes only surviving records from that peeked prefix, even after overflow
 * or other acknowledgments. Tokens are instance-local, cannot be constructed by callers, and
 * must not be reused after close/reopen. Overflow may discard even an in-flight batch locally;
 * its immutable text remains safe to send, and its acknowledgment cannot remove newer records.
 */
public final class ObservationSpool implements Closeable {
    public static final int DEFAULT_MAX_BYTES = 2 * 1024 * 1024;
    public static final int DEFAULT_MAX_LINES = 24576;
    public static final int MAX_LINE_BYTES = 1007;
    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static final int MAGIC = 0x41425350; // ABSP
    private static final int VERSION = 2;
    private static final int FRAME_MAGIC = 0x41425458; // ABTX
    private static final int TRANSACTION_HEADER = 36;
    private static final int FILE_OVERHEAD = 36;
    private static final int RECORD_OVERHEAD = 13;
    // Maximum encoded overflow record, including a 19-digit timestamp and count.
    private static final int OVERFLOW_RESERVE = 128;
    private final File file;
    private final File temporary;
    private final int maxBytes;
    private final int maxLines;
    private final Object tokenOwner = new Object();
    private RandomAccessFile lockFile;
    private FileLock lock;
    private State state;
    private boolean closed;
    private boolean needsRepair;
    private boolean forceCompaction;
    private long committedLength;

    public ObservationSpool(File directory) throws IOException {
        this(directory, DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES);
    }

    /** Smaller bounds are useful for tests. Byte bound includes binary metadata/checksum. */
    public ObservationSpool(File directory, int maxBytes, int maxLines) throws IOException {
        if (directory == null || maxBytes < 256 || maxBytes > DEFAULT_MAX_BYTES
                || maxLines < 2 || maxLines > DEFAULT_MAX_LINES) {
            throw new IllegalArgumentException("Invalid spool bounds or directory");
        }
        this.maxBytes = maxBytes;
        this.maxLines = maxLines;
        directory = directory.getCanonicalFile();
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Cannot create spool directory");
        file = new File(directory, "observations.spool");
        temporary = new File(directory, "observations.tmp");
        try {
            lockFile = new RandomAccessFile(new File(directory, "observations.lock"), "rw");
            try { lock = lockFile.getChannel().tryLock(); }
            catch (OverlappingFileLockException e) { throw new IOException("Spool is already open", e); }
            if (lock == null) throw new IOException("Spool is already open");
            state = file.exists() ? read() : new State();
            if (temporary.exists() && !temporary.delete()) throw new IOException("Cannot remove uncommitted spool file");
            if (needsRepair) {
                forceCompaction = true;
                enqueue((System.currentTimeMillis() / 1000L)
                        + " spool recovery reason=incomplete_write loss=unknown\n");
                needsRepair = false;
            }
        } catch (IOException e) {
            releaseLock();
            throw e;
        }
    }

    /**
     * Delete only the two known queue files, without parsing them, after explicit user approval.
     * Intended for an OFF-only recovery/delete UI. The same exclusive lock prevents deleting a
     * live spool. Unknown entries or non-file entries fail before any queue file is deleted.
     * Leaves the lock file/directory for the caller to remove after preventing all future opens.
     */
    public static void discard(File directory) throws IOException {
        if (directory == null) throw new IllegalArgumentException("Missing spool directory");
        directory = directory.getCanonicalFile();
        if (!directory.exists()) return;
        if (!directory.isDirectory()) throw new IOException("Invalid spool directory");
        RandomAccessFile guard = new RandomAccessFile(new File(directory, "observations.lock"), "rw");
        FileLock held = null;
        try {
            try { held = guard.getChannel().tryLock(); }
            catch (OverlappingFileLockException e) { throw new IOException("Spool is already open", e); }
            if (held == null) throw new IOException("Spool is already open");
            File[] entries = directory.listFiles();
            if (entries == null) throw new IOException("Cannot list spool directory");
            for (File entry : entries) {
                String name = entry.getName();
                if ((!name.equals("observations.spool") && !name.equals("observations.tmp")
                        && !name.equals("observations.lock")) || !entry.isFile()) {
                    throw new IOException("Unexpected entry in spool directory");
                }
            }
            for (String name : new String[] {"observations.spool", "observations.tmp"}) {
                File queue = new File(directory, name);
                if (queue.exists() && !queue.delete()) throw new IOException("Cannot delete spool file");
            }
        } finally {
            try { if (held != null) held.release(); }
            finally { guard.close(); }
        }
    }

    /**
     * Validate and durably enqueue nonempty LF-delimited text, optionally with a final LF.
     * Empty input is a no-op. Blank lines, controls, invalid Unicode and oversized lines reject
     * the entire call without changing storage. Every stored/wire line ends in LF. A line must
     * fit together with an overflow notice under configured bounds; otherwise it is rejected.
     */
    public synchronized void enqueue(String events) throws IOException {
        requireOpen();
        if (events == null) throw new IllegalArgumentException("Missing observation text");
        if (events.isEmpty()) return;
        State candidate = new State(state);
        long beforeDrops = candidate.dropped;
        int start = 0;
        while (start < events.length()) {
            int end = events.indexOf('\n', start);
            if (end < 0) end = events.length();
            byte[] text = encodeLine(events.substring(start, end));
            if (FILE_OVERHEAD + OVERFLOW_RESERVE + RECORD_OVERHEAD + text.length > maxBytes) {
                throw new IllegalArgumentException("Observation cannot fit spool bounds");
            }
            candidate.add(new Record(nextId(candidate), false, text));
            trim(candidate);
            start = end + 1;
        }
        if (candidate.dropped != beforeDrops) {
            // A replacement notice gets a fresh ID, so an older in-flight token cannot erase it.
            for (int i = candidate.records.size() - 1; i >= 0; i--) {
                if (candidate.records.get(i).overflow) candidate.remove(i);
            }
            long id = nextId(candidate);
            long epoch = System.currentTimeMillis() / 1000L;
            while (true) {
                candidate.add(new Record(id, true, overflowText(epoch, candidate.dropped)));
                long previous = candidate.dropped;
                trim(candidate);
                if (previous == candidate.dropped) break;
                candidate.remove(candidate.records.size() - 1);
            }
        }
        commit(candidate);
    }

    /** Returns null only if empty. A byte limit too small for the first line is an error. */
    public synchronized Batch peekBatch(int maxBatchLines, int maxBatchBytes) {
        requireOpen();
        if (maxBatchLines < 1 || maxBatchBytes < 1) throw new IllegalArgumentException("Invalid batch bounds");
        if (state.records.isEmpty()) return null;
        StringBuilder text = new StringBuilder();
        int lines = 0;
        int bytes = 0;
        long last = 0;
        for (Record record : state.records) {
            if (lines == maxBatchLines || record.text.length > maxBatchBytes - bytes) break;
            text.append(new String(record.text, UTF8));
            bytes += record.text.length;
            lines++;
            last = record.id;
        }
        if (lines == 0) throw new IllegalArgumentException("Batch byte bound cannot fit first observation");
        return new Batch(new Token(tokenOwner, last), text.toString(), lines, bytes);
    }

    /** Persist removal only after POST acknowledgment validation. Repeated tokens are harmless. */
    public synchronized int acknowledge(Token token) throws IOException {
        requireOpen();
        if (token == null || token.owner != tokenOwner) throw new IllegalArgumentException("Foreign spool token");
        State candidate = new State(state);
        int count = 0;
        while (!candidate.records.isEmpty() && candidate.records.get(0).id <= token.lastId) {
            candidate.remove(0);
            count++;
        }
        if (count > 0) commit(candidate);
        return count;
    }

    /**
     * Explicitly discard queued lines after caller obtains user approval. Cumulative drops and
     * sequence IDs remain, so a stale token cannot acknowledge observations enqueued after clear.
     * This is an intentional deletion, not bounded-retention loss, and emits no overflow notice.
     */
    public synchronized int clear() throws IOException {
        requireOpen();
        int removed = state.records.size();
        if (removed > 0) {
            State candidate = new State(state);
            candidate.records.clear();
            candidate.textBytes = 0;
            commit(candidate);
        }
        return removed;
    }

    public synchronized int lineCount() { requireOpen(); return state.records.size(); }
    /** Queued UTF-8 wire bytes, including LF, excluding local IDs and file metadata. */
    public synchronized int byteCount() { requireOpen(); return state.textBytes; }
    /** Cumulative ordinary observation lines dropped by bounded retention, survives acknowledgment. */
    public synchronized long dropCount() { requireOpen(); return state.dropped; }

    @Override public synchronized void close() throws IOException {
        if (closed) return;
        closed = true;
        IOException failure = releaseLock();
        if (failure != null) throw failure;
    }

    private IOException releaseLock() {
        IOException failure = null;
        if (lock != null) {
            try { lock.release(); } catch (IOException e) { failure = e; }
            lock = null;
        }
        if (lockFile != null) {
            try { lockFile.close(); } catch (IOException e) { if (failure == null) failure = e; }
            lockFile = null;
        }
        return failure;
    }

    private void requireOpen() {
        if (closed) throw new IllegalStateException("Spool is closed");
    }

    private static long nextId(State candidate) throws IOException {
        if (candidate.nextId == Long.MAX_VALUE) throw new IOException("Spool sequence exhausted");
        return candidate.nextId++;
    }

    private void trim(State candidate) throws IOException {
        while (candidate.records.size() > maxLines || candidate.fileBytes() > maxBytes) {
            int index = 0;
            while (index < candidate.records.size() && candidate.records.get(index).overflow) index++;
            if (index == candidate.records.size()) throw new IOException("Overflow notice exceeds spool bounds");
            if (candidate.dropped == Long.MAX_VALUE) throw new IOException("Spool drop count exhausted");
            candidate.remove(index);
            candidate.dropped++;
        }
    }

    private static byte[] overflowText(long epoch, long count) {
        return (epoch + " spool overflow dropped=" + count + " policy=oldest\n").getBytes(UTF8);
    }

    private static byte[] encodeLine(String text) {
        if (text.isEmpty() || text.length() > MAX_LINE_BYTES) throw new IllegalArgumentException("Invalid observation line length");
        boolean blank = true;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c < 32 || (c >= 127 && c <= 159) || c == '\u2028' || c == '\u2029' || c == '\ufeff') {
                throw new IllegalArgumentException("Control character in observation");
            }
            // Python's server-side strip() whitespace set, excluding controls rejected above.
            if (!(c == ' ' || c == '\u00a0' || c == '\u1680' || (c >= '\u2000' && c <= '\u200a')
                    || c == '\u202f' || c == '\u205f' || c == '\u3000')) blank = false;
        }
        if (blank) throw new IllegalArgumentException("Blank observation line");
        try {
            ByteBuffer encoded = UTF8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(text + "\n"));
            if (encoded.remaining() > MAX_LINE_BYTES + 1) throw new IllegalArgumentException("Observation line too large");
            byte[] result = new byte[encoded.remaining()];
            encoded.get(result);
            return result;
        } catch (CharacterCodingException e) { throw new IllegalArgumentException("Invalid observation Unicode", e); }
    }

    private void commit(State candidate) throws IOException {
        if (forceCompaction || !file.exists()) {
            compact(candidate);
            return;
        }
        byte[] frame = transaction(candidate);
        if (committedLength + frame.length > 2L * maxBytes) {
            compact(candidate);
            return;
        }
        RandomAccessFile disk = new RandomAccessFile(file, "rw");
        try {
            if (disk.length() != committedLength) throw new IOException("Spool changed while open");
            disk.seek(committedLength);
            try {
                disk.write(frame);
                disk.getFD().sync();
            } catch (IOException e) {
                // If rollback cannot sync, a subsequent mutation must replace the uncertain log.
                forceCompaction = true;
                try { disk.setLength(committedLength); disk.getFD().sync(); }
                catch (IOException ignored) { /* Recovery handles an incomplete tail on reopen. */ }
                throw e;
            }
            committedLength += frame.length;
            state = candidate;
        } finally { disk.close(); }
    }

    private byte[] transaction(State candidate) throws IOException {
        long through = 0;
        long overflow = 0;
        int retained = 0;
        for (Record old : state.records) {
            while (retained < candidate.records.size() && candidate.records.get(retained).id < old.id) retained++;
            if (retained < candidate.records.size() && candidate.records.get(retained).id == old.id) {
                retained++;
            } else if (retained == 0) {
                through = old.id;
            } else if (old.overflow) {
                overflow = old.id;
            } else {
                throw new IOException("Invalid spool transaction removal");
            }
        }
        int appended = 0;
        for (Record record : candidate.records) if (record.id >= state.nextId) appended++;
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        DataOutputStream output = new DataOutputStream(buffer);
        output.writeLong(candidate.nextId);
        output.writeLong(candidate.dropped);
        output.writeLong(through);
        output.writeLong(overflow);
        output.writeInt(appended);
        for (Record record : candidate.records) if (record.id >= state.nextId) writeRecord(output, record);
        output.flush();
        byte[] payload = buffer.toByteArray();
        buffer.reset();
        output.writeInt(FRAME_MAGIC);
        output.writeInt(payload.length);
        output.write(payload);
        output.flush();
        CRC32 checksum = new CRC32();
        checksum.update(buffer.toByteArray());
        output.writeLong(checksum.getValue());
        output.flush();
        return buffer.toByteArray();
    }

    private static void writeRecord(DataOutputStream output, Record record) throws IOException {
        output.writeLong(record.id);
        output.writeByte(record.overflow ? 1 : 0);
        output.writeInt(record.text.length);
        output.write(record.text);
    }

    private void compact(State candidate) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream(candidate.fileBytes());
        DataOutputStream output = new DataOutputStream(buffer);
        output.writeInt(MAGIC);
        output.writeInt(VERSION);
        output.writeLong(candidate.nextId);
        output.writeLong(candidate.dropped);
        output.writeInt(candidate.records.size());
        for (Record record : candidate.records) writeRecord(output, record);
        output.flush();
        CRC32 checksum = new CRC32();
        byte[] body = buffer.toByteArray();
        checksum.update(body);
        output.writeLong(checksum.getValue());
        output.flush();
        byte[] image = buffer.toByteArray();
        if (image.length > maxBytes) throw new IOException("Spool bounds exceeded");
        try {
            FileOutputStream disk = new FileOutputStream(temporary);
            try {
                disk.write(image);
                disk.flush();
                disk.getFD().sync();
            } finally { disk.close(); }
            // Do not delete the old file first: failure must leave the committed queue intact.
            if (!temporary.renameTo(file)) throw new IOException("Cannot atomically replace observation spool");
            state = candidate;
            committedLength = image.length;
            forceCompaction = false;
        } catch (IOException e) {
            // Best effort only. A failed cleanup is still bounded and recovered on next open.
            if (temporary.isFile()) temporary.delete();
            throw e;
        }
    }

    private State read() throws IOException {
        long length = file.length();
        if (!file.isFile() || length < FILE_OVERHEAD || length > 2L * maxBytes) throw new IOException("Invalid spool file size");
        byte[] image = new byte[(int) length];
        DataInputStream disk = new DataInputStream(new FileInputStream(file));
        try {
            disk.readFully(image);
            if (disk.read() != -1) throw new IOException("Spool changed while opening");
        } finally { disk.close(); }
        DataInputStream input = new DataInputStream(new ByteArrayInputStream(image));
        int magic = input.readInt();
        int version = input.readInt();
        // Version 1 was a complete atomic snapshot. Its data can be upgraded without loss.
        if (magic != MAGIC || (version != VERSION && version != 1)) throw new IOException("Unknown spool format");
        State loaded = new State();
        loaded.nextId = input.readLong();
        loaded.dropped = input.readLong();
        int count = input.readInt();
        if (loaded.nextId < 1 || loaded.dropped < 0 || count < 0 || count > maxLines) throw new IOException("Invalid spool metadata");
        long previous = 0;
        for (int i = 0; i < count; i++) {
            Record record = readRecord(input);
            if (record.id <= previous || record.id >= loaded.nextId) throw new IOException("Invalid spool record ID");
            loaded.add(record);
            previous = record.id;
        }
        int offset = image.length - input.available();
        CRC32 checksum = new CRC32();
        checksum.update(image, 0, offset);
        if (input.readLong() != checksum.getValue() || loaded.fileBytes() != offset + 8) {
            throw new IOException("Spool checksum or length mismatch");
        }
        validateState(loaded);
        if (version == 1) {
            if (input.available() != 0) throw new IOException("Trailing legacy spool data");
            forceCompaction = true;
        }
        while (input.available() != 0) {
            offset = image.length - input.available();
            if (input.available() < 8) {
                // Only a prefix of our own frame header qualifies as an interrupted append.
                int available = input.available();
                for (int i = 0; i < Math.min(4, available); i++) {
                    if ((image[offset + i] & 255) != ((FRAME_MAGIC >>> (24 - 8 * i)) & 255)) {
                        throw new IOException("Unknown trailing spool data");
                    }
                }
                needsRepair = true;
                break;
            }
            int frameMagic = input.readInt();
            int payloadSize = input.readInt();
            if (frameMagic != FRAME_MAGIC || payloadSize < TRANSACTION_HEADER
                    || payloadSize > maxBytes + TRANSACTION_HEADER) throw new IOException("Invalid spool transaction header");
            if (input.available() < payloadSize + 8) {
                needsRepair = true;
                break;
            }
            byte[] payload = new byte[payloadSize];
            input.readFully(payload);
            checksum.reset();
            checksum.update(image, offset, 8 + payloadSize);
            if (input.readLong() != checksum.getValue()) throw new IOException("Spool transaction checksum mismatch");
            loaded = replay(loaded, payload);
        }
        committedLength = image.length;
        return loaded;
    }

    private State replay(State old, byte[] payload) throws IOException {
        DataInputStream input = new DataInputStream(new ByteArrayInputStream(payload));
        // Open has not published this state. Reuse it to avoid copying a full queue per frame.
        long oldNextId = old.nextId;
        long oldDropped = old.dropped;
        State candidate = old;
        candidate.nextId = input.readLong();
        candidate.dropped = input.readLong();
        long through = input.readLong();
        long overflow = input.readLong();
        int count = input.readInt();
        if (candidate.nextId < oldNextId || candidate.dropped < oldDropped || through < 0
                || through >= oldNextId || overflow < 0 || overflow >= oldNextId
                || count < 0 || count > maxLines) throw new IOException("Invalid spool transaction metadata");
        while (!candidate.records.isEmpty() && candidate.records.get(0).id <= through) candidate.remove(0);
        if (overflow != 0) {
            boolean removed = false;
            for (int i = 0; i < candidate.records.size(); i++) {
                Record record = candidate.records.get(i);
                if (record.id == overflow && record.overflow) { candidate.remove(i); removed = true; break; }
            }
            if (!removed) throw new IOException("Invalid spool overflow removal");
        }
        long previous = oldNextId - 1;
        for (int i = 0; i < count; i++) {
            Record record = readRecord(input);
            if (record.id <= previous || record.id >= candidate.nextId) throw new IOException("Invalid appended spool ID");
            candidate.add(record);
            previous = record.id;
        }
        if (input.available() != 0) throw new IOException("Trailing spool transaction data");
        validateState(candidate);
        if (candidate.dropped > oldDropped && !hasOverflow(candidate)) throw new IOException("Missing overflow notice");
        return candidate;
    }

    private static boolean hasOverflow(State candidate) {
        for (Record record : candidate.records) if (record.overflow) return true;
        return false;
    }

    private void validateState(State loaded) throws IOException {
        if (loaded.records.size() > maxLines || loaded.fileBytes() > maxBytes) throw new IOException("Spool bounds exceeded");
        boolean foundOverflow = false;
        long previous = 0;
        for (Record record : loaded.records) {
            if (record.id <= previous || record.id >= loaded.nextId) throw new IOException("Invalid spool record order");
            if (record.overflow) {
                String decoded = new String(record.text, UTF8);
                int space = decoded.indexOf(' ');
                if (foundOverflow || loaded.dropped == 0 || space < 1
                        || !decoded.substring(0, space).matches("-?[0-9]{1,19}")
                        || !decoded.substring(space).equals(" spool overflow dropped=" + loaded.dropped + " policy=oldest\n")) {
                    throw new IOException("Invalid overflow record");
                }
                foundOverflow = true;
            }
            previous = record.id;
        }
    }

    private static Record readRecord(DataInputStream input) throws IOException {
        long id = input.readLong();
        int type = input.readUnsignedByte();
        int size = input.readInt();
        if (id < 1 || type > 1 || size < 2 || size > MAX_LINE_BYTES + 1 || size > input.available()) {
            throw new IOException("Invalid spool record");
        }
        byte[] text = new byte[size];
        input.readFully(text);
        try {
            String decoded = UTF8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(text)).toString();
            if (!decoded.endsWith("\n")) throw new IOException("Unterminated spool line");
            encodeLine(decoded.substring(0, decoded.length() - 1));
        } catch (CharacterCodingException e) { throw new IOException("Invalid spool UTF-8", e); }
        catch (IllegalArgumentException e) { throw new IOException("Invalid spool text", e); }
        return new Record(id, type == 1, text);
    }

    public static final class Batch {
        public final Token token;
        public final String text;
        public final int lineCount;
        public final int byteCount;
        private Batch(Token token, String text, int lineCount, int byteCount) {
            this.token = token;
            this.text = text;
            this.lineCount = lineCount;
            this.byteCount = byteCount;
        }
    }

    public static final class Token {
        private final Object owner;
        private final long lastId;
        private Token(Object owner, long lastId) { this.owner = owner; this.lastId = lastId; }
    }

    private static final class Record {
        final long id;
        final boolean overflow;
        final byte[] text;
        Record(long id, boolean overflow, byte[] text) { this.id = id; this.overflow = overflow; this.text = text; }
    }

    private static final class State {
        long nextId = 1;
        long dropped;
        int textBytes;
        final List<Record> records;
        State() { records = new ArrayList<Record>(); }
        State(State old) {
            nextId = old.nextId;
            dropped = old.dropped;
            textBytes = old.textBytes;
            records = new ArrayList<Record>(old.records);
        }
        void add(Record record) { records.add(record); textBytes += record.text.length; }
        void remove(int index) { textBytes -= records.remove(index).text.length; }
        int fileBytes() { return FILE_OVERHEAD + records.size() * RECORD_OVERHEAD + textBytes; }
    }
}
