// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanRecord;
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
import java.util.concurrent.atomic.AtomicInteger;

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
 * as an error event from the scanner call, not a crash. Every stop path stops
 * the scan and quits the worker thread; a terminal start failure is reported
 * and also ends the loop.
 */
final class BleScan {
    interface Sink {
        void enqueue(String event) throws IOException;
    }

    // API21-30 scanning requires both BLUETOOTH and BLUETOOTH_ADMIN (declared in
    // the manifest). API31+ requires runtime BLUETOOTH_SCAN, which the app
    // requests before starting the session. The sighting name is the scan
    // record's advertised local name -- the same advertisement field the scan
    // filter matches on. BluetoothDevice.getName() would instead need
    // BLUETOOTH_CONNECT for an app targeting S+, and the SecurityException it
    // throws inside this callback would kill the process rather than end the
    // scan, so the app requests no connect-level permission.
    @android.annotation.TargetApi(21)
    private final class Callback extends ScanCallback {
        private android.bluetooth.le.BluetoothLeScanner scanner;

        @Override public void onScanResult(int callbackType, ScanResult result) {
            ScanRecord scanRecord = result.getScanRecord();
            record(scanRecord == null ? null : scanRecord.getDeviceName(), result.getRssi());
        }
        @Override public void onScanFailed(int errorCode) {
            fail("scan_failed code=" + errorCode);
            stopped = true;
        }
    }

    private final Handler handler;
    private final AtomicBoolean running = new AtomicBoolean();
    private volatile boolean stopped;
    private Sink sink;
    private Callback callback;
    private final CountDownLatch finished = new CountDownLatch(1);
    // Per-cycle scan-state row (BleScanEvents.stateEvent), read by the sampler
    // lane every 5 s: windows completed since scan start, current phase, the
    // last error reason (persisted after the failure instant) and the session
    // sighting count. Volatile for cross-thread reads from the sampler.
    private final AtomicInteger windows = new AtomicInteger();
    private final AtomicInteger sightings = new AtomicInteger();
    private volatile String phase = BleScanEvents.PHASE_NONE;
    private volatile String lastError = BleScanEvents.LAST_ERROR_NONE;

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
                unavailable("api<21");
                return;
            }
            enqueue(BleScanEvents.startEvent());
            while (!stopped) {
                phase = BleScanEvents.PHASE_WINDOW;
                if (!window()) break;
                phase = BleScanEvents.PHASE_GAP;
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
        windows.incrementAndGet();
        return true;
    }

    @android.annotation.TargetApi(21)
    @android.annotation.SuppressLint("MissingPermission")
    private boolean startScan() throws IOException {
        BluetoothAdapter adapter;
        try { adapter = BluetoothAdapter.getDefaultAdapter(); }
        catch (RuntimeException e) { enqueue(BleScanEvents.errorEvent(e)); return false; }
        if (adapter == null) { unavailable("adapter_unavailable"); return false; }
        if (!adapter.isEnabled()) { unavailable("adapter_off"); return false; }
        callback = new Callback();
        try {
            callback.scanner = adapter.getBluetoothLeScanner();
            if (callback.scanner == null) { unavailable("scanner_null"); return false; }
            List<ScanFilter> filters = new ArrayList<ScanFilter>();
            filters.add(new ScanFilter.Builder().setDeviceName(BleScanEvents.BEACON_NAME).build());
            callback.scanner.startScan(filters, new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER).build(), callback);
            return true;
        } catch (RuntimeException e) {
            fail(e.getClass().getSimpleName());
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
        sightings.incrementAndGet();
        try { enqueue(event); }
        catch (IOException | IllegalStateException e) { /* spool unusable; loop exits via sampler failure */ }
    }

    private void error(String reason) {
        lastError = reason;
        try { enqueue("ble_scan error reason=" + reason); }
        catch (IOException | IllegalStateException e) { /* spool unusable; loop exits via sampler failure */ }
    }

    private void unavailable(String reason) {
        lastError = reason;
        try { enqueue(BleScanEvents.unavailableEvent(reason)); }
        catch (IOException | IllegalStateException e) { /* spool unusable; loop exits via sampler failure */ }
    }

    private void fail(String reason) {
        lastError = reason;
        error(reason);
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

    /**
     * Per-cycle state row for the sampler lane. phase is "none" when no loop
     * is running (never started or exited); the remaining fields persist after
     * exit so a terminal failure stays visible in later cycles.
     */
    synchronized String state() {
        String currentPhase = running.get() ? phase : BleScanEvents.PHASE_NONE;
        return BleScanEvents.stateEvent(windows.get(), currentPhase, lastError, sightings.get());
    }

}
