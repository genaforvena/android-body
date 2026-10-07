// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.IOException;

public final class MainActivity extends Activity {
    private EditText endpoint, secret;
    private CheckBox allowHttp, collectOnly;
    private TextView status;
    private Button toggle, reset, clear;
    private LinearLayout settings;
    private static volatile boolean clearing;
    private final Handler refresh = new Handler();
    private final Runnable update = new Runnable() { @Override public void run() { render(); refresh.postDelayed(this, 500); } };
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        Settings.honorUserStop(this);
        BodyService.createChannel(this);
        final SharedPreferences preferences = Settings.preferences(this);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true); scroll.setFitsSystemWindows(true);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int space = dp(24); root.setPadding(space, space, space, space);
        root.setBackgroundColor(Color.rgb(248, 248, 243)); scroll.addView(root);
        root.addView(label("Android Body", 30)); root.addView(label("A small physical bridge.", 16));
        addGap(root, 18);
        status = label("OFF", 16); status.setId(R.id.status); root.addView(status);
        toggle = new Button(this); toggle.setText(R.string.turn_on);
        toggle.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View view) {
            if (BodyService.running || Settings.desiredOn(MainActivity.this)) {
                boolean saved = Settings.disarm(MainActivity.this);
                BodyService.stopFromUi(MainActivity.this, saved ? "OFF • saved observations kept" : "OFF now; storage failed. Use Android Force stop before reboot.");
                toggle.setEnabled(false);
            } else startBody();
        } });
        root.addView(toggle);
        collectOnly = new CheckBox(this); collectOnly.setId(R.id.collect_only);
        collectOnly.setText(R.string.collect_only); collectOnly.setChecked(preferences.getBoolean("collect_only", false));
        collectOnly.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(CompoundButton button, boolean checked) {
                if (!preferences.edit().putBoolean("collect_only", checked).commit()) {
                    boolean saved = Settings.disarm(MainActivity.this);
                    BodyService.stopFromUi(MainActivity.this, saved ? "OFF • mode could not be saved" : "OFF now; storage failed. Use Android Force stop before reboot.");
                    show("Could not save the mode, so Body has stopped. Check storage before turning ON again."); return;
                }
                BodyService.applyModeFromUi();
            }
        });
        root.addView(collectOnly);
        root.addView(label("Checked: store locally, with no uploads or remote actions. Uncheck to send this node’s saved observations while ON.", 13));
        addGap(root, 14);
        root.addView(label("ON is remembered. Android can restore the visible session after a process kill or reboot. OFF disarms restoration. Force-stop and Xiaomi restrictions can still prevent operation.", 14));
        addGap(root, 10);
        root.addView(label("Keeps the CPU awake while ON, using more battery. The notification shows sending, offline collection or collect-only mode. No camera, microphone, location or account.", 14));
        addGap(root, 16);
        Button options = new Button(this); options.setText(R.string.connection_settings);
        root.addView(options);
        settings = new LinearLayout(this); settings.setOrientation(LinearLayout.VERTICAL);
        settings.setVisibility(preferences.getString("endpoint", "").isEmpty() ? View.VISIBLE : View.GONE);
        options.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View view) {
            settings.setVisibility(settings.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE);
        } });
        root.addView(settings);
        settings.addView(label("Endpoint", 16));
        endpoint = new EditText(this); endpoint.setId(R.id.endpoint); endpoint.setSingleLine(true);
        endpoint.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        endpoint.setHint("https://body.example/node/note3"); endpoint.setText(preferences.getString("endpoint", "")); settings.addView(endpoint);
        settings.addView(label("Shared secret", 16));
        secret = new EditText(this); secret.setId(R.id.secret); secret.setSingleLine(true); secret.setSaveEnabled(false);
        secret.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        secret.setTransformationMethod(PasswordTransformationMethod.getInstance());
        if (Build.VERSION.SDK_INT >= 26) secret.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        secret.setHint("32+ URL-safe characters"); secret.setText(preferences.getString("secret", "")); settings.addView(secret);
        allowHttp = new CheckBox(this); allowHttp.setText(R.string.allow_http); allowHttp.setChecked(preferences.getBoolean("allow_http", false)); settings.addView(allowHttp);
        settings.addView(label("HTTP exposes the secret and observations. Prefer HTTPS. Each endpoint has its own saved queue; changing it never uploads an old node’s data elsewhere.", 13));
        addGap(settings, 12);
        reset = new Button(this); reset.setText(R.string.reset_cursor);
        reset.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View view) { resetCursor(); } }); settings.addView(reset);
        clear = new Button(this); clear.setText(R.string.clear_saved);
        clear.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View view) { clearSaved(); } }); settings.addView(clear);
        settings.addView(label("Collection is bounded; when full, oldest lines are dropped with an explicit loss report. On Xiaomi, review this app’s battery/autostart settings. No setting guarantees survival.", 13));
        setContentView(scroll);
    }
    private void startBody() {
        if (clearing) return;
        try {
            String url = Protocol.endpoint(endpoint.getText().toString(), allowHttp.isChecked());
            String token = Protocol.secret(secret.getText().toString());
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 10); return;
            }
            if (!BodyService.notificationsVisible(this)) { show("Enable Body notifications and its ‘Body is ON’ channel in Android Settings, then try again."); return; }
            if (!Settings.preferences(this).edit().putString("endpoint", url).putString("secret", token)
                    .putBoolean("allow_http", allowHttp.isChecked()).putBoolean("collect_only", collectOnly.isChecked()).commit()
                    || !Settings.arm(this, url)) { show("Could not save configuration and ON state. Body remains OFF."); return; }
            Intent intent = new Intent(this, BodyService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
            toggle.setEnabled(false); status.setText(R.string.starting);
        } catch (IllegalArgumentException e) { settings.setVisibility(View.VISIBLE); show(e.getMessage()); }
        catch (RuntimeException e) { Settings.disarm(this); show("Could not start service: " + e.getClass().getSimpleName()); }
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 10) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) startBody();
            else show("Body remains OFF. Notifications are required here so operation stays visible.");
        }
    }
    private boolean enabled() { return BodyService.running || Settings.desiredOn(this); }
    private void resetCursor() {
        if (enabled() || clearing) return;
        final String url;
        try { url = Protocol.endpoint(endpoint.getText().toString(), allowHttp.isChecked()); }
        catch (IllegalArgumentException e) { show(e.getMessage()); return; }
        new AlertDialog.Builder(this).setTitle("Reset this node’s cursor?")
                .setMessage("Old queued actions may run again after ON. Reconcile or empty the server’s action queue first. Saved observations are unchanged.")
                .setNegativeButton("Cancel", null).setPositiveButton("Reset", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        if (enabled()) return;
                        String key = Settings.cursorKey(url);
                        boolean saved = Settings.preferences(MainActivity.this).edit().remove(key).remove(key + "_pending").commit();
                        show(saved ? "Action cursor reset to 0. Body remains OFF." : "Could not reset cursor.");
                    }
                }).show();
    }
    private void clearSaved() {
        if (enabled() || clearing) return;
        final String url;
        try { url = Protocol.endpoint(endpoint.getText().toString(), allowHttp.isChecked()); }
        catch (IllegalArgumentException e) { show(e.getMessage()); return; }
        new AlertDialog.Builder(this).setTitle("Delete this node’s saved observations?")
                .setMessage("This permanently deletes unsent sensor readings and action results for " + Protocol.node(url) + ". Its action cursor and other nodes are unchanged.")
                .setNegativeButton("Cancel", null).setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        if (enabled() || clearing) return;
                        clearing = true;
                        new Thread(new Runnable() { @Override public void run() {
                            String result;
                            try {
                                BodyService.awaitStoppedWork();
                                File directory = Settings.spoolDirectory(MainActivity.this, url, false);
                                if (directory.exists()) {
                                    ObservationSpool.discard(directory);
                                    File[] files = directory.listFiles();
                                    if (files == null) throw new IOException("Cannot inspect queue");
                                    for (File file : files) if (!file.isFile() || !file.delete()) throw new IOException("Cannot remove saved queue");
                                    if (!directory.delete()) throw new IOException("Cannot remove saved queue directory");
                                }
                                result = "OFF • this node’s saved observations deleted";
                            } catch (IOException e) { result = "OFF • could not clear queue. If a session is stopping, wait and retry."; }
                            BodyService.status = result; clearing = false;
                        } }, "body-clear").start();
                    }
                }).show();
    }
    private void render() {
        boolean on = enabled();
        endpoint.setEnabled(!on && !clearing); secret.setEnabled(!on && !clearing); allowHttp.setEnabled(!on && !clearing);
        reset.setEnabled(!on && !clearing); clear.setEnabled(!on && !clearing); collectOnly.setEnabled(!clearing);
        toggle.setText(on ? "Turn OFF" : "Turn ON"); toggle.setEnabled(!clearing);
        String text = BodyService.status;
        if (on && !BodyService.running && "OFF".equals(text)) text = "ON requested • Android paused it; switch OFF then ON to resume";
        status.setText(clearing ? "Deleting saved observations…" : text);
    }
    private void show(String message) { new AlertDialog.Builder(this).setMessage(message).setPositiveButton("OK", null).show(); }
    private TextView label(String text, int size) { TextView v = new TextView(this); v.setText(text); v.setTextSize(size); v.setTextColor(Color.rgb(32, 50, 41)); return v; }
    private int dp(int value) { return (int) (value * getResources().getDisplayMetrics().density + 0.5f); }
    private void addGap(LinearLayout root, int size) { root.addView(new View(this), new LinearLayout.LayoutParams(1, dp(size))); }
    @Override protected void onResume() { super.onResume(); Settings.honorUserStop(this); refresh.post(update); }
    @Override protected void onPause() { refresh.removeCallbacks(update); super.onPause(); }
}
