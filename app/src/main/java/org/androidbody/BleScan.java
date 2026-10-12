// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Bounded BLE scan-sighting recorder for the allowlisted experiment beacon.
 *
 * While a session is active, scans run in BleScanEvents.SCAN_WINDOW_MS windows
 * separated by BleScanEvents.GAP_MS idle gaps (programme duty cycle: windows &lt;= 60 s, gaps &gt;= 60 s).
 * Only the allowlisted beacon name is recorded; each matching result becomes one
 * `ble_sighting name= rssi=` event in the spool. Sightings are scanner-visible
 * evidence, not presence proof. The adapter is never enabled or disabled here;
 * if it is off or absent, the scanner reports unavailable once and stops for
 * the session. On API 31+ a missing BLUETOOTH_SCAN runtime permission surfaces
 * as an error event, not a crash. Every stop path stops the scan and quits the
 * worker thread; a terminal start failure is reported and also ends the loop.
 */
final class BleScan {
    interface Sink {
        void enqueue(String event) throws IOException;
    }

    // API21-30 scanning is covered by the declared BLUETOOTH normal permission
    // (maxSdkVersion=30). API31+ would require runtime BLUETOOTH_SCAN/BLUETOOTH_CONNECT,
    // which this app does not request: a missing permission surfaces as a caught
    // SecurityException and an honest error event, never a crash.
    @android.annotation.TargetApi(21)
    @android.annotation.SuppressLint("MissingPermission")
    private final class Callback extends ScanCallback {
        private android.bluetooth.le.BluetoothLeScanner scanner;

        @Override public void onScanResult(int callbackType, ScanResult result) {
            record(result.getDevice().getName(), result.getRssi());
        }
        @Override public void onScanFailed(int errorCode) {
            error("scan_failed code=" + errorCode);
        }
    }

    private final Handler handler;
    private final AtomicBoolean running = new AtomicBoolean();
    private volatile boolean stopped;
    private Sink sink;
    private Callback callback;
    private final CountDownLatch finished = new CountDownLatch(1);

    BleScan() {
        HandlerThread thread = new HandlerThread("body-ble-scan");
        thread.start();
        handler = new Handler(thread.getLooper());
    }

    void start(Sink sink) {
        this.sink = sink;
        handler.post(new Runnable() { @Override public void run() { loop(); } });
    }

    void stop() {
        stopped = true;
        handler.post(new Runnable() { @Override public void run() { stopScan(); } });
        handler.getLooper().quitSafely();
        try { finished.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    private void loop() {
        if (!running.compareAndSet(false, true)) return;
        try {
            if (Build.VERSION.SDK_INT < 21) {
                enqueue(BleScanEvents.unavailableEvent("api<21"));
                return;
            }
            enqueue(BleScanEvents.startEvent());
            while (!stopped) {
                if (!window()) break;
                sleep(BleScanEvents.GAP_MS);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (IOException | IllegalStateException e) {
            // Spool unusable; the sampler path fails the session. Stop scanning.
        } finally {
            running.set(false);
            if (stopped) {
                try { enqueue(BleScanEvents.stopEvent()); } catch (IOException | IllegalStateException e) { /* spool closing */ }
            }
            finished.countDown();
        }
    }

    private boolean window() throws InterruptedException, IOException {
        if (!startScan()) return false;
        sleep(BleScanEvents.SCAN_WINDOW_MS);
        stopScan();
        return true;
    }

    @android.annotation.TargetApi(21)
    @android.annotation.SuppressLint("MissingPermission")
    private boolean startScan() throws IOException {
        BluetoothAdapter adapter;
        try { adapter = BluetoothAdapter.getDefaultAdapter(); }
        catch (RuntimeException e) { enqueue(BleScanEvents.errorEvent(e)); return false; }
        if (adapter == null) { enqueue(BleScanEvents.unavailableEvent("adapter_unavailable")); return false; }
        if (!adapter.isEnabled()) { enqueue(BleScanEvents.unavailableEvent("adapter_off")); return false; }
        callback = new Callback();
        try {
            callback.scanner = adapter.getBluetoothLeScanner();
            if (callback.scanner == null) { enqueue(BleScanEvents.unavailableEvent("scanner_null")); return false; }
            List<ScanFilter> filters = new ArrayList<ScanFilter>();
            filters.add(new ScanFilter.Builder().setDeviceName(BleScanEvents.BEACON_NAME).build());
            callback.scanner.startScan(filters, new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER).build(), callback);
            return true;
        } catch (RuntimeException e) {
            enqueue(BleScanEvents.errorEvent(e));
            return false;
        }
    }

    @android.annotation.TargetApi(21)
    @android.annotation.SuppressLint("MissingPermission")
    private void stopScan() {
        Callback active = callback;
        if (active == null || active.scanner == null) return;
        try { active.scanner.stopScan(active); }
        catch (RuntimeException e) { /* best effort */ }
    }

    private void record(String name, int rssi) {
        String event = BleScanEvents.sighting(name, rssi);
        if (event == null) return;
        try { enqueue(event); }
        catch (IOException | IllegalStateException e) { /* spool unusable; loop exits via sampler failure */ }
    }

    private void error(String reason) {
        try { enqueue("ble_scan error reason=" + reason); }
        catch (IOException | IllegalStateException e) { /* spool unusable; loop exits via sampler failure */ }
    }

    private void enqueue(String event) throws IOException {
        Sink target = sink;
        if (target != null) target.enqueue(Protocol.event(event));
    }

    private void sleep(long millis) throws InterruptedException {
        long deadline = System.currentTimeMillis() + millis;
        while (!stopped) {
            long remaining = deadline - System.currentTimeMillis();
            if (remaining <= 0) return;
            Thread.sleep(Math.min(remaining, 1000L));
        }
    }

}
