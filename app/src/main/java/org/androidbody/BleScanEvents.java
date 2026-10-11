// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/**
 * Event text and bounds for the bounded BLE scan recorder.
 *
 * Android-free on purpose: the BleScan wrapper around the platform scanner is
 * not JVM-loadable (no android.jar on the unit-test classpath), so the pure
 * contract — beacon allowlist, duty cycle and event formats — lives here where
 * the deterministic tests can load it.
 */
final class BleScanEvents {
    static final String BEACON_NAME = "MISHE-BEACON";
    static final long SCAN_WINDOW_MS = 60000L;
    static final long GAP_MS = 60000L;

    private BleScanEvents() { }

    static String sighting(String name, int rssi) {
        return BEACON_NAME.equals(name) ? "ble_sighting name=" + name + " rssi=" + rssi : null;
    }

    static String startEvent() {
        return "ble_scan start beacon=" + BEACON_NAME + " window_ms=" + SCAN_WINDOW_MS + " gap_ms=" + GAP_MS;
    }

    static String stopEvent() { return "ble_scan stop reason=session_end"; }

    static String errorEvent(Exception e) {
        return "ble_scan error reason=" + e.getClass().getSimpleName();
    }

    static String unavailableEvent(String reason) {
        return "ble_scan unavailable reason=" + reason;
    }
}
