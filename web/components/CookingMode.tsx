"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronLeft, PartyPopper, Timer, X } from "lucide-react";
import type { Ref } from "react";

import { formatQuantity, ingredientLabel, type Ingredient, type Step } from "@/lib/api";
import { formatClock, formatDuration } from "@/lib/stepTimer";

import type { IslandTimer } from "./DynamicIslandStep";

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Step-by-step focus mode: one step at a time with just the ingredients it uses, plus an
 * overview list where finished steps fade back.
 */
export function CookingMode({
  steps,
  ingredients,
  active,
  direction,
  done,
  tried,
  timer,
  duration,
  focusRef,
  onSelect,
  onToggleDone,
  onCompleteStep,
  onMarkTried,
  onStartTimer,
  onCancelTimer,
}: {
  steps: Step[];
  ingredients: Ingredient[];
  active: number;
  /** 1 when moving forward, -1 when moving back; picks the slide direction. */
  direction: number;
  done: Set<number>;
  tried: boolean;
  timer: IslandTimer;
  /** Seconds the active step mentions, if any. */
  duration: number | null;
  /** The step card, so the page can tell when it has scrolled out of view. */
  focusRef: Ref<HTMLDivElement>;
  onSelect: (index: number) => void;
  onToggleDone: (index: number) => void;
  onCompleteStep: () => void;
  onMarkTried: () => void;
  onStartTimer: () => void;
  onCancelTimer: () => void;
}) {
  const allDone = done.size === steps.length;
  const step = steps[active];
  const isLast = active === steps.length - 1;
  const timerHere = timer !== null && timer.step === active;

  return (
    <div>
      <div className="flex gap-1.5" aria-hidden>
        {steps.map((_, i) => (
          <button
            key={i}
            type="button"
            tabIndex={-1}
            onClick={() => onSelect(i)}
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-sand"
          >
            <motion.span
              className="block h-full rounded-full bg-terracotta"
              initial={false}
              animate={{ width: done.has(i) ? "100%" : i === active ? "40%" : "0%", opacity: done.has(i) ? 0.45 : 1 }}
              transition={{ duration: 0.35, ease: "easeOut" }}
            />
          </button>
        ))}
      </div>

      <div ref={focusRef} className="relative mt-5 min-h-64 overflow-hidden rounded-3xl border border-sand bg-white/70 p-6">
        <AnimatePresence mode="wait" initial={false} custom={direction}>
          {allDone ? (
            <motion.div
              key="finished"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex min-h-52 flex-col items-center justify-center text-center"
            >
              <PartyPopper className="size-8 text-terracotta" strokeWidth={1.5} />
              <p className="mt-3 font-serif text-3xl text-ink">All done. Enjoy!</p>
              <p className="mt-1 text-sm text-muted">You finished all {steps.length} steps.</p>
              {!tried && (
                <button
                  type="button"
                  onClick={onMarkTried}
                  className="mt-5 rounded-full bg-terracotta px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                >
                  Mark as tried
                </button>
              )}
            </motion.div>
          ) : (
            <motion.div
              key={active}
              custom={direction}
              variants={{
                enter: (d: number) => ({ opacity: 0, x: d * 40 }),
                center: { opacity: 1, x: 0 },
                exit: (d: number) => ({ opacity: 0, x: d * -40 }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.28, ease: [0.32, 0.72, 0, 1] }}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-serif text-6xl leading-none text-terracotta">{pad(active + 1)}</span>
                <span className="text-sm text-muted">
                  Step {active + 1} of {steps.length}
                </span>
              </div>
              <p className={`mt-5 text-xl leading-relaxed text-ink ${done.has(active) ? "opacity-40" : ""}`}>
                {step.text}
              </p>
              {step.ingredients.length > 0 && (
                <ul className="mt-5 flex flex-wrap gap-2" aria-label="Ingredients for this step">
                  {step.ingredients.map((i, n) => (
                    <motion.li
                      key={i}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.12 + n * 0.04 }}
                      className="rounded-full bg-sand-soft px-3.5 py-1.5 text-sm text-ink"
                    >
                      {formatQuantity(ingredients[i]) && (
                        <span className="font-medium">{formatQuantity(ingredients[i])} </span>
                      )}
                      {ingredientLabel(ingredients[i])}
                    </motion.li>
                  ))}
                </ul>
              )}
              {timerHere ? (
                <button
                  type="button"
                  onClick={onCancelTimer}
                  aria-label="Cancel timer"
                  className={`mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-full border px-4 text-sm tabular-nums ${
                    timer.remaining <= 0 ? "border-terracotta text-terracotta" : "border-sand text-ink"
                  }`}
                >
                  <Timer className="size-4" />
                  {timer.remaining <= 0 ? "Time’s up" : formatClock(timer.remaining)}
                  <X className="size-4 text-muted" />
                </button>
              ) : (
                duration && (
                  <button
                    type="button"
                    onClick={onStartTimer}
                    className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-full border border-sand px-4 text-sm text-ink transition-colors hover:border-terracotta"
                  >
                    <Timer className="size-4" />
                    Start {formatDuration(duration)} timer
                  </button>
                )
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {!allDone && (
        <div className="mt-4 flex gap-3">
          <button
            type="button"
            onClick={() => onSelect(active - 1)}
            disabled={active === 0}
            aria-label="Previous step"
            className="flex size-12 shrink-0 items-center justify-center rounded-full border border-sand bg-white/70 text-ink transition-opacity disabled:opacity-30"
          >
            <ChevronLeft className="size-5" />
          </button>
          <button
            type="button"
            onClick={onCompleteStep}
            className="flex h-12 flex-1 items-center justify-center gap-2 rounded-full bg-terracotta font-medium text-white transition-opacity hover:opacity-90"
          >
            <Check className="size-4" strokeWidth={2.5} />
            {isLast ? "Finish" : "Done, next step"}
          </button>
        </div>
      )}

      <ol className="mt-8 divide-y divide-sand border-t border-sand">
        {steps.map((s, i) => {
          const isDone = done.has(i);
          const isActive = i === active && !allDone;
          return (
            <motion.li
              key={i}
              layout="position"
              className={`flex items-start gap-4 py-4 transition-opacity duration-300 ${
                isDone && !isActive ? "opacity-40" : ""
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(i)}
                className="flex min-w-0 flex-1 items-start gap-4 text-left"
                aria-current={isActive ? "step" : undefined}
              >
                <span
                  className={`w-9 shrink-0 font-serif text-2xl leading-none transition-colors ${
                    isActive ? "text-terracotta" : "text-ink/70"
                  }`}
                >
                  {pad(i + 1)}
                </span>
                <span className={`text-[15px] leading-relaxed text-ink ${isActive ? "" : "line-clamp-2"}`}>
                  {s.text}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onToggleDone(i)}
                aria-label={isDone ? `Mark step ${i + 1} not done` : `Mark step ${i + 1} done`}
                aria-pressed={isDone}
                className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border transition-colors ${
                  isDone ? "border-terracotta bg-terracotta text-white" : "border-sand bg-white"
                }`}
              >
                {isDone && <Check className="size-3.5" strokeWidth={3} />}
              </button>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}
