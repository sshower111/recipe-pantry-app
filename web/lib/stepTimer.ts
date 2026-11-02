// Kitchen timers taken from a step's own wording ("Bake for 28-32 minutes").

const DURATION =
  /(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b/i;

const UNIT_SECONDS: Record<string, number> = { h: 3600, m: 60, s: 1 };

/** Seconds for the first duration a step mentions (the low end of a range), or null. */
export function stepDuration(text: string): number | null {
  const match = DURATION.exec(text);
  if (!match) return null;
  const seconds = Math.round(parseFloat(match[1]) * UNIT_SECONDS[match[2][0].toLowerCase()]);
  return seconds > 0 ? seconds : null;
}

/** 90 -> "1:30", 3700 -> "1:01:40". */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  const parts = [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60];
  const [, m, sec] = parts.map((n) => String(n).padStart(2, "0"));
  return parts[0] ? `${parts[0]}:${m}:${sec}` : `${parts[1]}:${sec}`;
}

/** 1200 -> "20 min", 5400 -> "1 h 30 min", 45 -> "45 s". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return [h ? `${h} h` : "", m ? `${m} min` : ""].filter(Boolean).join(" ");
}

export type StepTimer = { step: number; total: number; endsAt: number };
