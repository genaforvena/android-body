// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

/** Formats one caller-visible API query without losing its key on failure. */
final class ProbeReport {
    interface Query { String read(); }

    private ProbeReport() {}

    static void appendQuery(StringBuilder out, String key, Query query) {
        try {
            String value = query.read();
            out.append(key).append('=').append(value).append('\n');
        } catch (RuntimeException error) {
            out.append(key).append("=error:").append(error.getClass().getSimpleName()).append('\n');
        }
    }
}
