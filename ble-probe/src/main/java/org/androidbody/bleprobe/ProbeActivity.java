// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

import android.app.Activity;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** A read-only capability diagnostic. It never starts discovery, scanning, or advertising. */
public final class ProbeActivity extends Activity {
    private TextView report;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (24 * getResources().getDisplayMetrics().density);
        column.setPadding(padding, padding, padding, padding);
        TextView title = new TextView(this);
        title.setText(R.string.title);
        column.addView(title);
        Button refresh = new Button(this);
        refresh.setText(R.string.refresh);
        column.addView(refresh);
        report = new TextView(this);
        report.setTextIsSelectable(true);
        column.addView(report, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(column);
        setContentView(scroll);
        refresh.setOnClickListener(view -> refreshReport());
        refreshReport();
    }

    private void refreshReport() {
        report.setText(CapabilityReport.collect(this));
    }
}
