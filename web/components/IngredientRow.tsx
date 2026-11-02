"use client";

import { motion } from "framer-motion";

import { formatQuantity, ingredientLabel, type Ingredient } from "@/lib/api";

/** Horizontally scrolling ingredient cards; the ones the active step uses are highlighted. */
export function IngredientRow({ ingredients, active }: { ingredients: Ingredient[]; active: Set<number> }) {
  return (
    <ul className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:-mx-6 sm:px-6">
      {ingredients.map((ingredient, index) => {
        const quantity = formatQuantity(ingredient);
        const isActive = active.has(index);
        return (
          <motion.li
            key={index}
            animate={{ y: isActive ? -3 : 0 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="w-28 shrink-0 snap-start"
          >
            <div
              className={`flex aspect-square items-center justify-center rounded-2xl border p-2 text-center transition-colors duration-300 ${
                isActive ? "border-terracotta bg-terracotta-soft" : "border-sand bg-sand-soft"
              }`}
            >
              <span
                className={`font-serif leading-none ${quantity.length > 6 ? "text-xl" : "text-3xl"} ${
                  isActive ? "text-terracotta" : "text-ink/80"
                }`}
              >
                {quantity || ingredient.name.charAt(0).toUpperCase()}
              </span>
            </div>
            <p className="mt-2 text-sm leading-snug text-ink line-clamp-2">{ingredientLabel(ingredient)}</p>
          </motion.li>
        );
      })}
    </ul>
  );
}
