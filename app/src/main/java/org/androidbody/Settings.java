// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;

final class Settings {
    static SharedPreferences preferences(Context context) { return context.getSharedPreferences("body", Context.MODE_PRIVATE); }
    static String cursorKey(String endpoint) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(endpoint.getBytes(Protocol.UTF8));
            StringBuilder key = new StringBuilder("cursor_");
            for (byte b : hash) key.append(String.format(java.util.Locale.US, "%02x", b & 255));
            return key.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static File marker(Context context) { return new File(context.getFilesDir(), "run-enabled"); }

    /** Both the preference and matching endpoint marker must be present to restore. */
    static synchronized boolean desiredOn(Context context) {
        SharedPreferences prefs = preferences(context);
        if (!prefs.getBoolean("desired_on", false)) return false;
        try {
            String endpoint = Protocol.endpoint(prefs.getString("endpoint", ""), prefs.getBoolean("allow_http", false));
            FileInputStream in = new FileInputStream(marker(context));
            try {
                byte[] bytes = new byte[128];
                int size = in.read(bytes);
                return size > 0 && in.read() == -1
                        && cursorKey(endpoint).equals(new String(bytes, 0, size, Protocol.UTF8));
            } finally { in.close(); }
        } catch (IOException | IllegalArgumentException e) { return false; }
    }
    static synchronized boolean arm(Context context, String endpoint) {
        File file = marker(context);
        File temp = new File(context.getFilesDir(), "run-enabled.tmp");
        try {
            FileOutputStream out = new FileOutputStream(temp);
            try { out.write(cursorKey(endpoint).getBytes(Protocol.UTF8)); out.getFD().sync(); }
            finally { out.close(); }
            if (!temp.renameTo(file)) throw new IOException("Cannot enable persistent session");
            long exit = latestExit(context)[0];
            if (!preferences(context).edit().putBoolean("desired_on", true).putLong("exit_baseline", exit).commit()) {
                disarm(context); return false;
            }
            return true;
        } catch (IOException e) { temp.delete(); disarm(context); return false; }
    }
    /** Deleting the marker independently makes OFF survive a failed preference write. */
    static synchronized boolean disarm(Context context) {
        File file = marker(context);
        boolean removed = !file.exists() || file.delete();
        new File(context.getFilesDir(), "run-enabled.tmp").delete();
        boolean saved = preferences(context).edit().putBoolean("desired_on", false).commit();
        return removed || saved;
    }
    static synchronized void honorUserStop(Context context) {
        if (!desiredOn(context)) return;
        long[] exit = latestExit(context);
        if (exit[0] > preferences(context).getLong("exit_baseline", 0) && exit[1] == 1) disarm(context);
    }
    private static long[] latestExit(Context context) {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
                List<ApplicationExitInfo> exits = manager.getHistoricalProcessExitReasons(null, 0, 1);
                if (!exits.isEmpty()) {
                    ApplicationExitInfo exit = exits.get(0);
                    return new long[] { exit.getTimestamp(), exit.getReason() == ApplicationExitInfo.REASON_USER_REQUESTED ? 1 : 0 };
                }
            } catch (RuntimeException ignored) { }
        }
        return new long[] { 0, 0 };
    }
    static synchronized File spoolDirectory(Context context, String endpoint, boolean create) throws IOException {
        File root = new File(context.getFilesDir(), "observations");
        if (!root.exists() && create && !root.mkdirs()) throw new IOException("Cannot create observation storage");
        File node = new File(root, cursorKey(endpoint));
        if (!node.exists() && create) {
            File[] directories = root.listFiles();
            if (directories == null) throw new IOException("Cannot inspect observation storage");
            int count = 0;
            for (File directory : directories) if (directory.isDirectory()) count++;
            if (count >= 8) throw new IOException("Eight saved destinations reached; clear an old node's saved observations first");
            if (!node.mkdir()) throw new IOException("Cannot create node storage");
        }
        return node;
    }
}
