// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/** Wire representation for current-link RSSI; deliberately excludes network identity. */
final class WifiRssi {
    private WifiRssi() { }

    static String event(boolean connected, int rssi, long observedAt) {
        if (!connected) return unavailable("disconnected", observedAt);
        if (rssi == -127 || rssi >= 0) return unavailable("invalid_rssi", observedAt);
        return "wifi_link_rssi_dbm=" + rssi
                + " source=androidbody_wifi_api observed_at=" + observedAt;
    }

    static String unavailable(String reason, long observedAt) {
        return "wifi_link_rssi_dbm unavailable reason=" + reason
                + " source=androidbody_wifi_api observed_at=" + observedAt;
    }
}
