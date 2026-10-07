// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** Restore an explicitly enabled session after unlock/reboot or an app update, where allowed. */
public final class RestoreReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        Settings.honorUserStop(context);
        if (!Settings.desiredOn(context)) return;
        BodyService.createChannel(context);
        if (!BodyService.notificationsVisible(context)) {
            BodyService.status = "Paused: enable Body notifications, then press ON";
            return;
        }
        try {
            Intent restore = new Intent(context, BodyService.class).setAction(BodyService.RESTORE);
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(restore); else context.startService(restore);
        } catch (RuntimeException e) {
            BodyService.status = "Paused by Android: open Body and press ON";
        }
    }
}
