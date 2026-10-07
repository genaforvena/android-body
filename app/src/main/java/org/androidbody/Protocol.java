// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/** Platform-independent, deliberately small wire boundary. No command evaluation. */
public final class Protocol {
    public static final int MAX_BODY_BYTES = 65536;
    public static final int MAX_WIRE_LINE_BYTES = 1024;
    public static final int MAX_BATCH = 128;
    public static final long MAX_ID = 9007199254740991L;
    public static final int MAX_VIBRATE_MS = 2000;
    public static final Charset UTF8 = Charset.forName("UTF-8");
    private static final Pattern SECRET = Pattern.compile("[A-Za-z0-9._~-]{32,256}");
    private static final Pattern PATH = Pattern.compile("/node/[a-z0-9][a-z0-9_-]{0,63}/?");
    private Protocol() { }

    public static String endpoint(String value, boolean allowHttp) {
        if (value == null || value.length() > 2048) throw new IllegalArgumentException("Invalid endpoint");
        try {
            URI uri = new URI(value.trim());
            String scheme = uri.getScheme();
            if (!"https".equals(scheme) && !(allowHttp && "http".equals(scheme))) {
                throw new IllegalArgumentException("Use HTTPS, or explicitly allow insecure HTTP");
            }
            if (uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null
                    || uri.getRawFragment() != null || uri.getPort() == 0 || uri.getPort() > 65535
                    || !PATH.matcher(uri.getRawPath()).matches()) {
                throw new IllegalArgumentException("Endpoint must be https://host/node/name (no query, credentials or fragment)");
            }
            String normalized = uri.toASCIIString();
            return normalized.endsWith("/") ? normalized.substring(0, normalized.length() - 1) : normalized;
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("Invalid endpoint");
        }
    }

    public static String secret(String value) {
        if (value == null || !SECRET.matcher(value).matches()) {
            throw new IllegalArgumentException("Secret must be 32–256 URL-safe letters, digits, ., _, ~ or -");
        }
        return value;
    }

    public static String node(String endpoint) { return endpoint.substring(endpoint.lastIndexOf('/') + 1); }

    public static String decode(byte[] bytes) throws IllegalArgumentException {
        if (bytes.length > MAX_BODY_BYTES) throw new IllegalArgumentException("Response too large");
        try {
            return UTF8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException e) { throw new IllegalArgumentException("Invalid UTF-8"); }
    }

    public static List<Action> actions(String body, long cursor) {
        if (cursor < 0 || cursor > MAX_ID || body.getBytes(UTF8).length > MAX_BODY_BYTES) {
            throw new IllegalArgumentException("Invalid cursor or response size");
        }
        List<Action> result = new ArrayList<Action>();
        if (body.isEmpty()) return result;
        String[] lines = body.split("\n", -1);
        long previous = cursor;
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (i == lines.length - 1 && line.isEmpty()) break;
            if (line.endsWith("\r")) line = line.substring(0, line.length() - 1);
            if (line.isEmpty() || line.getBytes(UTF8).length > MAX_WIRE_LINE_BYTES || result.size() >= MAX_BATCH) {
                throw new IllegalArgumentException("Invalid action line or batch size");
            }
            for (int c = 0; c < line.length(); c++) {
                if (line.charAt(c) < 32 || (line.charAt(c) >= 127 && line.charAt(c) <= 159) || line.charAt(c) == '\u2028' || line.charAt(c) == '\u2029' || line.charAt(c) == '\ufeff') throw new IllegalArgumentException("Control character");
            }
            int separator = line.indexOf(' ');
            if (separator < 1 || separator == line.length() - 1) throw new IllegalArgumentException("Missing action ID or command");
            String idText = line.substring(0, separator);
            if (!idText.matches("[1-9][0-9]{0,15}")) throw new IllegalArgumentException("Invalid action ID");
            long id;
            try { id = Long.parseLong(idText); } catch (NumberFormatException e) { throw new IllegalArgumentException("Invalid action ID"); }
            if (id <= previous || id > MAX_ID) throw new IllegalArgumentException("Action IDs must increase beyond cursor");
            result.add(new Action(id, line.substring(separator + 1)));
            previous = id;
        }
        return result;
    }

    public static void acknowledgment(String body, int expected) {
        String[] lines = body.split("\\n", -1);
        int count = lines.length;
        if (count > 0 && lines[count - 1].isEmpty()) count--;
        if (count != expected || count < 1) throw new IllegalArgumentException("Invalid acknowledgment count");
        long previous = 0;
        for (int i = 0; i < count; i++) {
            if (!lines[i].matches("[1-9][0-9]{0,15}")) throw new IllegalArgumentException("Invalid acknowledgment ID");
            long id = Long.parseLong(lines[i]);
            if (id <= previous || id > MAX_ID) throw new IllegalArgumentException("Invalid acknowledgment order");
            previous = id;
        }
    }

    public static int vibrationDuration(String command) {
        if (!command.matches("vibrate duration=[1-9][0-9]{0,3}")) return -1;
        int duration = Integer.parseInt(command.substring("vibrate duration=".length()));
        return duration <= MAX_VIBRATE_MS ? duration : -1;
    }

    public static String event(String content) { return (System.currentTimeMillis() / 1000L) + " " + content + "\n"; }

    public static final class Action {
        public final long id;
        public final String command;
        public Action(long id, String command) { this.id = id; this.command = command; }
    }
}
