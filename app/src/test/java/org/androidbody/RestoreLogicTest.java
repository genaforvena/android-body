// SPDX-License-Identifier: CC0-1.0
package org.androidbody;

/** Zero-dependency JVM tests for the self-heal guard decision: run via :app:testRestore. */
public final class RestoreLogicTest {
    private static int count;
    private static void equal(Object expected, Object actual) {
        count++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    public static void main(String[] ignored) {
        // RestoreLogic.shouldRestore(clearing, desiredOn, running)
        equal(false, RestoreLogic.shouldRestore(true, true, false));   // clearing → never
        equal(false, RestoreLogic.shouldRestore(true, false, false));  // clearing → never
        equal(false, RestoreLogic.shouldRestore(false, false, false)); // not desired → never
        equal(false, RestoreLogic.shouldRestore(false, true, true));   // already running → never
        equal(true, RestoreLogic.shouldRestore(false, true, false));   // all clear → restore
        equal(false, RestoreLogic.shouldRestore(true, true, true));    // clearing + running → never
    }
}
