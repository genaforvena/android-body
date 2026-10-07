// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

import android.annotation.TargetApi;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.bluetooth.le.BluetoothLeScanner;
import android.content.Context;
import android.os.Build;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** Builds the single allowlisted, read-only capability report used by UI and instrumentation. */
final class CapabilityReport {
    private CapabilityReport() {}

    static String collect(Context context) {
        StringBuilder out = new StringBuilder();
        out.append("source=org.androidbody.bleprobe/CapabilityReport\n")
                .append("sdk_int=").append(Build.VERSION.SDK_INT).append('\n')
                .append("sampled_at_utc=").append(timestampUtc()).append('\n');
        BluetoothAdapter adapter = null;
        String adapterLookupError = null;
        try {
            BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
            if (manager == null) out.append("adapter=unavailable: BluetoothManager service absent\n");
            else {
                adapter = manager.getAdapter();
                out.append("adapter=").append(adapter == null ? "absent" : "present").append('\n');
            }
        } catch (RuntimeException error) {
            adapterLookupError = error.getClass().getSimpleName();
            out.append("adapter=error:").append(adapterLookupError).append('\n');
        }
        if (adapter != null) {
            final BluetoothAdapter observed = adapter;
            ProbeReport.appendQuery(out, "adapter_state", () -> stateName(observed.getState()));
            if (Build.VERSION.SDK_INT >= 21) Api21.append(out, observed);
            else out.append("le_scanner=not_tested: API<21\nle_advertiser=not_tested: API<21\nmultiple_advertisement_supported=not_tested: API<21\n");
        } else if (adapterLookupError != null) {
            out.append("adapter_state=error:not queried after adapter lookup failure\nle_scanner=error:not queried after adapter lookup failure\nle_advertiser=error:not queried after adapter lookup failure\nmultiple_advertisement_supported=error:not queried after adapter lookup failure\n");
        } else {
            out.append("adapter_state=not_tested: no adapter\nle_scanner=not_tested: no adapter\nle_advertiser=not_tested: no adapter\nmultiple_advertisement_supported=not_tested: no adapter\n");
        }
        return out.append("limits=capability API only; no scan, discovery, advertisement, toggle, identities, or RF-success claim\n").toString();
    }

    @TargetApi(21)
    private static final class Api21 {
        static void append(StringBuilder out, BluetoothAdapter adapter) {
            ProbeReport.appendQuery(out, "le_scanner", () -> { BluetoothLeScanner value = adapter.getBluetoothLeScanner(); return value == null ? "null (conditionally unavailable; inspect adapter state)" : "object available"; });
            ProbeReport.appendQuery(out, "le_advertiser", () -> { BluetoothLeAdvertiser value = adapter.getBluetoothLeAdvertiser(); return value == null ? "null (conditionally unavailable; inspect adapter state)" : "object available"; });
            ProbeReport.appendQuery(out, "multiple_advertisement_supported", () -> Boolean.toString(adapter.isMultipleAdvertisementSupported()));
        }
    }
    private static String stateName(int state) {
        switch (state) {
            case BluetoothAdapter.STATE_OFF: return "OFF";
            case BluetoothAdapter.STATE_TURNING_ON: return "TURNING_ON";
            case BluetoothAdapter.STATE_ON: return "ON";
            case BluetoothAdapter.STATE_TURNING_OFF: return "TURNING_OFF";
            default: return "unknown(" + state + ")";
        }
    }
    private static String timestampUtc() {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date());
    }
}
