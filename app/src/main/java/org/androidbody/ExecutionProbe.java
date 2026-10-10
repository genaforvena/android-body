// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;

/** Bounded, read-only observation of the calling process identity and Linux supplementary groups. */
public final class ExecutionProbe {
    private static final int MAX_STATUS_BYTES = 4096;
    private static final Charset ASCII = Charset.forName("US-ASCII");
    private ExecutionProbe() { }

    public static String observation(int uid, InputStream status) throws IOException {
        if (uid < 0 || status == null) throw new IllegalArgumentException("Invalid identity probe input");
        byte[] bytes = new byte[MAX_STATUS_BYTES + 1];
        int size = 0;
        while (size < bytes.length) {
            int count = status.read(bytes, size, bytes.length - size);
            if (count < 0) break;
            if (count == 0) throw new IOException("proc status read made no progress");
            size += count;
        }
        if (size > MAX_STATUS_BYTES) throw new IOException("proc status exceeds probe bound");
        String text = new String(bytes, 0, size, ASCII);
        String groups = null;
        for (String line : text.split("\\n")) {
            if (!line.startsWith("Groups:\t")) continue;
            groups = line.substring("Groups:\t".length()).trim();
            break;
        }
        if (groups == null || groups.length() > 256 || !groups.matches("[0-9 ]*")) {
            throw new IOException("proc supplementary groups unavailable or invalid");
        }
        return "probe identity uid=" + uid + " groups=" + (groups.isEmpty() ? "none" : groups);
    }
}
