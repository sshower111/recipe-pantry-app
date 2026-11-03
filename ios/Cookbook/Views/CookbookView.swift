import SwiftUI

/// The home feed (web: app/page.tsx) with the pantry built into its search: typing filters by
/// title and suggests ingredients; picked ingredients re-rank the feed with GET /api/pantry
/// (the same ranking as `main.py pantry`: most picked ingredients used, then fewest others
/// needed). The filter chips apply either way.
struct CookbookView: View {
    @Environment(RecipeStore.self) private var store
    @State private var path: [Int] = []
    @State private var showSettings = false
    @State private var filter = Filter.all
    @State private var query = ""
    @FocusState private var searchFocused: Bool

    /// Picked ingredients ("what you have"), one per line; a per-phone convenience.
    @AppStorage("pantry:selected") private var savedPicks = ""
    @State private var ingredients: [PantryIngredient] = []
    /// Pantry results for the picks, by recipe id, in rank order.
    @State private var matches: [PantryMatch]?
    @State private var pantryError: String?

    /// The server's default RECIPE_PANTRY_STAPLES: never scored, so not worth suggesting.
    private static let staples: Set<String> = ["salt", "black pepper", "water", "oil"]

    /// "Cooked" is the API's `tried` mark. The raw value is the accessibility name.
    enum Filter: String, CaseIterable, Identifiable {
        case all = "All", favorites = "Favorites", cooked = "Cooked"
        var id: Self { self }

        /// What the chip shows.
        var label: String {
            switch self {
            case .all: "All"
            case .favorites: "❤️"
            case .cooked: "👌🎉"
            }
        }

        func matches(_ recipe: RecipeSummary) -> Bool {
            switch self {
            case .all: true
            case .favorites: recipe.favorite
            case .cooked: recipe.tried
            }
        }
    }

    private var picks: [String] {
        savedPicks.split(separator: "\n").map(String.init)
    }

    /// The feed: every recipe (title search), or with picks, the pantry ranking.
    private var shown: [(recipe: RecipeSummary, match: PantryMatch?)] {
        let words = query.lowercased().split(whereSeparator: \.isWhitespace)
        let recipes = store.recipes ?? []
        let ranked: [(RecipeSummary, PantryMatch?)]
        if picks.isEmpty {
            ranked = recipes.map { ($0, nil) }
        } else {
            let byId = Dictionary(uniqueKeysWithValues: recipes.map { ($0.id, $0) })
            ranked = (matches ?? []).compactMap { match in byId[match.recipeId].map { ($0, match) } }
        }
        return ranked.filter { recipe, _ in
            filter.matches(recipe) && words.allSatisfy { recipe.title.lowercased().contains($0) }
        }
    }

