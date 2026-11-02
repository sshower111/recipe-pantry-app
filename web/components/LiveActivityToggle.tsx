"use client";

import { motion } from "framer-motion";

/**
 * The "Dynamic Island" switch in the recipe action bar. On: leaving the iOS app shows the
 * current step on the Lock Screen and Dynamic Island. Off: it never starts.
 */
export function LiveActivityToggle({
  enabled,
  supported,
  onChange,
}: {
  enabled: boolean;
  /** False in a normal browser, where the switch is only a saved preference. */
  supported: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      onClick={() => onChange(!enabled)}
      title={
        supported
          ? "Show the current step on your Lock Screen and Dynamic Island when you leave the app"
          : "Works in the iOS app: shows the current step on your Lock Screen and Dynamic Island"
      }
      className={`inline-flex items-center gap-2.5 rounded-full py-2.5 pr-4 pl-2.5 text-sm font-medium transition-colors ${
        enabled ? "bg-terracotta-soft text-terracotta" : "border border-sand bg-white/70 text-muted hover:border-terracotta"
      }`}
    >
      <span
        aria-hidden
        className={`flex h-5 w-9 items-center rounded-full p-0.5 transition-colors ${
          enabled ? "justify-end bg-terracotta" : "justify-start bg-sand"
        }`}
      >
        <motion.span layout transition={{ type: "spring", stiffness: 600, damping: 35 }} className="size-4 rounded-full bg-white shadow-sm" />
      </span>
      Dynamic Island
    </button>
  );
}
