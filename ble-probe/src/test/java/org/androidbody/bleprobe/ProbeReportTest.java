// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

/** Zero-dependency JVM regression test for one-key API result rows. */
public final class ProbeReportTest {
    public static void main(String[] args) {
        StringBuilder report = new StringBuilder();
        ProbeReport.appendQuery(report, "adapter_state", () -> "OFF");
        ProbeReport.appendQuery(report, "adapter_state", () -> "ON");
        ProbeReport.appendQuery(report, "adapter_state", () -> {
            throw new SecurityException("permission denied");
        });
        ProbeReport.appendQuery(report, "le_scanner", () -> "object available");
        ProbeReport.appendQuery(report, "le_advertiser", () -> {
            throw new SecurityException("permission denied");
        });
        ProbeReport.appendQuery(report, "multiple_advertisement_supported", () -> "false");
        ProbeReport.appendQuery(report, "following_null", () -> null);
        String expected = "adapter_state=OFF\n"
                + "adapter_state=ON\n"
                + "adapter_state=error:SecurityException\n"
                + "le_scanner=object available\n"
                + "le_advertiser=error:SecurityException\n"
                + "multiple_advertisement_supported=false\n"
                + "following_null=null\n";
        if (!expected.equals(report.toString())) {
            throw new AssertionError("Expected one complete row per query; got: " + report);
        }
        System.out.println("ProbeReport: adapter-state and query boundary assertions passed");
    }
}
