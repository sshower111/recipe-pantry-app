"use client";

import { motion } from "framer-motion";
import { Check, Heart } from "lucide-react";
import Link from "next/link";

import type { RecipeSummary } from "@/lib/api";
import { Thumbnail } from "./Thumbnail";

export function RecipeCard({
  recipe,
  onToggleFavorite,
}: {
  recipe: RecipeSummary;
  onToggleFavorite: () => void;
}) {
  const meta = [
    `${recipe.ingredient_count} ingredients`,
    recipe.step_count ? `${recipe.step_count} steps` : null,
  ].filter(Boolean);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="relative"
    >
      <Link
        href={`/recipes/${recipe.id}`}
        className="flex items-center gap-4 rounded-3xl border border-sand bg-white/60 p-3 pr-12 transition-colors hover:bg-white focus-visible:outline-2 focus-visible:outline-terracotta"
      >
        <Thumbnail src={recipe.thumbnail_url} title={recipe.title} className="size-24 shrink-0 rounded-2xl" />
        <div className="min-w-0 py-1">
          <h2 className="font-serif text-xl leading-tight text-ink line-clamp-2">{recipe.title}</h2>
          <p className="mt-1.5 text-sm text-muted">{meta.join(" · ")}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {recipe.yield_label && (
              <span className="max-w-full truncate rounded-full bg-sand-soft px-2.5 py-0.5 text-xs text-muted">
                {recipe.yield_label}
              </span>
            )}
            {recipe.tried && (
              <span className="inline-flex items-center gap-1 rounded-full bg-terracotta-soft px-2.5 py-0.5 text-xs font-medium text-terracotta">
                <Check className="size-3" strokeWidth={2.5} />
                Tried
              </span>
            )}
          </div>
        </div>
      </Link>
      <button
        type="button"
        onClick={onToggleFavorite}
        aria-label={recipe.favorite ? "Remove from favorites" : "Add to favorites"}
        aria-pressed={recipe.favorite}
        className="absolute top-3 right-3 flex size-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-sand-soft"
      >
        <motion.span key={String(recipe.favorite)} initial={{ scale: 0.6 }} animate={{ scale: 1 }}>
          <Heart
            className={`size-[18px] ${recipe.favorite ? "fill-terracotta text-terracotta" : ""}`}
            strokeWidth={1.75}
          />
        </motion.span>
      </button>
    </motion.li>
  );
}
