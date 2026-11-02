// Types and calls for the FastAPI server in ../api (proxied at /api by next.config.ts).

export type Platform = "instagram" | "youtube" | "tiktok" | null;

export type RecipeSummary = {
  id: number;
  title: string;
  uploader: string | null;
  yield_label: string | null;
  status: string | null;
  ingredient_count: number;
  step_count: number;
  favorite: boolean;
  tried: boolean;
  thumbnail_url: string | null;
  platform: Platform;
};

export type Ingredient = {
  name: string;
  raw_name: string;
  amount: number | null;
  unit: string | null;
};

export type Step = {
  text: string;
  /** Indexes into the recipe's ingredients. */
  ingredients: number[];
};

export type Recipe = {
  id: number;
  title: string;
  uploader: string | null;
  description: string | null;
  yield_label: string | null;
  status: string | null;
  favorite: boolean;
  tried: boolean;
  thumbnail_url: string | null;
  recipe_page_url: string | null;
  video: { url: string; platform: Platform; embed_url: string | null };
  ingredients: Ingredient[];
  steps: Step[];
};

export type Marks = { favorite: boolean; tried: boolean };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new Error(response.status === 404 ? "Not found" : `Server error (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const getRecipes = () => request<RecipeSummary[]>("/api/recipes");

export const getRecipe = (id: number | string) => request<Recipe>(`/api/recipes/${id}`);

export const setMarks = (id: number, marks: Partial<Marks>) =>
  request<Marks>(`/api/recipes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(marks),
  });

const FRACTIONS: [number, string][] = [
  [0.125, "⅛"], [0.25, "¼"], [1 / 3, "⅓"], [0.5, "½"], [2 / 3, "⅔"], [0.75, "¾"],
];

/** 1.5 -> "1½", 0.333 -> "⅓", 170 -> "170". */
export function formatAmount(amount: number | null): string {
  if (amount === null) return "";
  const whole = Math.floor(amount);
  const fraction = FRACTIONS.find(([value]) => Math.abs(amount - whole - value) < 0.02);
  if (fraction) return `${whole || ""}${fraction[1]}`;
  return String(Math.round(amount * 100) / 100);
}

export function formatQuantity(ingredient: Ingredient): string {
  return [formatAmount(ingredient.amount), ingredient.unit].filter(Boolean).join(" ");
}

/** "Garlic, minced" for display: the original wording, first letter capitalised. */
export function ingredientLabel(ingredient: Ingredient): string {
  const text = ingredient.raw_name || ingredient.name;
  return text.charAt(0).toUpperCase() + text.slice(1);
}
