import SwiftUI

/// The home feed: search, filter chips and recipe cards (web: app/page.tsx).
struct CookbookView: View {
    @Environment(RecipeStore.self) private var store
    @State private var filter = Filter.all
    @State private var query = ""
    @Namespace private var chips

    enum Filter: String, CaseIterable, Identifiable {
        case all = "All", favorites = "Favorites", tried = "Tried", untried = "To try"
        var id: Self { self }

        func matches(_ recipe: RecipeSummary) -> Bool {
            switch self {
            case .all: true
            case .favorites: recipe.favorite
            case .tried: recipe.tried
            case .untried: !recipe.tried
            }
        }
    }

    private var shown: [RecipeSummary] {
        let words = query.lowercased().split(whereSeparator: \.isWhitespace)
        return (store.recipes ?? []).filter { recipe in
            filter.matches(recipe) && words.allSatisfy { recipe.title.lowercased().contains($0) }
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    searchField.padding(.top, 32)
                    filterChips.padding(.top, 12)
                    content.padding(.top, 24)
                }
                .padding(.horizontal, 16)
                .padding(.top, 24)
                .padding(.bottom, 64)
            }
            .scrollDismissesKeyboard(.immediately)
            .background(Color.cream)
            .refreshable { await store.load() }
            .toolbar(.hidden, for: .navigationBar)
        }
        .task { if store.recipes == nil { await store.load() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Cookbook")
                .font(.serifTitle(46))
                .foregroundStyle(Color.ink)
            Text(store.recipes.map { "\($0.count) recipes saved from your reels" } ?? "Your saved recipes, all in one place")
                .foregroundStyle(Color.muted)
        }
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.subheadline)
                .foregroundStyle(Color.muted)
            TextField("Search recipes", text: $query, prompt: Text("Search recipes").foregroundStyle(Color.muted))
                .foregroundStyle(Color.ink)
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

    private var filterChips: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8) {
                ForEach(Filter.allCases) { option in
                    let selected = filter == option
                    Button {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) { filter = option }
                    } label: {
                        Text(option.rawValue)
                            .font(.subheadline)
                            .foregroundStyle(selected ? Color.white : Color.muted)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background {
                                if selected {
                                    Capsule().fill(Color.terracotta)
                                        .matchedGeometryEffect(id: "pill", in: chips)
                                }
                            }
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                }
            }
        }
        .scrollIndicators(.hidden)
        .scrollClipDisabled()
    }

    @ViewBuilder
    private var content: some View {
        if let error = store.error, store.recipes == nil {
            VStack(alignment: .leading, spacing: 12) {
                Text("Couldn't reach the recipe server (\(error)). Start it on the Mac with `uvicorn api.app:app --host 0.0.0.0 --port 8000`.")
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
                Button("Try again") { Task { await store.load() } }
                    .tint(.terracotta)
            }
            .padding(20)
            .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(Color.sand) }
        } else if store.recipes == nil {
            VStack(spacing: 12) {
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 24).fill(Color.sandSoft).frame(height: 122)
                }
            }
        } else if shown.isEmpty {
            Text(query.isEmpty
                 ? (filter == .favorites ? "Tap the heart on a recipe to keep it here." : "Nothing here yet.")
                 : "No recipes match that search.")
                .foregroundStyle(Color.muted)
                .frame(maxWidth: .infinity)
                .padding(.top, 16)
        } else {
            LazyVStack(spacing: 12) {
                ForEach(shown) { recipe in
                    RecipeCard(recipe: recipe, thumbnailURL: store.thumbnailURL(recipe.thumbnailUrl)) {
                        Task { await store.toggleFavorite(recipe.id) }
                    }
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
                }
            }
            .animation(.easeOut(duration: 0.25), value: shown.map(\.id))
        }
    }
}

#Preview {
    CookbookView().environment(RecipeStore())
}
