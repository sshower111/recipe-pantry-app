import SwiftUI
import UIKit

/// One recipe: hero, title, caption, pills, actions, ingredients and steps.
struct RecipeDetailView: View {
    let recipeId: Int
    @Environment(RecipeStore.self) private var store
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase
    @State private var error: String?
    @State private var showFullCaption = false
    /// Cooking progress; the Live Activity's ‹ › buttons can move it while the app is away.
    @State private var session: CookingSession?
    /// Where cooking mode's step card is: the pop-up only comes out once it's been scrolled
    /// past going down (reading the step list), not while above it (photo, ingredients).
    @State private var cardPosition = CookingModeView.CardPosition.onScreen
    /// The pop-up copy of the step card: out only while scrolling away from the real one.
    @State private var showStepBar = false
    @State private var hideStepBar: Task<Void, Never>?
    @State private var lastScrollY: CGFloat?
    /// "Check again" sent and not yet confirmed by the PC (no recipe yet posts).
    @State private var checkRequested = false
    @State private var checkError: String?
    /// ▶ found no app for the post (e.g. Instagram not installed): offer Safari instead.
    @State private var appMissing: AppMissing?

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
                            .foregroundStyle(recipe.favorite ? Color.heart : Color.softWhite)
                            .shadow(color: .black.opacity(0.3), radius: 1.5, y: 0.5)  // readable on light photos
                            .symbolEffect(.bounce, value: recipe.favorite)
                    }
                    .tint(recipe.favorite ? Color.heart : Color.softWhite)
                    .accessibilityLabel(recipe.favorite ? "Remove from favorites" : "Add to favorites")
                    .sensoryFeedback(.selection, trigger: recipe.favorite)
                }
            }
        }
        .alert(item: $appMissing) { missing in
            Alert(title: Text("\(missing.name) isn't installed"),
                  message: Text("The video opens in the \(missing.name) app so you stay signed in. Install it, or open the post in Safari, which may ask you to sign in."),
                  primaryButton: .default(Text("Open in Safari")) { openURL(missing.url) },
                  secondaryButton: .cancel())
        }
        // The system back arrow takes the tint: soft white over the photo, like the heart.
        .tint(.softWhite)
        // Refresh on every visit (steps may have been re-parsed on the PC); cached copy shows meanwhile.
        .task { await load() }
        // Back to the cookbook: leaving the app no longer starts the island for this recipe.
        .onDisappear {
            if LiveActivityController.onScreen?.id == recipeId { LiveActivityController.onScreen = nil }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { session?.reload() }
        }
    }

    /// Scrolling below the step card (it's above the screen): pop up its copy until a moment
    /// after the scrolling stops.
    private func scrolled() {
        guard cardPosition == .above, session?.steps.isEmpty == false else { return }
        setStepBar(true)
    }

    /// Shows the pop-up card (and restarts its countdown to tuck away) or hides it now.
    private func setStepBar(_ show: Bool) {
        hideStepBar?.cancel()
        if show != showStepBar {
            withAnimation(.snappy(duration: 0.25)) { showStepBar = show }
        }
        guard show else { return }
        hideStepBar = Task {
            try? await Task.sleep(for: .seconds(2))  // a full card takes a moment to read
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.3)) { showStepBar = false }
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
        LiveActivityController.onScreen = recipe
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
                    if recipe.ingredients.isEmpty {
                        noRecipeYet(recipe)
                            .padding(.horizontal, 16)
                            .padding(.top, 32)
                    } else {
                        ingredients(recipe)
                            .padding(.top, 40)
                        steps(recipe)
                            .padding(.horizontal, 16)
                            .padding(.top, 48)
                    }
                }
                .padding(.bottom, 64)
                // Any scroll movement (iOS 17 has no scroll-phase signal) pops the line up.
                .onGeometryChange(for: CGFloat.self) { $0.frame(in: .scrollView).minY } action: { y in
                    // Only real movement: not the first layout when the screen opens.
                    if let last = lastScrollY, abs(y - last) > 2 { scrolled() }
                    lastScrollY = y
                }
            }
            .overlay(alignment: .top) {
                // The same step card as on the page (same size, look and controls), on an opaque
                // cream backing so it reads over the content. 6 + 10 pt of padding keeps the card
                // itself exactly as wide as the page's (16 pt margins).
                if showStepBar, let session, !session.steps.isEmpty, !session.allDone {
                    StepCard(session: session, ingredients: recipe.ingredients, tried: recipe.tried,
                             onMarkTried: { Task { await store.toggle(.tried, for: recipeId) } },
                             onInteract: { setStepBar(true) }, showsHint: false, compact: true)
                        .padding(10)
                        .background(Color.cream, in: .rect(cornerRadius: 32))
                        .overlay { RoundedRectangle(cornerRadius: 32).strokeBorder(Color.sand) }
                        .shadow(color: Color.ink.opacity(0.16), radius: 18, y: 6)
                        .padding(.horizontal, 6)
                        .padding(.top, 4)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
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
            .overlay { Thumbnail(url: store.thumbnailURL(recipe.thumbnailUrl), title: recipe.title, initialSize: 96, maxPoints: 500) }
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
                if !recipe.ingredients.isEmpty { triedButton(recipe) }  // nothing to cook yet
                watchButton(recipe)
            }
            .padding(.top, 20)
        }
    }

    private func pills(_ recipe: Recipe) -> [String] {
        if recipe.ingredients.isEmpty { return ["No recipe yet"] }
        return [recipe.yieldLabel,
                "\(recipe.ingredients.count) ingredients",
                recipe.steps.isEmpty ? nil : "\(recipe.steps.count) steps"].compactMap { $0 }
    }

    /// A post kept without a recipe (🔖 Saved): Check again re-reads it on the PC, for when the
    /// creator adds the recipe to the caption or links it. Recipes posted only in the comments
    /// still can't be read (yt-dlp gets few comments signed out; see CLAUDE.md).
    private func noRecipeYet(_ recipe: Recipe) -> some View {
        let checking = store.ingestJobs.contains { $0.isActive && $0.recipeId == recipe.id }
            || checkRequested
        let kept = recipe.status == "needs_recipe"
        return VStack(alignment: .leading, spacing: 12) {
            Label("No recipe yet", systemImage: "bookmark")
                .font(.serifTitle(26))
                .foregroundStyle(Color.ink)
            Text(kept
                 ? "Kept in 🔖 for later. When the creator adds the recipe to the caption or links it, Check again reads the post again."
                 : "This post has no ingredient list. If the recipe is coming, save it for later and check again then.")
                .font(.callout)
                .foregroundStyle(Color.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let note = checkError {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(Color.heart)
            }
            HStack(spacing: 10) {
                Button {
                    checkError = nil
                    checkRequested = true
                    Task {
                        do { try await store.checkAgain(recipe) } catch {
                            checkError = store.offlineSince != nil
                                ? "Checking again needs the PC, which is out of reach right now."
                                : "Couldn't ask the PC: \(error.localizedDescription)"
                        }
                        checkRequested = false
                    }
                } label: {
                    HStack(spacing: 8) {
                        if checking { ProgressView().tint(.white) } else { Image(systemName: "arrow.clockwise") }
                        Text(checking ? "Checking on your PC…" : "Check again")
                    }
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .frame(minHeight: 44)
                    .background(Color.terracotta, in: .capsule)
                }
                .buttonStyle(.plain)
                .disabled(checking)

                Button(kept ? "Remove from 🔖" : "Save for later") {
                    Task { try? await store.setStatus(kept ? "not_recipe" : "needs_recipe", for: recipe.id) }
                }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.ink)
                .padding(.horizontal, 16)
                .frame(minHeight: 44)
                .overlay { Capsule().strokeBorder(Color.sand) }
                .buttonStyle(.plain)
            }
            .padding(.top, 4)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 24))
        .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
    }

    /// Mark as cooked and ▶ share one height.
    private static let actionHeight: CGFloat = 40

    private func triedButton(_ recipe: Recipe) -> some View {
        Button {
            Task { await store.toggle(.tried, for: recipeId) }
        } label: {
            Label(recipe.tried ? "Cooked it" : "Mark as cooked", systemImage: "checkmark")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(recipe.tried ? Color.terracotta : Color.ink)
                .padding(.horizontal, 16)
                .frame(height: Self.actionHeight)
                .background(recipe.tried ? Color.terracottaSoft : Color.white.opacity(0.7), in: .capsule)
                .overlay { Capsule().strokeBorder(recipe.tried ? Color.clear : Color.sand) }
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: recipe.tried) { _, tried in tried }
    }

    /// ▶: starts the Live Activity on the current step, then opens the post in its app
    /// (Instagram etc.), so the step follows along in the Dynamic Island. Only the app: a
    /// browser asks people to sign in, so without the app installed it asks first.
    @ViewBuilder
    private func watchButton(_ recipe: Recipe) -> some View {
        if let url = URL(string: recipe.video.url) {
            let platform = recipe.video.platform.flatMap { Self.platformNames[$0] }
            Button {
                Task {
                    await LiveActivityController.start(recipe)
                    let opened = await UIApplication.shared.open(url, options: [.universalLinksOnly: true])
                    if !opened {
                        await LiveActivityController.endAll()  // still here: no island needed
                        appMissing = AppMissing(name: platform ?? "the post's app", url: url)
                    }
                }
            } label: {
                // Same look and height as Mark as cooked, beside it.
                Image(systemName: "play.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.ink)
                    .padding(.horizontal, 18)
                    .frame(height: Self.actionHeight)
                    .background(Color.white.opacity(0.7), in: .capsule)
                    .overlay { Capsule().strokeBorder(Color.sand) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(platform.map { "Watch on \($0)" } ?? "Watch the video")
        }
    }

    struct AppMissing: Identifiable {
        let name: String
        let url: URL
        var id: String { url.absoluteString }
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
                CookingModeView(session: session, ingredients: recipe.ingredients, tried: recipe.tried,
                                onMarkTried: { Task { await store.toggle(.tried, for: recipeId) } },
                                onCardPosition: { position in
                                    cardPosition = position
                                    if position != .above { setStepBar(false) }
                                })
            }
        }
    }
}
