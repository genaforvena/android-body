// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/** Zero-dependency JVM tests for the BLE scan event contract: run gradle :app:testBleScanEvents. */
public final class BleScanEventsTest {
    private static int count;
    private static void equal(Object expected, Object actual) {
        count++;
        if (expected == null ? actual != null : !expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    public static void main(String[] ignored) {
        equal("ble_sighting name=MISHE-BEACON rssi=-62", BleScanEvents.sighting("MISHE-BEACON", -62));
        equal("ble_sighting name=MISHE-BEACON rssi=0", BleScanEvents.sighting("MISHE-BEACON", 0));
        equal(null, BleScanEvents.sighting("other-device", -50));
        equal(null, BleScanEvents.sighting(null, -50));
        equal(null, BleScanEvents.sighting("mishe-beacon", -50));
        equal("ble_scan start beacon=MISHE-BEACON window_ms=60000 gap_ms=60000", BleScanEvents.startEvent());
        equal("ble_scan stop reason=session_end", BleScanEvents.stopEvent());
        equal("ble_scan error reason=SecurityException", BleScanEvents.errorEvent(new SecurityException()));
        equal("ble_scan unavailable reason=adapter_off", BleScanEvents.unavailableEvent("adapter_off"));
        count++;
        if (BleScanEvents.SCAN_WINDOW_MS > 60000L) throw new AssertionError("scan window exceeds programme bound: " + BleScanEvents.SCAN_WINDOW_MS);
        count++;
        if (BleScanEvents.GAP_MS < 60000L) throw new AssertionError("gap below programme bound: " + BleScanEvents.GAP_MS);
        System.out.println("BleScanEvents: " + count + " assertions passed");
    }
}
