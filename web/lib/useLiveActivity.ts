"use client";

import { useEffect, useState } from "react";

import { liveActivity, liveActivitySupported, type LiveActivityStep } from "./liveActivity";

const AUTO_START_KEY = "liveActivity:autoStart";

function loadAutoStart(): boolean {
  try {
    return localStorage.getItem(AUTO_START_KEY) !== "false";
  } catch {
    return true;
  }
}

/** The step and timer, ignoring wording: what "the user moved on" means for a session. */
const positionKey = (step: LiveActivityStep) => `${step.recipeId}:${step.stepNumber}:${step.timerEndsAt}`;

/**
 * Keeps the native Live Activity session in step with cooking mode.
 *
 * `step` is what to show if the app is backgrounded (null: nothing, e.g. all steps done).
 * The native side starts and ends the activity itself on background/foreground; this hook
 * only feeds it the current step, the user's on/off switch, and "End cooking session".
 * After ending, nothing is sent again until the user moves to another step or timer.
 */
export function useLiveActivity(step: LiveActivityStep | null) {
  const [supported, setSupported] = useState(false);
  const [autoStart, setAutoStartState] = useState(true);
  const [endedAt, setEndedAt] = useState<string | null>(null);

  // Read after mount: the Capacitor bridge and localStorage only exist in the browser.
  useEffect(() => {
    setSupported(liveActivitySupported());
    setAutoStartState(loadAutoStart());
  }, []);

  useEffect(() => {
    if (supported) liveActivity.setAutoStart(autoStart);
  }, [supported, autoStart]);

  const key = step && positionKey(step);
  const sessionActive = step !== null && key !== endedAt;
  const payload = JSON.stringify(step);

  useEffect(() => {
    if (!supported) return;
    if (sessionActive && autoStart) liveActivity.setSession(JSON.parse(payload));
    else liveActivity.clearSession();
  }, [supported, sessionActive, autoStart, payload]);

  // Leaving the recipe page ends the session.
  useEffect(() => () => void liveActivity.clearSession(), []);

  function setAutoStart(enabled: boolean) {
    setAutoStartState(enabled);
    try {
      localStorage.setItem(AUTO_START_KEY, String(enabled));
    } catch {}
  }

  /** `next` is the step as it will be once the caller has finished ending (say, with its
   * timer cleared), so that change doesn't count as moving on. */
  function endSession(next: LiveActivityStep | null = step) {
    setEndedAt(next && positionKey(next));
    liveActivity.endSession();
  }

  return { supported, autoStart, setAutoStart, sessionActive, endSession };
}
