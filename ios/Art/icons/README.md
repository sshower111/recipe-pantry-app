# Ingredient icons

Black-and-white line icons for the ingredient tiles, from three open sets (licenses alongside):

- `healthicons/`: [Health Icons](https://healthicons.org) outline icons, CC0 1.0 (public domain):
  cow, pig, chicken, duck, sugar, dairy, vegetables, fruits, gluten (wheat), carbohydrates
  (bread), alcohol.
- `tabler/`: [Tabler Icons](https://tabler.io/icons) `@tabler/icons@3.19.0` outline, MIT:
  salt, pepper (chili), bottle (sauce), egg, fish, grain (powders), cheese.
- `lucide/`: [Lucide](https://lucide.dev) `lucide-static@0.460.0`, ISC: droplet, glass-water,
  soup, nut, bean, coffee, cookie, cake-slice, ice-cream-bowl, leaf (herbs).

The app's copies are `ios/Cookbook/Assets.xcassets/Ingredients/ing-<key>.imageset` (template
images; `currentColor` set to black, and Tabler/Lucide strokes thinned from 2 to 1.25 so their
weight matches Health Icons' at the tile size). `Cookbook/Models/IngredientIcon.swift` maps
ingredient names to the keys.
