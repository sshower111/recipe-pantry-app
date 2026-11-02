"use client";

import { motion } from "framer-motion";
import { ArrowLeft, Check, ExternalLink, Heart, Play, Square } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { CookingMode } from "@/components/CookingMode";
import { DynamicIslandStep } from "@/components/DynamicIslandStep";
import { FloatingVideo } from "@/components/FloatingVideo";
import { IngredientRow } from "@/components/IngredientRow";
import { LiveActivityToggle } from "@/components/LiveActivityToggle";
import { Thumbnail } from "@/components/Thumbnail";
import { formatQuantity, getRecipe, ingredientLabel, setMarks, type Marks, type Recipe } from "@/lib/api";
import type { LiveActivityStep } from "@/lib/liveActivity";
import { stepDuration, type StepTimer } from "@/lib/stepTimer";
import { useLiveActivity } from "@/lib/useLiveActivity";

const PLATFORM_NAMES = { instagram: "Instagram", youtube: "YouTube", tiktok: "TikTok" } as const;

type Progress = { active: number; done: number[] };

// Step progress is a per-device convenience, so it lives in localStorage (which may be unavailable).
function loadProgress(id: string): Progress {
  try {
    const saved = JSON.parse(localStorage.getItem(`progress:${id}`) ?? "null");
    if (saved && typeof saved.active === "number" && Array.isArray(saved.done)) return saved;
  } catch {}
  return { active: 0, done: [] };
}

function saveProgress(id: string, progress: Progress) {
  try {
    localStorage.setItem(`progress:${id}`, JSON.stringify(progress));
  } catch {}
}

/** The Live Activity payload for the active step, or null when there is nothing to follow. */
function liveActivityStep(recipe: Recipe | null, progress: Progress, timer: StepTimer | null): LiveActivityStep | null {
  const step = recipe?.steps[progress.active];
  if (!recipe || !step || progress.done.length === recipe.steps.length) return null;
  return {
    recipeId: recipe.id,
    recipeTitle: recipe.title,
    stepNumber: progress.active + 1,
    totalSteps: recipe.steps.length,
    stepText: step.text,
    ingredients: step.ingredients.map((i) =>
      [formatQuantity(recipe.ingredients[i]), ingredientLabel(recipe.ingredients[i])].filter(Boolean).join(" "),
    ),
    timerEndsAt: timer && timer.step === progress.active ? timer.endsAt : null,
  };
}

