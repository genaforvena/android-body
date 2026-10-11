// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/** Pure-Java guard decision for self-heal; testable without Android framework. */
public final class RestoreLogic {
    private RestoreLogic() {}
    /** Restore only when not clearing, desired-on, and not already running. */
    public static boolean shouldRestore(boolean clearing, boolean desiredOn, boolean running) {
        return !clearing && desiredOn && !running;
    }
}
