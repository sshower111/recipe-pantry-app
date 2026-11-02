"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronLeft, ChevronUp, Timer, X } from "lucide-react";
import { useEffect, useState } from "react";

import { formatQuantity, ingredientLabel, type Ingredient, type Step } from "@/lib/api";
import { formatClock, formatDuration } from "@/lib/stepTimer";

const pad = (n: number) => String(n).padStart(2, "0");
const SPRING = { type: "spring", stiffness: 420, damping: 36 } as const;

export type IslandTimer = { step: number; remaining: number } | null;

/**
 * A Dynamic Island-style bar pinned to the top of the screen while the step card is out
 * of view. Collapsed it shows the step number and the running timer (or a step summary);
 * tapped it opens into a card with the step, its ingredients and previous/next controls.
 * All state lives in the recipe page, so it moves in step with the main cooking mode.
 */
export function DynamicIslandStep({
  visible,
  steps,
  ingredients,
  active,
  done,
  timer,
  duration,
  onPrevious,
  onCompleteStep,
  onStartTimer,
  onCancelTimer,
}: {
  visible: boolean;
  steps: Step[];
  ingredients: Ingredient[];
  active: number;
  done: Set<number>;
  timer: IslandTimer;
  /** Seconds the active step mentions, if any. */
  duration: number | null;
  onPrevious: () => void;
  onCompleteStep: () => void;
  onStartTimer: () => void;
  onCancelTimer: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [direction, setDirection] = useState(1);
  const [shownStep, setShownStep] = useState(active);

  // Slide the step text the way the step moved, wherever the change came from.
  if (shownStep !== active) {
    setDirection(active > shownStep ? 1 : -1);
    setShownStep(active);
  }

  useEffect(() => {
    if (!expanded) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);

  const isOpen = visible && expanded;
  const step = steps[active];
  const counter = `${pad(active + 1)}/${pad(steps.length)}`;
  const timesUp = timer !== null && timer.remaining <= 0;
  const timerHere = timer !== null && timer.step === active;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-40 flex justify-center px-3">
      <AnimatePresence onExitComplete={() => setExpanded(false)}>
        {visible && (
          <motion.div
            layout
            key="island"
            initial={{ opacity: 0, y: -24, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -24, scale: 0.9 }}
            transition={SPRING}
            style={{ borderRadius: isOpen ? 32 : 28 }}
            className={`pointer-events-auto overflow-hidden bg-[#000000] text-white shadow-xl shadow-ink/30 ${
              isOpen ? "w-full max-w-[420px]" : ""
            }`}
          >
            <AnimatePresence mode="popLayout" initial={false}>
              {isOpen ? (
                <motion.div
                  key="expanded"
                  layout="position"
                  initial={{ opacity: 0, filter: "blur(6px)" }}
                  animate={{ opacity: 1, filter: "blur(0px)" }}
                  exit={{ opacity: 0, filter: "blur(6px)" }}
                  transition={{ duration: 0.2 }}
                  className="p-5"
                >
                  <button
                    type="button"
                    onClick={() => setExpanded(false)}
                    aria-expanded
                    aria-label="Collapse step bar"
                    className="-mt-1 flex min-h-[44px] w-full items-center justify-between text-left"
                  >
                    <span className="text-sm text-white/60">
                      Step <span className="font-medium text-white tabular-nums">{counter}</span>
                    </span>
                    <ChevronUp className="size-5 text-white/60" />
                  </button>

                  <div className="mt-3 flex gap-1" aria-hidden>
                    {steps.map((_, i) => (
                      <span
                        key={i}
                        className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
                          i === active ? "bg-terracotta" : done.has(i) ? "bg-terracotta/45" : "bg-white/15"
                        }`}
                      />
                    ))}
                  </div>

                  <AnimatePresence mode="wait" initial={false} custom={direction}>
                    <motion.div
                      key={active}
                      custom={direction}
                      variants={{
                        enter: (d: number) => ({ opacity: 0, x: d * 24 }),
                        center: { opacity: 1, x: 0 },
                        exit: (d: number) => ({ opacity: 0, x: d * -24 }),
                      }}
                      initial="enter"
                      animate="center"
                      exit="exit"
                      transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
                    >
                      <p
                        className={`mt-4 text-lg leading-relaxed transition-opacity ${done.has(active) ? "opacity-40" : ""}`}
                      >
                        {step.text}
                      </p>
                      {step.ingredients.length > 0 && (
                        <ul className="mt-4 flex flex-wrap gap-2" aria-label="Ingredients for this step">
                          {step.ingredients.map((i) => (
                            <li key={i} className="rounded-full bg-white/10 px-3 py-1.5 text-sm text-white/90">
                              {formatQuantity(ingredients[i]) && (
                                <span className="font-medium text-white">{formatQuantity(ingredients[i])} </span>
                              )}
                              {ingredientLabel(ingredients[i])}
                            </li>
                          ))}
                        </ul>
                      )}
                    </motion.div>
                  </AnimatePresence>

                  <div className="mt-5 flex gap-2">
                    <button
                      type="button"
                      onClick={onPrevious}
                      disabled={active === 0}
                      aria-label="Previous step"
                      className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-white/10 transition-opacity disabled:opacity-30"
                    >
                      <ChevronLeft className="size-5" />
                    </button>
                    {timerHere ? (
                      <button
                        type="button"
                        onClick={onCancelTimer}
                        aria-label="Cancel timer"
                        className={`flex min-h-[44px] items-center gap-1.5 rounded-full bg-white/10 px-4 text-sm tabular-nums ${
                          timesUp ? "text-terracotta" : ""
                        }`}
                      >
                        {timesUp ? "Time's up" : formatClock(timer.remaining)}
                        <X className="size-4 text-white/60" />
                      </button>
                    ) : (
                      duration && (
                        <button
                          type="button"
                          onClick={onStartTimer}
                          className="flex min-h-[44px] items-center gap-1.5 rounded-full bg-white/10 px-4 text-sm"
                        >
                          <Timer className="size-4" />
                          {formatDuration(duration)}
                        </button>
                      )
                    )}
                    <button
                      type="button"
                      onClick={onCompleteStep}
                      className="flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-full bg-terracotta text-sm font-medium transition-opacity hover:opacity-90"
                    >
                      <Check className="size-4" strokeWidth={2.5} />
                      {active === steps.length - 1 ? "Finish" : "Next"}
                    </button>
                  </div>
                </motion.div>
              ) : (
                <motion.button
                  key="collapsed"
                  type="button"
                  layout="position"
                  onClick={() => setExpanded(true)}
                  aria-expanded={false}
                  aria-label={`Step ${active + 1} of ${steps.length}. Show step`}
                  initial={{ opacity: 0, filter: "blur(6px)" }}
                  animate={{ opacity: 1, filter: "blur(0px)" }}
                  exit={{ opacity: 0, filter: "blur(6px)" }}
                  transition={{ duration: 0.2 }}
                  className="flex min-h-[44px] items-center gap-3 py-1.5 pr-4 pl-1.5"
                >
                  <span className="flex h-8 items-center rounded-full bg-terracotta px-3 text-sm font-medium tabular-nums">
                    Step {counter}
                  </span>
                  {timer ? (
                    <span
                      className={`flex items-center gap-1.5 text-sm tabular-nums ${timesUp ? "text-terracotta" : ""}`}
                    >
                      <Timer className="size-4" />
                      {timesUp ? "Time's up" : formatClock(timer.remaining)}
                    </span>
                  ) : (
                    <span className="max-w-[46vw] truncate text-sm text-white/80 sm:max-w-[220px]">{step.text}</span>
                  )}
                </motion.button>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
