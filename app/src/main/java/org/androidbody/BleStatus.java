// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.bluetooth.BluetoothAdapter;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

/** Read-only BLE API snapshot; getter outcomes are not radio or RF evidence. */
final class BleStatus {
    private BleStatus() { }

    static String snapshot(Context context) {
        String feature;
        try {
            feature = context.getPackageManager().hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)
                    ? "present" : "absent";
        } catch (RuntimeException e) {
            feature = "query_error";
        }
        if (Build.VERSION.SDK_INT < 21) {
            return "ble_status source=androidbody_bluetooth_api api=" + Build.VERSION.SDK_INT
                    + " api_surface=platform_sdk feature_ble=" + feature
                    + " adapter=unavailable scanner_api=unavailable advertiser_api=unavailable"
                    + " scanner_getter=unavailable advertiser_getter=unavailable"
                    + " advertiser_supported=unavailable";
        }

        BluetoothAdapter adapter;
        try {
            adapter = BluetoothAdapter.getDefaultAdapter();
        } catch (RuntimeException e) {
            return record(feature, "error", "error", "error", "error", "error", "error");
        }
        if (adapter == null) {
            return record(feature, "unavailable", "present", "present", "unavailable",
                    "unavailable", "unavailable");
        }
        String state;
        try {
            int adapterState = adapter.getState();
            state = adapterState == BluetoothAdapter.STATE_ON ? "enabled"
                    : adapterState == BluetoothAdapter.STATE_OFF ? "disabled" : "unavailable";
        } catch (RuntimeException e) {
            state = "error";
        }
        String advertiserSupported;
        try {
            advertiserSupported = adapter.isMultipleAdvertisementSupported() ? "supported" : "unsupported";
        } catch (RuntimeException e) {
            advertiserSupported = "error";
        }
        String scannerGetter = getter(adapter, true);
        String advertiserGetter = getter(adapter, false);
        return record(feature, state, "present", "present", scannerGetter, advertiserGetter,
                advertiserSupported);
    }
    @android.annotation.TargetApi(21)
    private static String getter(BluetoothAdapter adapter, boolean scanner) {
        try {
            return (scanner ? adapter.getBluetoothLeScanner() : adapter.getBluetoothLeAdvertiser()) == null
                    ? "null" : "returned";
        } catch (RuntimeException e) {
            return "error";
        }
    }


    private static String record(String feature, String adapter, String scanner,
                                 String advertiser, String scannerGetter,
                                 String advertiserGetter, String support) {
        return "ble_status source=androidbody_bluetooth_api api=" + Build.VERSION.SDK_INT
                + " api_surface=platform_sdk feature_ble=" + feature
                + " adapter=" + adapter + " scanner_api=" + scanner
                + " advertiser_api=" + advertiser + " scanner_getter=" + scannerGetter
                + " advertiser_getter=" + advertiserGetter
                + " advertiser_supported=" + support;
}

}
