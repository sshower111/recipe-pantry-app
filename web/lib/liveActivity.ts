// Bridge to the iOS LiveActivity plugin (web/native/ios/App/LiveActivityManager.swift).
// In a normal browser every call is a no-op; only the Capacitor iOS app has the plugin.

import { Capacitor, registerPlugin } from "@capacitor/core";

/** What the Live Activity shows. Mirrors CookingActivityAttributes in Swift. */
export type LiveActivityStep = {
  recipeId: number;
  recipeTitle: string;
  /** 1-based. */
  stepNumber: number;
  totalSteps: number;
  stepText: string;
  /** Ready-made pill labels, e.g. "170 g Butter". */
  ingredients: string[];
  /** Epoch milliseconds when the step timer runs out, or null. */
  timerEndsAt: number | null;
};

type LiveActivityPlugin = {
  setSession(step: LiveActivityStep): Promise<void>;
  clearSession(): Promise<void>;
  setAutoStart(options: { enabled: boolean }): Promise<void>;
  endSession(): Promise<void>;
};

const plugin = registerPlugin<LiveActivityPlugin>("LiveActivity");

export function liveActivitySupported(): boolean {
  return Capacitor.getPlatform() === "ios" && Capacitor.isPluginAvailable("LiveActivity");
}

async function call(action: (p: LiveActivityPlugin) => Promise<void>) {
  if (!liveActivitySupported()) return;
  try {
    await action(plugin);
  } catch (error) {
    // A Live Activity is a nicety; never let it break cooking mode.
    console.warn("Live Activity:", error);
  }
}

export const liveActivity = {
  /** The step to show if the app is backgrounded (the native side starts it). */
  setSession: (step: LiveActivityStep) => call((p) => p.setSession(step)),
  /** Nothing to show: leaving the recipe, or all steps done. */
  clearSession: () => call((p) => p.clearSession()),
  setAutoStart: (enabled: boolean) => call((p) => p.setAutoStart({ enabled })),
  /** End every cooking Live Activity now. */
  endSession: () => call((p) => p.endSession()),
};