/** The caption without its hashtag pile. */
function cleanDescription(text: string | null): string {
  return (text ?? "")
    .replace(/(^|\s)#[\p{L}\p{N}_]+/gu, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export default function RecipePage() {
  const { id } = useParams<{ id: string }>();
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFullDescription, setShowFullDescription] = useState(false);
  const [videoOpen, setVideoOpen] = useState(false);
  const [progress, setProgress] = useState<Progress>({ active: 0, done: [] });
  const [direction, setDirection] = useState(1);
  const [timer, setTimer] = useState<StepTimer | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const focusRef = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLElement>(null);
  const [inView, setInView] = useState({ focus: true, hero: true, focusAbove: false });

  useEffect(() => {
    getRecipe(id).then(
      (r) => {
        setRecipe(r);
        const saved = loadProgress(id);
        setProgress({
          active: Math.min(saved.active, Math.max(r.steps.length - 1, 0)),
          done: saved.done.filter((i) => i < r.steps.length),
        });
      },
      (e: Error) => setError(e.message),
    );
  }, [id]);

  const done = useMemo(() => new Set(progress.done), [progress.done]);

  // Track the step card and the hero, to know when the island should take over.
  const hasSteps = Boolean(recipe?.steps.length);
  useEffect(() => {
    const card = focusRef.current;
    const hero = heroRef.current;
    if (!card || !hero) return;
    const observer = new IntersectionObserver((entries) => {
      setInView((state) => {
        const next = { ...state };
        for (const entry of entries) {
          if (entry.target === card) {
            next.focus = entry.isIntersecting;
            next.focusAbove = !entry.isIntersecting && entry.boundingClientRect.top < 0;
          } else {
            next.hero = entry.isIntersecting;
          }
        }
        return next;
      });
    });
    observer.observe(card);
    observer.observe(hero);
    return () => observer.disconnect();
  }, [hasSteps]);

  useEffect(() => {
    if (!timer) return;
    const tick = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(tick);
  }, [timer]);

  const live = useLiveActivity(liveActivityStep(recipe, progress, timer));

  function updateProgress(next: Progress) {
    setDirection(next.active >= progress.active ? 1 : -1);
    setProgress(next);
    saveProgress(id, next);
  }

  async function toggleMark(key: keyof Marks) {
    if (!recipe) return;
    const value = !recipe[key];
    setRecipe({ ...recipe, [key]: value });
    try {
      await setMarks(recipe.id, { [key]: value });
    } catch {
      setRecipe((r) => (r ? { ...r, [key]: !value } : r));
    }
  }

  if (error) {
    return (
      <main className="mx-auto max-w-xl px-4 pt-16 text-center">
        <p className="font-serif text-3xl">{error === "Not found" ? "Recipe not found" : "Couldn’t load this recipe"}</p>
        <p className="mt-2 text-muted">{error}</p>
        <Link href="/" className="mt-6 inline-block text-terracotta underline underline-offset-4">
          Back to cookbook
        </Link>
      </main>
    );
  }

  if (!recipe) {
    return (
      <main className="mx-auto max-w-xl px-4 pt-4" aria-busy>
        <div className="aspect-[4/5] max-h-[62vh] w-full animate-pulse rounded-[2rem] bg-sand-soft" />
        <div className="mt-6 h-10 w-2/3 animate-pulse rounded-xl bg-sand-soft" />
      </main>
    );
  }

  const steps = recipe.steps;
  const allDone = done.size === steps.length;
  const duration = steps[progress.active] ? stepDuration(steps[progress.active].text) : null;
  const islandTimer = timer && { step: timer.step, remaining: (timer.endsAt - now) / 1000 };

  // Shared by the step card and the island, so both always show the same step.
  const selectStep = (i: number) =>
    updateProgress({ ...progress, active: Math.max(0, Math.min(i, steps.length - 1)) });
  const completeStep = () => {
    const nextDone = done.has(progress.active) ? progress.done : [...progress.done, progress.active];
    const nextOpen = steps.findIndex((_, i) => i > progress.active && !nextDone.includes(i));
    updateProgress({ active: nextOpen === -1 ? progress.active : nextOpen, done: nextDone });
  };
  const startTimer = () => {
    if (!duration) return;
    const start = Date.now();
    setNow(start);
    setTimer({ step: progress.active, total: duration, endsAt: start + duration * 1000 });
  };
  const cookingStarted = progress.active > 0 || done.size > 0 || timer !== null;
  const endCookingSession = () => {
    live.endSession(liveActivityStep(recipe, progress, null));
    setTimer(null);
  };

  const description = cleanDescription(recipe.description);
  const activeStep = recipe.steps[progress.active];
  const activeIngredients = new Set(activeStep && done.size < recipe.steps.length ? activeStep.ingredients : []);
  const platform = recipe.video.platform ? PLATFORM_NAMES[recipe.video.platform] : null;
  const pills = [
    recipe.yield_label,
    `${recipe.ingredients.length} ingredients`,
    recipe.steps.length ? `${recipe.steps.length} steps` : null,
  ].filter(Boolean) as string[];

  return (
    <main className="mx-auto w-full max-w-xl pb-28">
      <section ref={heroRef} className="relative px-3 pt-3">
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="overflow-hidden rounded-[2rem]"
        >
          <Thumbnail
            src={recipe.thumbnail_url}
            title={recipe.title}
            className="aspect-[4/5] max-h-[62vh] w-full"
            initialClassName="text-8xl"
          />
        </motion.div>
        <div className="absolute inset-x-6 top-6 flex justify-between">
          <Link
            href="/"
            aria-label="Back to cookbook"
            className="flex size-12 items-center justify-center rounded-2xl border border-white/60 bg-white/85 text-ink shadow-sm backdrop-blur transition-colors hover:bg-white"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <button
            type="button"
            onClick={() => toggleMark("favorite")}
            aria-label={recipe.favorite ? "Remove from favorites" : "Add to favorites"}
            aria-pressed={recipe.favorite}
            className="flex size-12 items-center justify-center rounded-2xl border border-white/60 bg-white/85 text-ink shadow-sm backdrop-blur transition-colors hover:bg-white"
          >
            <motion.span key={String(recipe.favorite)} initial={{ scale: 0.6 }} animate={{ scale: 1 }}>
              <Heart className={`size-5 ${recipe.favorite ? "fill-terracotta text-terracotta" : ""}`} strokeWidth={1.75} />
            </motion.span>
          </button>
        </div>
      </section>

      <div className="px-4 sm:px-6">
        <section className="pt-7">
          <h1 className="font-serif text-4xl leading-[1.1] tracking-tight text-ink sm:text-5xl">{recipe.title}</h1>
          {recipe.uploader && <p className="mt-2 text-sm text-muted">by {recipe.uploader}</p>}

          {description && (
            <div className="mt-4">
              <p className={`whitespace-pre-line text-[15px] leading-relaxed text-muted ${showFullDescription ? "" : "line-clamp-3"}`}>
                {description}
              </p>
              <button
                type="button"
                onClick={() => setShowFullDescription((s) => !s)}
                className="mt-1 text-sm font-medium text-ink underline underline-offset-4"
              >
                {showFullDescription ? "See less" : "See more"}
              </button>
            </div>
          )}

          <ul className="mt-5 flex flex-wrap gap-2">
            {pills.map((pill) => (
              <li key={pill} className="rounded-full border border-sand px-3 py-1 text-sm text-ink">
                {pill}
              </li>
            ))}
          </ul>

          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => toggleMark("tried")}
              aria-pressed={recipe.tried}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium transition-colors ${
                recipe.tried
                  ? "bg-terracotta-soft text-terracotta"
                  : "border border-sand bg-white/70 text-ink hover:border-terracotta"
              }`}
            >
              <Check className="size-4" strokeWidth={2.5} />
              {recipe.tried ? "Tried it" : "Mark as tried"}
            </button>
            {recipe.video.embed_url && (
              <button
                type="button"
                onClick={() => setVideoOpen(true)}
                className="inline-flex items-center gap-2 rounded-full border border-sand bg-white/70 px-4 py-2.5 text-sm font-medium text-ink transition-colors hover:border-terracotta"
              >
                <Play className="size-4 fill-current" />
                Watch video
              </button>
            )}
            {!recipe.video.embed_url && (
              <a
                href={recipe.video.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-full border border-sand bg-white/70 px-4 py-2.5 text-sm font-medium text-ink"
              >
                <ExternalLink className="size-4" />
                {platform ? `Open on ${platform}` : "Open original"}
              </a>
            )}
            {steps.length > 0 && (
              <LiveActivityToggle enabled={live.autoStart} supported={live.supported} onChange={live.setAutoStart} />
            )}
          </div>
        </section>

        <section className="mt-10">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="font-serif text-3xl text-ink">Ingredients</h2>
            <span className="text-sm text-muted">{recipe.ingredients.length} items</span>
          </div>
          <IngredientRow ingredients={recipe.ingredients} active={activeIngredients} />
          {recipe.recipe_page_url && (
            <a
              href={recipe.recipe_page_url}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex items-center gap-1.5 text-sm text-muted underline underline-offset-4"
            >
              Full recipe page <ExternalLink className="size-3.5" />
            </a>
          )}
        </section>

        <section className="mt-12">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-serif text-3xl text-ink">Cooking Steps</h2>
            {recipe.video.embed_url && !videoOpen && (
              <button
                type="button"
                onClick={() => setVideoOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full bg-terracotta-soft px-3 py-1.5 text-sm font-medium text-terracotta"
              >
                <Play className="size-3.5 fill-current" />
                Video
              </button>
            )}
          </div>
          {recipe.steps.length ? (
            <CookingMode
              steps={recipe.steps}
              ingredients={recipe.ingredients}
              active={progress.active}
              direction={direction}
              done={done}
              tried={recipe.tried}
              timer={islandTimer}
              duration={duration}
              focusRef={focusRef}
              onSelect={selectStep}
              onToggleDone={(i) =>
                updateProgress({
                  ...progress,
                  done: done.has(i) ? progress.done.filter((d) => d !== i) : [...progress.done, i],
                })
              }
              onCompleteStep={completeStep}
              onMarkTried={() => toggleMark("tried")}
              onStartTimer={startTimer}
              onCancelTimer={() => setTimer(null)}
            />
          ) : (
            <p className="rounded-3xl border border-sand bg-white/60 p-5 text-muted">
              The post doesn&apos;t describe the method.{" "}
              {recipe.video.embed_url ? "Watch the video to follow along." : ""}
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
            {cookingStarted && live.sessionActive && (
              <button
                type="button"
                onClick={endCookingSession}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-sand bg-white/70 px-4 text-sm font-medium text-ink transition-colors hover:border-terracotta"
              >
                <Square className="size-3.5 fill-current" />
                End cooking session
              </button>
            )}
            {done.size > 0 && (
              <button
                type="button"
                onClick={() => updateProgress({ active: 0, done: [] })}
                className="text-sm text-muted underline underline-offset-4"
              >
                Start over
              </button>
            )}
          </div>
        </section>
      </div>

      {steps.length > 0 && (
        <DynamicIslandStep
          visible={
            !allDone &&
            // A running timer always shows (the pill is then narrow enough to sit between
            // the hero's buttons); otherwise only once the step card is off screen and the
            // hero is scrolled away: below the card, or above it after cooking has started.
            (timer !== null ||
              (!inView.focus && !inView.hero && (inView.focusAbove || progress.active > 0 || done.size > 0)))
          }
          steps={steps}
          ingredients={recipe.ingredients}
          active={progress.active}
          done={done}
          timer={islandTimer}
          duration={duration}
          onPrevious={() => selectStep(progress.active - 1)}
          onCompleteStep={completeStep}
          onStartTimer={startTimer}
          onCancelTimer={() => setTimer(null)}
        />
      )}

      <FloatingVideo video={recipe.video} open={videoOpen} onClose={() => setVideoOpen(false)} />
    </main>
  );
}
