// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.BatteryManager;
import android.os.SystemClock;

/** Holds only the latest real samples; snapshots coalesce while the network is offline. */
final class Sensors implements SensorEventListener {
    private final Context context;
    private final SensorManager manager;
    private final Sensor light;
    private final Sensor acceleration;
    private String lightError = "no_sample";
    private String accelerationError = "no_sample";
    private boolean batteryRegistered;
    private float lux;
    private float x, y, z;
    private long lightTime;
    private long accelerationTime;
    private int lightAccuracy;
    private int accelerationAccuracy;
    private String battery = "battery unavailable reason=no_sample";
    private final BroadcastReceiver batteryReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ignored, Intent intent) { battery(intent); }
    };
    Sensors(Context context) {
        this.context = context;
        manager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        light = manager == null ? null : manager.getDefaultSensor(Sensor.TYPE_LIGHT);
        acceleration = manager == null ? null : manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
    }
    void start() {
        if (manager != null) {
            if (light != null && !manager.registerListener(this, light, SensorManager.SENSOR_DELAY_NORMAL)) lightError = "registration_failed";
            if (acceleration != null && !manager.registerListener(this, acceleration, SensorManager.SENSOR_DELAY_NORMAL)) accelerationError = "registration_failed";
        }
        try {
            Intent sticky = context.registerReceiver(batteryReceiver, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            batteryRegistered = true;
            if (sticky != null) battery(sticky);
        } catch (RuntimeException e) { battery = "battery unavailable reason=registration_failed"; }
    }
    void stop() {
        if (manager != null) manager.unregisterListener(this);
        if (batteryRegistered) { context.unregisterReceiver(batteryReceiver); batteryRegistered = false; }
    }
    String capabilities() {
        return Protocol.event("cap battery")
                + Protocol.event(light == null ? "sensor light absent" : "cap light")
                + Protocol.event(acceleration == null ? "sensor accelerometer absent" : "cap accelerometer");
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
            lux = event.values[0]; lightTime = time; lightAccuracy = event.accuracy; lightError = null;
        } else if (event.sensor.getType() == Sensor.TYPE_ACCELEROMETER) {
            if (event.values.length < 3 || !finite(event.values[0]) || !finite(event.values[1]) || !finite(event.values[2])) {
                accelerationError = "invalid_sample"; accelerationTime = 0; return;
            }
            x = event.values[0]; y = event.values[1]; z = event.values[2];
            accelerationTime = time; accelerationAccuracy = event.accuracy; accelerationError = null;
        }
    }
    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }
    synchronized String snapshot() {
        long now = SystemClock.elapsedRealtime();
        StringBuilder body = new StringBuilder(Protocol.event(battery));
        if (light == null) body.append(Protocol.event("light unavailable reason=absent"));
        else if (lightError != null) body.append(Protocol.event("light unavailable reason=" + lightError));
        else if (now < lightTime || now - lightTime > 60000) body.append(Protocol.event("light unavailable reason=stale"));
        else body.append(sample(lightTime, now, "light lux=" + lux + " accuracy=" + lightAccuracy));
        if (acceleration == null) body.append(Protocol.event("acceleration unavailable reason=absent"));
        else if (accelerationError != null) body.append(Protocol.event("acceleration unavailable reason=" + accelerationError));
        else if (now < accelerationTime || now - accelerationTime > 15000) body.append(Protocol.event("acceleration unavailable reason=stale"));
        else body.append(sample(accelerationTime, now, "acceleration x=" + x + " y=" + y + " z=" + z + " accuracy=" + accelerationAccuracy));
        return body.toString();
    }
    private String sample(long time, long now, String value) {
        long age = now - time;
        long epoch = (System.currentTimeMillis() - age) / 1000L;
        return epoch + " " + value + " age_ms=" + age + "\n";
    }
    private static boolean finite(float value) { return !Float.isNaN(value) && !Float.isInfinite(value); }
}