    /// Ingredient chips under the search box: matches for what's typed, or the most used
    /// ones while the box is focused and empty.
    private var suggestions: [PantryIngredient] {
        let words = query.lowercased().split(whereSeparator: \.isWhitespace)
        guard searchFocused || !words.isEmpty else { return [] }
        let picked = Set(picks)
        return Array(ingredients.lazy.filter { ingredient in
            !Self.staples.contains(ingredient.name) && !picked.contains(ingredient.name)
                && words.allSatisfy { ingredient.name.contains($0) }
        }.prefix(12))
    }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    searchField.padding(.top, 32)
                    ingredientChips
                    if !picks.isEmpty {
                        pickedChips.padding(.top, 14)
                    }
                    filterChips.padding(.top, 14)
                    content.padding(.top, 24)
                }
                .padding(.horizontal, 16)
                .padding(.top, 24)
                .padding(.bottom, 64)
            }
            .scrollDismissesKeyboard(.immediately)
            .background(Color.cream)
            .refreshable {
                await store.load()
                await searchPantry()
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: Int.self) { RecipeDetailView(recipeId: $0) }
        }
        .task { if store.recipes == nil { await store.load() } }
        .task { await loadIngredients() }
        // Re-rank whenever the picks change (a short pause first, for quick taps).
        .task(id: savedPicks) {
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            await searchPantry()
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        // cookbook://recipe/<id>, from tapping the Live Activity: show that recipe at its step.
        .onOpenURL { url in
            guard url.scheme == "cookbook", url.host() == "recipe", let id = Int(url.lastPathComponent) else { return }
            if path.last != id { path = [id] }
            store.stepToReveal = id
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center) {
                Text("Cookbook")
                    .font(.serifTitle(46))
                    .foregroundStyle(Color.ink)
                Spacer()
                Button("Settings", systemImage: "gearshape") { showSettings = true }
                    .labelStyle(.iconOnly)
                    .font(.system(size: 20))
                    .foregroundStyle(Color.muted)
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            Text(subtitle)
                .foregroundStyle(Color.muted)
        }
    }

    private var subtitle: String {
        guard let recipes = store.recipes else { return "Your saved recipes, all in one place" }
        if !picks.isEmpty, let matches { return "\(matches.count) recipes use what you have" }
        return "\(recipes.count) recipes saved from your reels"
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.subheadline)
                .foregroundStyle(Color.muted)
            TextField("Search recipes or add what you have", text: $query,
                      prompt: Text("Search recipes or add what you have").foregroundStyle(Color.muted))
                .foregroundStyle(Color.ink)
                .focused($searchFocused)
                .submitLabel(.search)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            if !query.isEmpty {
                Button("Clear search", systemImage: "xmark.circle.fill") { query = "" }
                    .labelStyle(.iconOnly)
                    .foregroundStyle(Color.muted)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(Color.sand) }
    }

    /// Tap to add to "You have". With text typed, the first chip adds it as written (the
    /// server normalizes it: "2 large eggs" -> egg).
    @ViewBuilder
    private var ingredientChips: some View {
        let typed = query.trimmingCharacters(in: .whitespaces).lowercased()
        let shown = suggestions
        let offerTyped = !typed.isEmpty && !picks.contains(typed) && !shown.contains { $0.name == typed }
        if offerTyped || !shown.isEmpty {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    if offerTyped {
                        chip("Add “\(typed)”", systemImage: "plus", count: nil) { addPick(typed) }
                    }
                    ForEach(shown, id: \.name) { ingredient in
                        chip(ingredient.name.prefix(1).uppercased() + ingredient.name.dropFirst(),
                             systemImage: "plus", count: ingredient.recipeCount) { addPick(ingredient.name) }
                    }
                }
            }
            .scrollIndicators(.hidden)
            .scrollClipDisabled()
            .padding(.top, 12)
        }
    }

    private func chip(_ text: String, systemImage: String, count: Int?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: systemImage).font(.system(size: 10, weight: .bold))
                Text(text).foregroundStyle(Color.ink)
                if let count { Text("\(count)").foregroundStyle(Color.muted) }
            }
            .font(.subheadline)
            .foregroundStyle(Color.terracotta)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(Color.sandSoft, in: .capsule)
        }
        .buttonStyle(.plain)
    }

    private var pickedChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("You have")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.ink)
                Spacer()
                Button("Clear") { withAnimation(.easeOut(duration: 0.2)) { savedPicks = "" } }
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
            }
            FlowLayout(spacing: 8) {
                ForEach(picks, id: \.self) { name in
                    Button {
                        withAnimation(.easeOut(duration: 0.2)) { removePick(name) }
                    } label: {
                        HStack(spacing: 6) {
                            Text(name.prefix(1).uppercased() + name.dropFirst())
                            Image(systemName: "xmark").font(.system(size: 10, weight: .bold))
                        }
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Color.terracotta, in: .capsule)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Remove \(name)")
                }
            }
        }
    }

    private var filterChips: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(Filter.allCases) { option in
                    let selected = filter == option
                    // No animation at all: a sliding pill and an animated feed both stuttered.
                    // The highlight just switches and the list swaps at once.
                    Button {
                        filter = option
                    } label: {
                        Text(option.label)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(selected ? Color.terracotta : Color.muted)
                            .frame(minWidth: 28)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(selected ? Color.terracottaSoft : Color.clear, in: .capsule)
                            .overlay { Capsule().strokeBorder(selected ? Color.terracotta : Color.sand) }
                            .contentShape(.capsule)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(option.rawValue)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .sensoryFeedback(.selection, trigger: filter)
                }
            }
            .transaction { $0.animation = nil }
        }
        .scrollIndicators(.hidden)
        .scrollClipDisabled()
    }

    @ViewBuilder
    private var content: some View {
        let shown = shown
        if let error = store.error, store.recipes == nil {
            errorBox("Couldn't reach the recipe server (\(error)). Start it on the PC with `uvicorn api.app:app --host 0.0.0.0 --port 8000`.") {
                Task { await store.load() }
            }
        } else if store.recipes == nil || (!picks.isEmpty && matches == nil && pantryError == nil) {
            VStack(spacing: 12) {
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 24).fill(Color.sandSoft).frame(height: 122)
                }
            }
        } else if !picks.isEmpty, let pantryError, matches == nil {
            errorBox("Couldn't search by ingredient (\(pantryError)).") { Task { await searchPantry() } }
        } else if shown.isEmpty {
            Text(emptyMessage)
                .foregroundStyle(Color.muted)
                .frame(maxWidth: .infinity)
                .padding(.top, 16)
        } else {
            LazyVStack(spacing: 12) {
                ForEach(shown, id: \.recipe.id) { item in
                    RecipeCard(recipe: item.recipe, thumbnailURL: store.thumbnailURL(item.recipe.thumbnailUrl),
                               match: item.match) {
                        Task { await store.toggle(.favorite, for: item.recipe.id) }
                    }
                }
            }
        }
    }

    private var emptyMessage: String {
        if !query.isEmpty { return "No recipes match that search." }
        if !picks.isEmpty { return "No recipes use those yet. Try another ingredient." }
        return filter == .favorites ? "Tap the heart on a recipe to keep it here." : "Nothing here yet."
    }

    private func errorBox(_ message: String, retry: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Color.muted)
            Button("Try again", action: retry)
                .tint(.terracotta)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(Color.sand) }
    }

    private func addPick(_ name: String) {
        query = ""
        guard !name.isEmpty, !picks.contains(name) else { return }
        withAnimation(.easeOut(duration: 0.2)) { savedPicks = (picks + [name]).joined(separator: "\n") }
    }

    private func removePick(_ name: String) {
        savedPicks = picks.filter { $0 != name }.joined(separator: "\n")
    }

    private func loadIngredients() async {
        guard ingredients.isEmpty else { return }
        ingredients = (try? await APIClient.current().ingredients()) ?? []
    }

    private func searchPantry() async {
        let have = picks
        guard !have.isEmpty else {
            matches = nil
            pantryError = nil
            return
        }
        do {
            matches = try await APIClient.current().pantry(have: have)
            pantryError = nil
        } catch {
            pantryError = error.localizedDescription
        }
    }
}

#Preview {
    CookbookView().environment(RecipeStore())
}
