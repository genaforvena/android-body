// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Strict consumer-side classification; only a bounded complete report for the current run is accepted. */
final class ProbeResult {
    private static final String[] REQUIRED = {"source", "sdk_int", "sampled_at_utc", "adapter", "adapter_state",
            "le_scanner", "le_advertiser", "multiple_advertisement_supported", "limits"};
    private ProbeResult() {}

    static String classify(String expectedRun, String returnedRun, String status, String report, long ageMillis) {
        if (!validRunId(expectedRun) || returnedRun == null || status == null) return "missing";
        if (!expectedRun.equals(returnedRun)) return "mismatched_run";
        if (ageMillis < 0 || ageMillis > 60_000) return "stale";
        if (!"complete".equals(status) || report == null || report.length() == 0 || report.length() > 8192) return "error";
        Set<String> keys = new HashSet<>();
        Map<String, String> values = new HashMap<>();
        String[] lines = report.split("\\n", -1);
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (i == lines.length - 1 && line.length() == 0) continue;
            int separator = line.indexOf('=');
            if (separator <= 0 || line.indexOf('\r') >= 0) return "error";
            String key = line.substring(0, separator);
            String value = line.substring(separator + 1);
            if (!keys.add(key) || !isRequired(key) || value.trim().length() == 0) return "error";
            values.put(key, value);
        }
        for (String key : REQUIRED) if (!keys.contains(key)) return "error";
        if (!"org.androidbody.bleprobe/CapabilityReport".equals(values.get("source"))
                || !values.get("sdk_int").matches("[1-9][0-9]{0,2}")
                || !values.get("sampled_at_utc").matches(
                        "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z")) {
            return "error";
        }
        return "complete";
    }

    private static boolean validRunId(String runId) {
        if (runId == null || runId.length() == 0 || runId.length() > 64) return false;
        for (int i = 0; i < runId.length(); i++) {
            char c = runId.charAt(i);
            if (!(c >= 'A' && c <= 'Z') && !(c >= 'a' && c <= 'z')
                    && !(c >= '0' && c <= '9') && c != '_' && c != '-') return false;
        }
        return true;
    }

    private static boolean isRequired(String key) {
        for (String required : REQUIRED) if (required.equals(key)) return true;
        return false;
    }
}
