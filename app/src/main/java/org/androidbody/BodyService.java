// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import java.io.IOException;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

public final class BodyService extends Service {
    static final String STOP = "org.androidbody.STOP";
    static final String RESTORE = "org.androidbody.RESTORE";
    static final String MODE = "org.androidbody.MODE";
    static final String CHANNEL = "body_running";
    static volatile boolean running;
    static volatile String status = "OFF";
    private static volatile Session lastSession;
    private final Handler main = new Handler(Looper.getMainLooper());
    private Session current;
    private boolean foreground;
    private long lastNotice;
    private boolean noticeScheduled;

    private static final class Session {
        final BodyService owner;
        final SharedPreferences preferences;
        final String endpoint, secret, cursorKey;
        final boolean allowHttp;
        final Sensors sensors;
        final Vibrator vibrator;
        final Object signal = new Object();
        volatile boolean active = true, collectOnly;
        volatile int modeVersion, queued;
        volatile String mode = "Starting";
        volatile Transport transport;
        volatile Thread worker, sampler;
        ObservationSpool spool;
        PowerManager.WakeLock wakeLock;
        Session previous;
        long lastVibration = -3000;
        Session(BodyService owner, Session previous) {
            this.owner = owner; this.previous = previous;
            preferences = Settings.preferences(owner);
            allowHttp = preferences.getBoolean("allow_http", false);
            endpoint = Protocol.endpoint(preferences.getString("endpoint", ""), allowHttp);
            secret = Protocol.secret(preferences.getString("secret", ""));
            cursorKey = Settings.cursorKey(endpoint);
            collectOnly = preferences.getBoolean("collect_only", false);
            sensors = new Sensors(owner);
            vibrator = (Vibrator) owner.getSystemService(VIBRATOR_SERVICE);
            transport = new Transport(endpoint, secret, allowHttp);
        }
    }
    static void awaitStoppedWork() throws IOException {
        Session session = lastSession;
        if (session == null || session.worker == null) return;
        if (session.active) throw new IOException("Session is still active");
        try { session.worker.join(15000); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException("Waiting for stop interrupted", e); }
        if (session.worker.isAlive()) throw new IOException("Previous session is still stopping");
    }
    static void applyModeFromUi() {
        Session session = lastSession;
        if (session != null && session.active) session.owner.changeMode(session);
    }
    static void stopFromUi(android.content.Context context, String message) {
        Session session = lastSession;
        if (session != null && session.active) { session.owner.stopActive(message); session.owner.stopSelf(); }
        else { running = false; status = message; context.stopService(new Intent(context, BodyService.class)); }
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    static void createChannel(android.content.Context context) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager manager = (NotificationManager) context.getSystemService(NOTIFICATION_SERVICE);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Body is ON", NotificationManager.IMPORTANCE_LOW));
        }
    }
    static boolean notificationsVisible(android.content.Context context) {
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false;
        NotificationManager manager = (NotificationManager) context.getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 24 && !manager.areNotificationsEnabled()) return false;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
            if (channel == null || channel.getImportance() == NotificationManager.IMPORTANCE_NONE) return false;
        }
        return true;
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? RESTORE : intent.getAction();
        if (STOP.equals(action)) {
            boolean saved = Settings.disarm(this);
            stopActive(saved ? "OFF" : "OFF now; storage failed. Use Android Force stop before reboot.");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (MODE.equals(action)) {
            if (current != null && current.active) changeMode(current);
            else stopSelf();
            return current != null && current.active ? START_STICKY : START_NOT_STICKY;
        }
        Settings.honorUserStop(this);
        if (!Settings.desiredOn(this)) { stopActive("OFF"); stopSelf(); return START_NOT_STICKY; }
        if (current != null && current.active) return START_STICKY;
        createChannel(this);
        try {
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).cancel(2);
            Notification initial = notification("Starting • saved ON enabled", true);
            if (Build.VERSION.SDK_INT >= 34) startForeground(1, initial, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            else startForeground(1, initial);
            foreground = true;
            if (!notificationsVisible(this)) throw new IllegalStateException("Enable Body notifications before starting");
            final Session session = new Session(this, lastSession);
            current = session; lastSession = session;
            session.sensors.start();
            PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
            session.wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "AndroidBody:session");
            session.wakeLock.setReferenceCounted(false);
            keepCpuAwake(session);
            running = true;
            session.mode = session.collectOnly ? "Collect only • nothing sent" : "Connecting";
            refreshNotice(session);
            session.worker = new Thread(new Runnable() { @Override public void run() { runSession(session); } }, "body-network");
            session.worker.start();
            return START_STICKY;
        } catch (RuntimeException e) {
            Settings.disarm(this);
            stopActive("OFF: start failed (" + e.getClass().getSimpleName() + ")");
            stopSelf();
            return START_NOT_STICKY;
        }
    }
    @android.annotation.SuppressLint("WakelockTimeout")
    private void keepCpuAwake(Session session) { session.wakeLock.acquire(); }
    private Notification notification(String text, boolean ongoing) {
        int immutable = Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0;
        PendingIntent content = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | immutable);
        PendingIntent off = PendingIntent.getService(this, 1, new Intent(this, BodyService.class).setAction(STOP), PendingIntent.FLAG_UPDATE_CURRENT | immutable);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        builder.setContentTitle(ongoing ? "Android Body is ON" : "Android Body stopped")
                .setContentText(text).setSmallIcon(R.drawable.ic_stat_body).setOngoing(ongoing)
                .setOnlyAlertOnce(true).setShowWhen(false).setContentIntent(content);
        if (ongoing) builder.addAction(android.R.drawable.ic_menu_close_clear_cancel, "OFF", off).setDeleteIntent(off);
        if (Build.VERSION.SDK_INT >= 31) builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        return builder.build();
    }
    private void requestNotice(final Session session) {
        main.post(new Runnable() { @Override public void run() {
            if (current != session || !session.active || noticeScheduled) return;
            noticeScheduled = true;
            main.postDelayed(new Runnable() { @Override public void run() {
                noticeScheduled = false;
                if (current == session && session.active) refreshNotice(session);
            } }, Math.max(0, 2000 - (SystemClock.elapsedRealtime() - lastNotice)));
        } });
    }
    private void refreshNotice(Session session) {
        String text = (session.collectOnly ? "Collect only • nothing sent" : session.mode) + " • " + session.queued + " saved";
        status = "ON: " + text;
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(1, notification(text, true));
        lastNotice = SystemClock.elapsedRealtime();
    }
    private void changeMode(Session session) {
        boolean collect = session.preferences.getBoolean("collect_only", false);
        if (collect == session.collectOnly) return;
        synchronized (session.signal) {
            session.collectOnly = collect;
            if (collect && session.vibrator != null) { try { session.vibrator.cancel(); } catch (RuntimeException ignored) { } }
            session.modeVersion++;
            try { session.transport.cancel(); } catch (RuntimeException ignored) { }
            session.transport = new Transport(session.endpoint, session.secret, session.allowHttp);
            session.mode = collect ? "Collect only • nothing sent" : "Connecting / sending backlog";
            session.signal.notifyAll();
        }
        requestNotice(session);
    }
    private void runSession(final Session session) {
        try {
            // A prior stopped service can still be unwinding I/O. Do not open its file twice.
            Session previous = session.previous;
            boolean interrupted = Thread.interrupted();
            if (previous != null && previous.worker != null) {
                // Preserve transitive teardown ordering through even a rapidly stopped middle session.
                while (previous.worker.isAlive()) {
                    try { previous.worker.join(100); } catch (InterruptedException e) { interrupted = true; }
                }
            }
            session.previous = null;
            if (interrupted) Thread.currentThread().interrupt();
            if (!session.active) return;
            session.spool = new ObservationSpool(Settings.spoolDirectory(this, session.endpoint, true));
            if (!session.active) return;
            String hello = Protocol.event("hello node=" + Protocol.node(session.endpoint) + " protocol=1 session=" + UUID.randomUUID())
                    + Protocol.event("android sdk=" + Build.VERSION.SDK_INT) + session.sensors.capabilities()
                    + Protocol.event(session.vibrator != null && session.vibrator.hasVibrator() ? "cap vibration" : "actuator vibration absent");
            long pending = session.preferences.getLong(session.cursorKey + "_pending", 0);
            if (pending > 0) hello += Protocol.event("action " + pending + " unknown reason=interrupted verification=unverified");
            session.spool.enqueue(hello);
            if (pending > 0 && !session.preferences.edit().remove(session.cursorKey + "_pending").commit()) throw new IOException("Cannot persist interrupted result");
            session.queued = session.spool.lineCount();
            session.sampler = new Thread(new Runnable() { @Override public void run() { sample(session); } }, "body-sampler");
            session.sampler.start();
            network(session);
        } catch (InterruptedException stopped) {
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) {
            fail(session, "storage/start failure: " + e.getClass().getSimpleName());
        } finally {
            if (session.sampler != null) {
                session.sampler.interrupt();
                boolean interrupted = Thread.interrupted();
                while (session.sampler.isAlive()) {
                    try { session.sampler.join(100); } catch (InterruptedException e) { interrupted = true; }
                }
                if (interrupted) Thread.currentThread().interrupt();
            }
            if (session.spool != null) { try { session.spool.close(); } catch (IOException ignored) { } }
            session.previous = null;
        }
    }
    private void sample(Session session) {
        try {
            while (session.active) {
                if (!notificationsVisible(this)) { fail(session, "notifications disabled"); return; }
                session.spool.enqueue(session.sensors.snapshot());
                session.queued = session.spool.lineCount();
                requestNotice(session);
                Thread.sleep(5000);
            }
        } catch (InterruptedException stopped) {
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) { fail(session, "cannot save observations"); }
    }
    private void network(Session session) throws InterruptedException, IOException {
        long cursor = session.preferences.getLong(session.cursorKey, 0);
        int failures = 0;
        boolean paused = false;
        int lastMode = session.modeVersion;
        while (session.active) {
            int version = session.modeVersion;
            if (version != lastMode) { failures = 0; paused = false; lastMode = version; }
            if (session.collectOnly || paused) { await(session, 1000, version); continue; }
            Transport client = session.transport;
            try {
                ObservationSpool.Batch batch = session.spool.peekBatch(Protocol.MAX_BATCH, Protocol.MAX_BODY_BYTES);
                if (batch != null) {
                    if (!session.active || session.collectOnly) continue;
                    session.mode = "Sending saved observations"; requestNotice(session);
                    client.postObservations(batch.text);
                    try { session.spool.acknowledge(batch.token); } catch (IOException e) { throw new StorageFailure(e); }
                    session.queued = session.spool.lineCount();
                }
                if (!session.active || session.collectOnly || version != session.modeVersion) continue;
                if (session.spool.lineCount() > 0) continue; // Drain saved receipts before another physical effect.
                List<Protocol.Action> actions;
                try { actions = Protocol.actions(client.getActions(cursor), cursor); }
                catch (IllegalArgumentException e) { throw new Transport.ProtocolFailure("Invalid action response"); }
                failures = 0;
                session.mode = "Connected • sending enabled"; requestNotice(session);
                if (!actions.isEmpty()) {
                    Protocol.Action action = actions.get(0);
                    String outcome = execute(session, action);
                    if (outcome == null) continue;
                    cursor = action.id;
                    try { session.spool.enqueue(outcome); } catch (IOException e) { throw new StorageFailure(e); }
                    // A persisted outcome, rather than a network ACK, now closes the crash marker.
                    if (!session.preferences.edit().remove(session.cursorKey + "_pending").commit()) throw new StorageFailure("Cannot persist action receipt");
                    session.queued = session.spool.lineCount();
                    await(session, 500, version);
                } else await(session, 2000, version);
            } catch (Transport.ProtocolFailure e) {
                paused = true; session.mode = "Upload paused • invalid response; collecting"; requestNotice(session);
            } catch (Transport.HttpFailure e) {
                if (e.fatal()) {
                    paused = true; session.mode = "Upload paused • HTTP " + e.status + "; collecting"; requestNotice(session);
                } else failures = retry(session, failures, "HTTP " + e.status, version);
            } catch (StorageFailure e) {
                throw e;
            } catch (IOException e) {
                // Local spool failures must stop, rather than be disguised as network outages.
                if (!session.active || session.collectOnly || version != session.modeVersion) continue;
                failures = retry(session, failures, e instanceof javax.net.ssl.SSLException ? "TLS error" : "offline", version);
            }
        }
    }
    private int retry(Session session, int failures, String reason, int version) throws InterruptedException {
        failures = Math.min(6, failures + 1);
        long delay = Math.min(60000, 1000L << failures);
        session.mode = "Collecting • " + reason + " • retry " + delay / 1000 + "s"; requestNotice(session);
        await(session, delay + (long) (Math.random() * 500), version);
        return failures;
    }
    private void await(Session session, long millis, int version) throws InterruptedException {
        synchronized (session.signal) {
            if (session.active && version == session.modeVersion) session.signal.wait(millis);
        }
    }
    private String execute(final Session session, final Protocol.Action action) throws InterruptedException, IOException {
        final CountDownLatch complete = new CountDownLatch(1);
        final String[] result = new String[1];
        final boolean[] error = new boolean[1];
        main.post(new Runnable() { @Override public void run() {
            try {
                if (current != session || !session.active || session.collectOnly) return;
                if (!session.preferences.edit().putLong(session.cursorKey, action.id).putLong(session.cursorKey + "_pending", action.id).commit()) { error[0] = true; return; }
                int duration = Protocol.vibrationDuration(action.command);
                String requested = Protocol.event("action " + action.id + " requested kind=" + (duration > 0 ? "vibrate duration=" + duration : "unknown"));
                String failure = null;
                if (!notificationsVisible(BodyService.this)) failure = "notifications_disabled";
                else if (duration < 0) failure = action.command.startsWith("vibrate") ? "invalid_arguments" : "unsupported_action";
                else if (session.vibrator == null || !session.vibrator.hasVibrator()) failure = "absent";
                else if (SystemClock.elapsedRealtime() - session.lastVibration < 3000) failure = "rate_limited";
                if (failure != null) { result[0] = requested + Protocol.event("action " + action.id + " failed reason=" + failure); return; }
                try {
                    if (Build.VERSION.SDK_INT >= 26) session.vibrator.vibrate(VibrationEffect.createOneShot(duration, VibrationEffect.DEFAULT_AMPLITUDE));
                    else session.vibrator.vibrate(duration);
                    session.lastVibration = SystemClock.elapsedRealtime();
                    result[0] = requested + Protocol.event("action " + action.id + " succeeded kind=vibrate duration=" + duration + " evidence=api_return verification=unverified");
                } catch (SecurityException e) { result[0] = requested + Protocol.event("action " + action.id + " failed reason=permission_denied"); }
                catch (RuntimeException e) { result[0] = requested + Protocol.event("action " + action.id + " failed reason=api_error verification=unverified"); }
            } finally { complete.countDown(); }
        } });
        while (session.active && !complete.await(500, TimeUnit.MILLISECONDS)) { }
        if (error[0]) throw new StorageFailure("Cannot persist action cursor");
        return result[0];
    }
    private static final class StorageFailure extends IOException {
        StorageFailure(IOException cause) { super(cause); }
        StorageFailure(String message) { super(message); }
    }
    private void fail(final Session session, final String message) {
        main.post(new Runnable() { @Override public void run() {
            if (current != session || !session.active) return;
            boolean saved = Settings.disarm(BodyService.this);
            stopActive("OFF: " + message + (saved ? "" : "; use Android Force stop before reboot"));
            if (notificationsVisible(BodyService.this)) ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(2, notification(status, false));
            stopSelf();
        } });
    }
    private void stopActive(String message) {
        Session session = current;
        if (session != null) {
            session.active = false;
            if (session.wakeLock != null) { try { if (session.wakeLock.isHeld()) session.wakeLock.release(); } catch (RuntimeException ignored) { } }
            try { session.transport.cancel(); } catch (RuntimeException ignored) { }
            if (session.worker != null) session.worker.interrupt();
            if (session.sampler != null) session.sampler.interrupt();
            try { session.sensors.stop(); } catch (RuntimeException ignored) { }
            if (session.vibrator != null) { try { session.vibrator.cancel(); } catch (RuntimeException ignored) { } }
            synchronized (session.signal) { session.signal.notifyAll(); }
        }
        running = false; status = message;
        if (foreground) { stopForeground(true); foreground = false; }
    }
    @Override public void onDestroy() {
        stopActive(Settings.desiredOn(this) ? "Paused • saved ON; Android may restore the session" : status);
        super.onDestroy();
    }
}
