// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

import android.app.Instrumentation;
import android.os.Bundle;
import android.util.Base64;

/** Self-targeted, non-persistent diagnostic result channel. */
public final class ProbeInstrumentation extends Instrumentation {
    public static final String ARG_RUN_ID = "run_id";
    public static final String KEY_RUN_ID = "run_id";
    public static final String KEY_STATUS = "status";
    public static final String KEY_REPORT_B64 = "report_b64";
    private Bundle launchArguments;

    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        launchArguments = arguments == null ? new Bundle() : new Bundle(arguments);
        start();
    }

    @Override public void onStart() {
        String runId = launchArguments.getString(ARG_RUN_ID);
        Bundle result = new Bundle();
        if (runId == null || !runId.matches("[A-Za-z0-9_-]{1,64}")) {
            result.putString(KEY_STATUS, "error:invalid_run_id");
        } else {
            result.putString(KEY_RUN_ID, runId);
            try {
                String report = CapabilityReport.collect(getTargetContext());
                result.putString(KEY_REPORT_B64, Base64.encodeToString(
                        report.getBytes(java.nio.charset.Charset.forName("UTF-8")), Base64.NO_WRAP));
                result.putString(KEY_STATUS, "complete");
            } catch (RuntimeException error) {
                result.putString(KEY_STATUS, "error:" + error.getClass().getSimpleName());
            }
        }
        finish(0, result);
    }
}
