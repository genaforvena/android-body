// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.Charset;
import java.util.List;

/** Zero-dependency JVM tests: run tools/test-protocol.sh. */
public final class ProtocolTest {
    private static int count;
    private static void equal(Object expected, Object actual) {
        count++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void rejects(Runnable block) {
        count++;
        try { block.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    private static void probeRejects(final int uid, final java.io.InputStream status, Class<? extends Exception> type) {
        count++;
        try { ExecutionProbe.observation(uid, status); }
        catch (Exception e) { if (type.isInstance(e)) return; throw new AssertionError(e); }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
    private static void probeRejects(final int uid, final byte[] status, Class<? extends Exception> type) {
        probeRejects(uid, new ByteArrayInputStream(status), type);
    }
    private static void badBody(final String body) { rejects(new Runnable() { public void run() { Protocol.actions(body, 0); } }); }
    private static void badEndpoint(final String endpoint) { rejects(new Runnable() { public void run() { Protocol.endpoint(endpoint, true); } }); }
    public static void main(String[] ignored) {
        equal("wifi_link_rssi_dbm=-61 source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(true, -61, 123));
        equal("wifi_link_rssi_dbm unavailable reason=disconnected source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(false, -61, 123));
        equal("wifi_link_rssi_dbm unavailable reason=invalid_rssi source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(true, -127, 123));
        equal("wifi_link_rssi_dbm unavailable reason=invalid_rssi source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(true, 0, 123));
        equal("wifi_link_rssi_dbm unavailable reason=invalid_rssi source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(true, 1, 123));
        equal("wifi_link_rssi_dbm unavailable reason=invalid_rssi source=androidbody_wifi_api observed_at=123",
                WifiRssi.event(true, Integer.MAX_VALUE, 123));
        equal("wifi_link_rssi_dbm unavailable reason=permission_denied source=androidbody_wifi_api observed_at=123",
                WifiRssi.unavailable("permission_denied", 123));
        equal("https://example.org/node/note3", Protocol.endpoint(" https://example.org/node/note3/ ", false));
        equal("http://192.168.1.2:8080/node/xiaomi", Protocol.endpoint("http://192.168.1.2:8080/node/xiaomi", true));
        equal("https://[::1]/node/a", Protocol.endpoint("https://[::1]/node/a", false));
        badEndpoint("file:///node/a"); badEndpoint("https://user:secret@example.org/node/a");
        badEndpoint("https://example.org/node/a?secret=x"); badEndpoint("https://example.org/node/a#x");
        badEndpoint("https://example.org/node/../a"); badEndpoint("https://example.org/node/a%2Fb");
        badEndpoint("https://example.org/node/Note3"); badEndpoint("https://example.org/node/_name");
        badEndpoint("https://example.org:0/node/a"); badEndpoint("https://example.org:99999/node/a");
        rejects(new Runnable() { public void run() { Protocol.endpoint("http://example.org/node/a", false); } });
        equal("abcdefghijklmnopqrstuvwxyz_12345", Protocol.secret("abcdefghijklmnopqrstuvwxyz_12345"));
        rejects(new Runnable() { public void run() { Protocol.secret("short"); } });
        rejects(new Runnable() { public void run() { Protocol.secret("abcdefghijklmnopqrstuvwxyz_12345\r\nInjected: true"); } });
        rejects(new Runnable() { public void run() { Protocol.secret("abcdefghijklmnopqrstuvwxyz_12345="); } });
        List<Protocol.Action> actions = Protocol.actions("1 vibrate duration=200\n3 unsupported\n", 0);
        equal(2, actions.size()); equal(1L, actions.get(0).id); equal("unsupported", actions.get(1).command);
        equal(0, Protocol.actions("", 0).size());
        equal(1, Protocol.actions("1 vibrate duration=1\r\n", 0).size());
        equal(1, Protocol.actions("9007199254740991 vibrate duration=1", 0).size());
        badBody("9007199254740992 vibrate duration=1"); badBody("0 vibrate duration=1");
        badBody("01 vibrate duration=1"); badBody("-1 vibrate duration=1"); badBody("1"); badBody("1 ");
        badBody("1 x\u0080"); badBody("1 x\u009f"); badBody("1 x\u2028"); badBody("1 x\u2029"); badBody("1 x\ufeff");
        badBody("1 x\n1 y"); badBody("2 x\n1 y"); badBody("1 x\n\n2 y"); badBody("\n");
        badBody("1 vibrate\tduration=2"); badBody("1 x\u0000"); badBody("1 x\u007f");
        rejects(new Runnable() { public void run() { Protocol.actions("5 vibrate duration=1", 5); } });
        equal(1, Protocol.vibrationDuration("vibrate duration=1"));
        equal(2000, Protocol.vibrationDuration("vibrate duration=2000"));
        for (String command : new String[] {"vibrate duration=0", "vibrate duration=-1", "vibrate duration=2001", "vibrate duration=99999999999", "vibrate duration=0200", "vibrate duration=2 extra=1", "vibrate duration=2; reboot", "vibrate", "torch on", " vibrate duration=2"}) equal(-1, Protocol.vibrationDuration(command));
        StringBuilder many = new StringBuilder();
        for (int i = 1; i <= 128; i++) many.append(i).append(" vibrate duration=1\n");
        equal(128, Protocol.actions(many.toString(), 0).size());
        badBody(many.append("129 vibrate duration=1\n").toString());
        StringBuilder longLine = new StringBuilder("1 ");
        for (int i = 0; i < 1022; i++) longLine.append('x');
        equal(1, Protocol.actions(longLine.toString(), 0).size()); badBody(longLine.append('x').toString());
        rejects(new Runnable() { public void run() { Protocol.decode(new byte[] {(byte) 0xc3, 0x28}); } });
        rejects(new Runnable() { public void run() { Protocol.decode(new byte[65537]); } });
        equal("hello", Protocol.decode("hello".getBytes(Protocol.UTF8)));
        equal("note3", Protocol.node("https://example.org/node/note3"));
        Protocol.acknowledgment("12\n13\n", 2);
        Protocol.acknowledgment("12", 1);
        rejects(new Runnable() { public void run() { Protocol.acknowledgment("12\n", 2); } });
        rejects(new Runnable() { public void run() { Protocol.acknowledgment("12\n12\n", 2); } });
        rejects(new Runnable() { public void run() { Protocol.acknowledgment("0\n", 1); } });
        rejects(new Runnable() { public void run() { Protocol.acknowledgment("01\n", 1); } });
        rejects(new Runnable() { public void run() { Protocol.acknowledgment("9007199254740992\n", 1); } });
        try {
            equal("probe identity uid=10452 groups=1003 3003", ExecutionProbe.observation(10452,
                    new ByteArrayInputStream("Name:\\tapp\\nGroups:\\t1003 3003\\n".replace("\\t", "\t").replace("\\n", "\n").getBytes(Charset.forName("US-ASCII")))));
        } catch (IOException e) { throw new AssertionError(e); }
        try {
            ExecutionProbe.observation(10452, new ByteArrayInputStream("Name:\\tapp\\n".replace("\\t", "\t").replace("\\n", "\n").getBytes(Charset.forName("US-ASCII"))));
            throw new AssertionError("Missing Groups row accepted");
        } catch (IOException expected) { count++; }
        probeRejects(1, "Name:\\tapp\\nGroups:\\t1 x\\n".replace("\\t", "\t").replace("\\n", "\n").getBytes(Charset.forName("US-ASCII")), IOException.class);
        byte[] oversized = new byte[4097];
        java.util.Arrays.fill(oversized, (byte) 'x');
        probeRejects(1, oversized, IOException.class);
        probeRejects(1, new ByteArrayInputStream(new byte[1]) {
            @Override public synchronized int read(byte[] target, int offset, int length) { return 0; }
        }, IOException.class);
        probeRejects(-1, new byte[0], IllegalArgumentException.class);
        System.out.println("Protocol: " + count + " assertions passed");
    }
}
