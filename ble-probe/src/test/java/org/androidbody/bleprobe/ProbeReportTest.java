// SPDX-License-Identifier: CC0-1.0
package org.androidbody.bleprobe;

/** Zero-dependency JVM regression checks for report rows and terminal-result acceptance. */
public final class ProbeReportTest {
    private static final String COMPLETE_REPORT = "source=org.androidbody.bleprobe/CapabilityReport\nsdk_int=21\nsampled_at_utc=2026-10-07T00:00:00.000Z\nadapter=present\nadapter_state=OFF\nle_scanner=not_tested\nle_advertiser=not_tested\nmultiple_advertisement_supported=not_tested\nlimits=capability API only\n";
    public static void main(String[] args) {
        StringBuilder rows = new StringBuilder();
        ProbeReport.appendQuery(rows, "adapter_state", () -> "OFF");
        ProbeReport.appendQuery(rows, "adapter_state", () -> "ON");
        ProbeReport.appendQuery(rows, "adapter_state", () -> { throw new SecurityException("private detail"); });
        ProbeReport.appendQuery(rows, "following_null", () -> null);
        String expected = "adapter_state=OFF\nadapter_state=ON\nadapter_state=error:SecurityException\nfollowing_null=null\n";
        if (!expected.equals(rows.toString())) throw new AssertionError("query rows mismatch: " + rows);
        check("complete", "run", "run", "complete", COMPLETE_REPORT, 60_000);
        check("missing", "", "", "complete", COMPLETE_REPORT, 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT + "extra=ignored\n", 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT + "\n", 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT.replace("sdk_int=21\n", ""), 0);
        check("missing", "run", null, null, null, 0);
        check("mismatched_run", "run", "old-run", "complete", COMPLETE_REPORT, 0);
        check("stale", "run", "run", "complete", COMPLETE_REPORT, 60_001);
        check("error", "run", "run", "error:SecurityException", null, 0);
        check("error", "run", "run", "complete", "adapter=present\n", 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT + "adapter=duplicate\n", 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT.replace("adapter=present", "adapter="), 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT.replace("source=org.androidbody.bleprobe/CapabilityReport", "source=other"), 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT.replace("sdk_int=21", "sdk_int=nonsense"), 0);
        check("error", "run", "run", "complete", COMPLETE_REPORT.replace("sampled_at_utc=2026-10-07T00:00:00.000Z", "sampled_at_utc=unknown"), 0);
        check("complete", "run", "run", "complete", COMPLETE_REPORT.replace("le_scanner=not_tested", "le_scanner=error:SecurityException"), 0);
        check("stale", "run", "run", "complete", COMPLETE_REPORT, -1);
        check("missing", "bad\nrun", "bad\nrun", "complete", COMPLETE_REPORT, 0);
        System.out.println("ProbeReport: query rows and result-boundary assertions passed");
    }
    private static void check(String want, String expectedRun, String run, String status, String report, long age) {
        String got = ProbeResult.classify(expectedRun, run, status, report, age);
        if (!want.equals(got)) throw new AssertionError("expected " + want + " but got " + got);
    }
}
