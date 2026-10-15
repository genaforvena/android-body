// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.BatteryManager;
import android.os.SystemClock;

/** Holds only the latest real samples; snapshots coalesce while the network is offline. */
final class Sensors implements SensorEventListener {
    private final Context context;
    private final SharedPreferences preferences;
    private final SensorManager manager;
    private final WifiManager wifi;
    private final Sensor light;
    private final Sensor acceleration;
    private String lightError = "no_sample";
    private String accelerationError = "no_sample";
    private boolean batteryRegistered;
    private boolean ownerBattery, ownerLight, ownerAcceleration;
    private float lux;
    private float x, y, z;
    private long lightTime;
    private long accelerationTime;
    private long lightSensorTimeNs;
    private long accelerationSensorTimeNs;
    private int lightAccuracy;
    private int accelerationAccuracy;
    private String battery = "battery unavailable reason=no_sample";
    private final BroadcastReceiver batteryReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ignored, Intent intent) { battery(intent); }
    };
    Sensors(Context context, SharedPreferences preferences) {
        this.context = context;
        this.preferences = preferences;
        ownerBattery = preferences.getBoolean("owner_battery", true);
        ownerLight = preferences.getBoolean("owner_light", true);
        ownerAcceleration = preferences.getBoolean("owner_acceleration", true);
        manager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        light = manager == null ? null : manager.getDefaultSensor(Sensor.TYPE_LIGHT);
        acceleration = manager == null ? null : manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
    }
    /** Live-apply hook for owner checkboxes; true when registrations must be rebuilt. */
    boolean ownerFlagsChanged(boolean battery, boolean light, boolean acceleration) {
        boolean changed = battery != ownerBattery || light != ownerLight || acceleration != ownerAcceleration;
        ownerBattery = battery; ownerLight = light; ownerAcceleration = acceleration;
        return changed;
    }
    void start() {
        if (manager != null) {
            if (ownerLight && light != null && !manager.registerListener(this, light, SensorManager.SENSOR_DELAY_NORMAL)) lightError = "registration_failed";
            if (ownerAcceleration && acceleration != null && !manager.registerListener(this, acceleration, SensorManager.SENSOR_DELAY_NORMAL)) accelerationError = "registration_failed";
        }
        if (ownerBattery) {
            try {
                Intent sticky = context.registerReceiver(batteryReceiver, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                batteryRegistered = true;
                if (sticky != null) battery(sticky);
            } catch (RuntimeException e) { battery = "battery unavailable reason=registration_failed"; }
        }
    }
    void stop() {
        if (manager != null) manager.unregisterListener(this);
        if (batteryRegistered) { context.unregisterReceiver(batteryReceiver); batteryRegistered = false; }
    }
    String capabilities() {
        StringBuilder caps = new StringBuilder();
        caps.append(Protocol.event(ownerBattery ? "cap battery" : "owner battery off"));
        if (light == null) caps.append(Protocol.event("sensor light absent"));
        else if (!ownerLight) caps.append(Protocol.event("owner light off"));
        else caps.append(Protocol.event("cap light"));
        if (acceleration == null) caps.append(Protocol.event("sensor accelerometer absent"));
        else if (!ownerAcceleration) caps.append(Protocol.event("owner accelerometer off"));
        else caps.append(Protocol.event("cap accelerometer"));
        caps.append(Protocol.event("cap wifi_link_rssi"));
        return caps.toString();
    }
    private synchronized void battery(Intent intent) {
        int level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
        int state = intent.getIntExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_UNKNOWN);
        String charge = state == BatteryManager.BATTERY_STATUS_CHARGING || state == BatteryManager.BATTERY_STATUS_FULL
                ? "true" : state == BatteryManager.BATTERY_STATUS_DISCHARGING || state == BatteryManager.BATTERY_STATUS_NOT_CHARGING ? "false" : "unknown";
        String fraction = level >= 0 && scale > 0 && level <= scale ? Float.toString((float) level / scale) : "unknown";
        battery = "battery level=" + fraction + " charging=" + charge;
    }
    @Override public synchronized void onSensorChanged(SensorEvent event) {
        long time = event.timestamp / 1000000L;
        if (event.sensor.getType() == Sensor.TYPE_LIGHT) {
            if (event.values.length < 1 || !finite(event.values[0]) || event.values[0] < 0) { lightError = "invalid_sample"; lightTime = 0; return; }
            lux = event.values[0]; lightTime = time; lightSensorTimeNs = event.timestamp; lightAccuracy = event.accuracy; lightError = null;
        } else if (event.sensor.getType() == Sensor.TYPE_ACCELEROMETER) {
            if (event.values.length < 3 || !finite(event.values[0]) || !finite(event.values[1]) || !finite(event.values[2])) {
                accelerationError = "invalid_sample"; accelerationTime = 0; return;
            }
            x = event.values[0]; y = event.values[1]; z = event.values[2];
            accelerationTime = time; accelerationSensorTimeNs = event.timestamp; accelerationAccuracy = event.accuracy; accelerationError = null;
        }
    }
    @Override public synchronized void onAccuracyChanged(Sensor sensor, int accuracy) { }
    synchronized String snapshot() {
        long now = SystemClock.elapsedRealtime();
        StringBuilder body = new StringBuilder(Protocol.event(ownerBattery ? battery : "battery unavailable reason=owner_off"));
        body.append(Protocol.event(wifiRssi(now)));
        if (!ownerLight) body.append(Protocol.event("light unavailable reason=owner_off"));
        else if (light == null) body.append(Protocol.event("light unavailable reason=absent"));
        else if (lightError != null) body.append(Protocol.event("light unavailable reason=" + lightError));
        else if (now < lightTime || now - lightTime > 60000) body.append(Protocol.event("light unavailable reason=stale age_ms=" + (now - lightTime)));
        else body.append(sample(lightTime, lightSensorTimeNs, now, "light lux=" + lux + " accuracy=" + lightAccuracy));
        if (!ownerAcceleration) body.append(Protocol.event("acceleration unavailable reason=owner_off"));
        else if (acceleration == null) body.append(Protocol.event("acceleration unavailable reason=absent"));
        else if (accelerationError != null) body.append(Protocol.event("acceleration unavailable reason=" + accelerationError));
        else if (now < accelerationTime || now - accelerationTime > 15000) body.append(Protocol.event("acceleration unavailable reason=stale age_ms=" + (now - accelerationTime)));
        else body.append(sample(accelerationTime, accelerationSensorTimeNs, now, "acceleration x=" + x + " y=" + y + " z=" + z + " accuracy=" + accelerationAccuracy));
        body.append(Protocol.event(bleStatus()));
        return body.toString();
    }
    private String wifiRssi(long now) {
        long observedAt = System.currentTimeMillis() / 1000L;
        if (wifi == null) return WifiRssi.unavailable("service_absent", observedAt, now);
        try {
            WifiInfo info = wifi.getConnectionInfo();
            return WifiRssi.event(info != null && info.getNetworkId() >= 0,
                    info == null ? -127 : info.getRssi(), observedAt, now);
        } catch (SecurityException e) {
            return WifiRssi.unavailable("permission_denied", observedAt, now);
        } catch (RuntimeException e) {
            return WifiRssi.unavailable("read_failed", observedAt, now);
        }
    }
    private String bleStatus() {
        try {
            return BleStatus.snapshot(context);
        } catch (RuntimeException e) {
            return "ble_status source=androidbody_bluetooth_api error=" + e.getClass().getSimpleName();
        }
    }
    private String sample(long time, long sensorTimeNs, long now, String value) {
        long age = now - time;
        long epoch = (System.currentTimeMillis() - age) / 1000L;
        return epoch + " " + value + " age_ms=" + age + " sensor_time_ns=" + sensorTimeNs
                + " phone_elapsed_ms=" + time + "\n";
    }
    private static boolean finite(float value) { return !Float.isNaN(value) && !Float.isInfinite(value); }
}
