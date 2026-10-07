// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

import android.annotation.TargetApi;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.bluetooth.le.BluetoothLeScanner;
import android.content.Context;
import android.os.Build;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** A read-only capability diagnostic. It never starts discovery, scanning, or advertising. */
public final class ProbeActivity extends Activity {
    private TextView report;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        column.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText(R.string.title);
        column.addView(title);
        Button refresh = new Button(this);
        refresh.setText(R.string.refresh);
        column.addView(refresh);
        report = new TextView(this);
        report.setTextIsSelectable(true);
        column.addView(report, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(column);
        setContentView(scroll);
        refresh.setOnClickListener(view -> refreshReport());
        refreshReport();
    }

    private void refreshReport() {
        StringBuilder out = new StringBuilder();
        out.append("source=org.androidbody.bleprobe/ProbeActivity\n")
                .append("sdk_int=").append(Build.VERSION.SDK_INT).append('\n')
                .append("sampled_at_utc=").append(timestampUtc()).append('\n');
        BluetoothAdapter adapter = null;
        String adapterLookupError = null;
        try {
            BluetoothManager manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
            if (manager == null) {
                out.append("adapter=unavailable: BluetoothManager service absent\n");
            } else {
                adapter = manager.getAdapter();
                out.append("adapter=").append(adapter == null ? "absent" : "present").append('\n');
            }
        } catch (RuntimeException error) {
            adapterLookupError = error.getClass().getSimpleName();
            out.append("adapter=error:").append(adapterLookupError).append('\n');
        }
        if (adapter != null) {
            final BluetoothAdapter observedAdapter = adapter;
            ProbeReport.appendQuery(out, "adapter_state", () -> stateName(observedAdapter.getState()));
            if (Build.VERSION.SDK_INT >= 21) {
                Api21.append(out, observedAdapter);
            } else {
                out.append("le_scanner=not_tested: API<21\n")
                        .append("le_advertiser=not_tested: API<21\n")
                        .append("multiple_advertisement_supported=not_tested: API<21\n");
            }
        } else if (adapterLookupError != null) {
            out.append("adapter_state=error:not queried after adapter lookup failure\n")
                    .append("le_scanner=error:not queried after adapter lookup failure\n")
                    .append("le_advertiser=error:not queried after adapter lookup failure\n")
                    .append("multiple_advertisement_supported=error:not queried after adapter lookup failure\n");
        } else {
            out.append("adapter_state=not_tested: no adapter\n")
                    .append("le_scanner=not_tested: no adapter\n")
                    .append("le_advertiser=not_tested: no adapter\n")
                    .append("multiple_advertisement_supported=not_tested: no adapter\n");
        }
        out.append("limits=capability API only; no scan, discovery, advertisement, toggle, identities, or RF-success claim\n");
        report.setText(out.toString());
    }

    /** Keeps API21-only Bluetooth classes out of the API18 Activity verifier path. */
    @TargetApi(21)
    private static final class Api21 {
        static void append(StringBuilder out, BluetoothAdapter adapter) {
            ProbeReport.appendQuery(out, "le_scanner", () -> {
                BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
                return scanner == null ? "null (conditionally unavailable; inspect adapter state)" : "object available";
            });
            ProbeReport.appendQuery(out, "le_advertiser", () -> {
                BluetoothLeAdvertiser advertiser = adapter.getBluetoothLeAdvertiser();
                return advertiser == null ? "null (conditionally unavailable; inspect adapter state)" : "object available";
            });
            ProbeReport.appendQuery(out, "multiple_advertisement_supported", () ->
                    Boolean.toString(adapter.isMultipleAdvertisementSupported()));
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
