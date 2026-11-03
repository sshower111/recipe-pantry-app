import SwiftUI

/// One recipe: hero, title, caption, pills, actions, ingredients and steps
/// (web: app/recipes/[id]/page.tsx).
struct RecipeDetailView: View {
    let recipeId: Int
    @Environment(RecipeStore.self) private var store
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @State private var error: String?
    @State private var showFullCaption = false
    /// Cooking progress; the Live Activity's ‹ › buttons can move it while the app is away.
    @State private var session: CookingSession?

    private static let platformNames = ["instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok"]

    var body: some View {
        Group {
            if let recipe = store.details[recipeId] {
                content(recipe)
            } else if let error {
                ContentUnavailableView {
                    Label("Couldn't load this recipe", systemImage: "fork.knife")
                } description: {
                    Text(error)
                } actions: {
                    Button("Try again") { Task { await load() } }
                        .tint(.terracotta)
                }
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.cream)
        // The bar's heart can clip its own animation, so the burst sits on the page, lined
        // up under the trailing toolbar button.
        .overlay(alignment: .topTrailing) {
            if let recipe = store.details[recipeId] {
                HeartBurst(isFavorite: recipe.favorite)
                    .frame(width: 44, height: 44)
                    .padding(.trailing, 16)
                    .offset(y: -44)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            if let recipe = store.details[recipeId] {
                ToolbarItem(placement: .topBarTrailing) {
                    // A custom label, not Button(_:systemImage:): the bar draws standard
                    // toolbar symbols with a translucent tint, and the filled heart must be solid.
                    Button {
                        Task { await store.toggle(.favorite, for: recipeId) }
                    } label: {
                        Image(systemName: recipe.favorite ? "heart.fill" : "heart")
                            .symbolRenderingMode(.monochrome)
                            .fontWeight(.medium)
                            .foregroundStyle(recipe.favorite ? Color.heart : Color.heartOutline)
                            .symbolEffect(.bounce, value: recipe.favorite)
                    }
                    .tint(recipe.favorite ? Color.heart : Color.heartOutline)
                    .accessibilityLabel(recipe.favorite ? "Remove from favorites" : "Add to favorites")
                    .sensoryFeedback(.selection, trigger: recipe.favorite)
                }
            }
        }
        .tint(.ink)
        // Refresh on every visit (steps may have been re-parsed on the PC); cached copy shows meanwhile.
        .task { await load() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { session?.reload() }
        }
    }

    private func load() async {
        do {
            try await store.loadRecipe(recipeId)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        updateSession()
    }

    /// One session per visit; a fresh one only if a re-parse on the PC changed the steps.
    private func updateSession() {
        guard let recipe = store.details[recipeId] else { return }
        if let session, session.steps == recipe.steps {
            session.reload()
        } else {
            session = CookingSession(recipe: recipe)
        }
    }

    private func content(_ recipe: Recipe) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    hero(recipe)
                    header(recipe)
                        .padding(.horizontal, 16)
                        .padding(.top, 28)
                    ingredients(recipe)
                        .padding(.top, 40)
                    steps(recipe)
                        .padding(.horizontal, 16)
                        .padding(.top, 48)
                }
                .padding(.bottom, 64)
            }
            // Opened from the Live Activity: jump to the step card, which shows its step.
            .onChange(of: store.stepToReveal, initial: true) { _, id in
                guard id == recipeId, !recipe.steps.isEmpty else { return }
                store.stepToReveal = nil
                updateSession()
                Task {
                    try? await Task.sleep(for: .milliseconds(350))  // let the push finish first
                    withAnimation(.easeInOut(duration: 0.4)) {
                        proxy.scrollTo(CookingModeView.focusID, anchor: .top)
                    }
                }
            }
        }
    }

    private func hero(_ recipe: Recipe) -> some View {
        Color.sandSoft
            .aspectRatio(4 / 5, contentMode: .fit)
            .overlay { Thumbnail(url: store.thumbnailURL(recipe.thumbnailUrl), title: recipe.title, initialSize: 96) }
            .clipShape(.rect(cornerRadius: 32))
            .padding(.horizontal, 12)
    }

    private func header(_ recipe: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(recipe.title)
                .font(.serifTitle(36))
                .foregroundStyle(Color.ink)
            if let uploader = recipe.uploader {
                Text("by \(uploader)")
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
                    .padding(.top, 8)
            }

            let caption = recipe.caption
            if !caption.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(caption)
                        .font(.callout)
                        .foregroundStyle(Color.muted)
                        .lineLimit(showFullCaption ? nil : 3)
                        .lineSpacing(3)
                    Button(showFullCaption ? "See less" : "See more") {
                        withAnimation(.easeOut(duration: 0.2)) { showFullCaption.toggle() }
                    }
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.ink)
                    .underline()
                }
                .padding(.top, 16)
            }

            FlowLayout(spacing: 8) {
                ForEach(pills(recipe), id: \.self) { pill in
                    Text(pill)
                        .font(.subheadline)
                        .foregroundStyle(Color.ink)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 5)
                        .overlay { Capsule().strokeBorder(Color.sand) }
                }
            }
            .padding(.top, 20)

            FlowLayout(spacing: 8) {
                triedButton(recipe)
                watchButton(recipe)
            }
            .padding(.top, 20)
        }
    }

    private func pills(_ recipe: Recipe) -> [String] {
        [recipe.yieldLabel,
         "\(recipe.ingredients.count) ingredients",
         recipe.steps.isEmpty ? nil : "\(recipe.steps.count) steps"].compactMap { $0 }
    }

    private func triedButton(_ recipe: Recipe) -> some View {
        Button {
            Task { await store.toggle(.tried, for: recipeId) }
        } label: {
            Label(recipe.tried ? "Tried it" : "Mark as tried", systemImage: "checkmark")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(recipe.tried ? Color.terracotta : Color.ink)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(recipe.tried ? Color.terracottaSoft : Color.white.opacity(0.7), in: .capsule)
                .overlay { Capsule().strokeBorder(recipe.tried ? Color.clear : Color.sand) }
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: recipe.tried) { _, tried in tried }
    }

    /// Starts the Live Activity on the current step, then opens the post in its app
    /// (Instagram etc.) or the browser, so the step follows along in the Dynamic Island.
    @ViewBuilder
    private func watchButton(_ recipe: Recipe) -> some View {
        if let url = URL(string: recipe.video.url) {
            let platform = recipe.video.platform.flatMap { Self.platformNames[$0] }
            Button {
                Task {
                    await LiveActivityController.start(recipe)
                    openURL(url)
                }
            } label: {
                Label(platform.map { "Watch on \($0)" } ?? "Open original", systemImage: "play.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.ink)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.white.opacity(0.7), in: .capsule)
                    .overlay { Capsule().strokeBorder(Color.sand) }
            }
            .buttonStyle(.plain)
        }
    }

    private func ingredients(_ recipe: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                Text("Ingredients")
                    .font(.serifTitle(30))
                    .foregroundStyle(Color.ink)
                Spacer()
                Text("\(recipe.ingredients.count) items")
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
            }
            .padding(.horizontal, 16)

            IngredientRow(ingredients: recipe.ingredients, active: session?.activeIngredients ?? [])

            if let page = recipe.recipePageUrl.flatMap(URL.init(string:)) {
                Link(destination: page) {
                    Label("Full recipe page", systemImage: "arrow.up.right.square")
                        .font(.subheadline)
                        .foregroundStyle(Color.muted)
                        .underline()
                }
                .padding(.horizontal, 16)
            }
        }
    }

    /// Cooking mode; the step in focus is the one the Dynamic Island follows.
    private func steps(_ recipe: Recipe) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Cooking Steps")
                .font(.serifTitle(30))
                .foregroundStyle(Color.ink)

            if recipe.steps.isEmpty {
                Text("The post doesn't describe the method. Watch the video to follow along.")
                    .foregroundStyle(Color.muted)
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 24))
                    .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
            } else if let session {
                CookingModeView(session: session, ingredients: recipe.ingredients, tried: recipe.tried) {
                    Task { await store.toggle(.tried, for: recipeId) }
                }
            }
        }
    }
}
