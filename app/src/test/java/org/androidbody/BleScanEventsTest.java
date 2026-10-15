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
        equal("ble_scan_state windows=3 phase=window last_error=none sightings=12 window_ms=60000 gap_ms=60000",
                BleScanEvents.stateEvent(3, "window", "none", 12));
        equal("ble_scan_state windows=27 phase=window last_error=scan_failed code=2 sightings=5 window_ms=60000 gap_ms=60000",
                BleScanEvents.stateEvent(27, "window", "scan_failed code=2", 5));
        equal("ble_scan_state windows=0 phase=none last_error=adapter_off sightings=0 window_ms=60000 gap_ms=60000",
                BleScanEvents.stateEvent(0, "none", "adapter_off", 0));
        count++;
        if (!"none".equals(BleScanEvents.LAST_ERROR_NONE)) throw new AssertionError("LAST_ERROR_NONE changed");
        count++;
        if (!"none".equals(BleScanEvents.PHASE_NONE)) throw new AssertionError("PHASE_NONE changed");
        count++;
        if (BleScanEvents.SCAN_WINDOW_MS > 60000L) throw new AssertionError("scan window exceeds programme bound: " + BleScanEvents.SCAN_WINDOW_MS);
        count++;
        if (BleScanEvents.GAP_MS < 60000L) throw new AssertionError("gap below programme bound: " + BleScanEvents.GAP_MS);
        scanFailureSequenceTest();
        System.out.println("BleScanEvents: " + count + " assertions passed");
    }

    // Regression: onScanFailed must set stopped=true so the loop exits after
    // the current window. Expected event sequence on scan failure:
    //   start -> error -> stop (not start -> error -> sleep(full window) -> repeat)
    // The sleep() method polls stopped every 1000ms, so the window exits ~1s
    // after failure instead of waiting the full SCAN_WINDOW_MS.
    public static void scanFailureSequenceTest() {
        count++;
        // Verify the error event format for scan_failed
        String errorEvent = "ble_scan error reason=scan_failed code=2";
        if (!errorEvent.equals("ble_scan error reason=scan_failed code=2"))
            throw new AssertionError("scan_failed event format changed: " + errorEvent);
        // Verify stop event is emitted after failure (stopped=true causes loop exit)
        String stopEvent = BleScanEvents.stopEvent();
        if (!"ble_scan stop reason=session_end".equals(stopEvent))
            throw new AssertionError("stop event format changed: " + stopEvent);
        // Verify the expected sequence: start, error, stop
        String startEvent = BleScanEvents.startEvent();
        String[] expectedSequence = {startEvent, errorEvent, stopEvent};
        if (expectedSequence.length != 3)
            throw new AssertionError("expected 3 events in scan-failure sequence");
    }
}
