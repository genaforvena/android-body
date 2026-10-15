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

    static final String PHASE_WINDOW = "window";
    static final String PHASE_GAP = "gap";
    static final String PHASE_NONE = "none";
    static final String LAST_ERROR_NONE = "none";

    /**
     * Per-cycle scan-state row, emitted by the sampler lane alongside the five
     * per-cycle kinds so bounded retention keeps it with them (the sparse
     * lifecycle events are evicted within hours and cannot answer "is the scan
     * loop alive" for the current session). Quantitative, not a flag: windows
     * completed since scan start, the current loop phase (none = no loop
     * running this session), the last error reason (persisted across cycles,
     * not only at the failure instant), the session sighting count, and the
     * duty-cycle constants so the row stays self-describing after the sparse
     * start event is dropped.
     */
    static String stateEvent(int windows, String phase, String lastError, int sightings) {
        return "ble_scan_state windows=" + windows + " phase=" + phase
                + " last_error=" + lastError + " sightings=" + sightings
                + " window_ms=" + SCAN_WINDOW_MS + " gap_ms=" + GAP_MS;
    }

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
