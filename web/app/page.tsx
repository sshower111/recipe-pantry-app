"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { RecipeCard } from "@/components/RecipeCard";
import { getRecipes, setMarks, type RecipeSummary } from "@/lib/api";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "favorites", label: "Favorites" },
  { id: "tried", label: "Tried" },
  { id: "untried", label: "To try" },
] as const;

type Filter = (typeof FILTERS)[number]["id"];

const MATCHES: Record<Filter, (r: RecipeSummary) => boolean> = {
  all: () => true,
  favorites: (r) => r.favorite,
  tried: (r) => r.tried,
  untried: (r) => !r.tried,
};

export default function CookbookPage() {
  const [recipes, setRecipes] = useState<RecipeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    getRecipes().then(setRecipes, (e: Error) => setError(e.message));
  }, []);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return (recipes ?? []).filter(
      (r) => MATCHES[filter](r) && words.every((w) => r.title.toLowerCase().includes(w)),
    );
  }, [recipes, filter, query]);

  async function toggleFavorite(recipe: RecipeSummary) {
    const favorite = !recipe.favorite;
    const update = (value: boolean) =>
      setRecipes((all) => all?.map((r) => (r.id === recipe.id ? { ...r, favorite: value } : r)) ?? null);
    update(favorite);
    try {
      await setMarks(recipe.id, { favorite });
    } catch {
      update(!favorite);
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 pt-12 pb-16 sm:px-6">
      <header>
        <h1 className="font-serif text-5xl tracking-tight text-ink">Cookbook</h1>
        <p className="mt-2 text-muted">
          {recipes ? `${recipes.length} recipes saved from your reels` : "Your saved recipes, all in one place"}
        </p>
      </header>

      <div className="mt-8 flex flex-col gap-3">
        <label className="flex items-center gap-2 rounded-2xl border border-sand bg-white/60 px-4 py-3 focus-within:border-terracotta">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search recipes"
            className="w-full bg-transparent text-ink outline-none placeholder:text-muted"
          />
        </label>
        <div role="tablist" className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          {FILTERS.map(({ id, label }) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className="relative shrink-0 rounded-full px-4 py-2 text-sm transition-colors aria-selected:text-white aria-[selected=false]:text-muted aria-[selected=false]:hover:text-ink"
            >
              {filter === id && (
                <motion.span
                  layoutId="filter-pill"
                  className="absolute inset-0 rounded-full bg-terracotta"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                />
              )}
              <span className="relative">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mt-10 rounded-2xl border border-sand bg-white/60 p-5 text-sm text-muted">
          Couldn&apos;t reach the recipe server ({error}). Start it from the project root with{" "}
          <code className="text-ink">uvicorn api.app:app --port 8000</code>.
        </p>
      )}

      {recipes === null && !error ? (
        <ul className="mt-6 flex flex-col gap-3" aria-busy>
          {Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="h-[122px] animate-pulse rounded-3xl bg-sand-soft" />
          ))}
        </ul>
      ) : (
        <ul className="mt-6 flex flex-col gap-3">
          <AnimatePresence initial={false} mode="popLayout">
            {shown.map((recipe) => (
              <RecipeCard key={recipe.id} recipe={recipe} onToggleFavorite={() => toggleFavorite(recipe)} />
            ))}
          </AnimatePresence>
        </ul>
      )}

      {recipes && !shown.length && (
        <p className="mt-10 text-center text-muted">
          {query ? "No recipes match that search." : filter === "favorites" ? "Tap the heart on a recipe to keep it here." : "Nothing here yet."}
        </p>
      )}
    </main>
  );
}
