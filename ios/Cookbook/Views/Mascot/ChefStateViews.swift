import SwiftUI

/// The chef above a short title and message: empty lists, the end of a recipe, errors.
struct ChefStateView<Actions: View>: View {
    let animation: ChefAnimation
    let title: String
    var message: String?
    var size: CGFloat = 72
    @ViewBuilder var actions: Actions

    var body: some View {
        VStack(spacing: 8) {
            AnimatedChefView(animation, size: size)
            Text(title)
                .font(.serifTitle(24))
                .foregroundStyle(Color.ink)
                .multilineTextAlignment(.center)
                .padding(.top, 4)
            if let message {
                Text(message)
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            actions.padding(.top, 8)
        }
        .frame(maxWidth: .infinity)
    }
}

extension ChefStateView where Actions == EmptyView {
    init(animation: ChefAnimation, title: String, message: String? = nil, size: CGFloat = 72) {
        self.init(animation: animation, title: title, message: message, size: size) { EmptyView() }
    }
}

/// ❤️ with no favorites yet.
struct EmptyFavoritesView: View {
    var body: some View {
        ChefStateView(animation: .empty, title: "No favorites yet",
                      message: "Tap the heart on a recipe to keep it here.")
    }
}

/// A recipe the PC couldn't read or that couldn't be loaded.
struct ParseErrorView<Actions: View>: View {
    var title = "Couldn't read this recipe"
    let message: String
    @ViewBuilder var actions: Actions

    var body: some View {
        ChefStateView(animation: .error, title: title, message: message) { actions }
    }
}

/// The chef cooking while a recipe loads or a shared video is read on the PC.
struct ChefLoadingView: View {
    var title = "Loading the recipe…"
    var message: String?

    var body: some View {
        ChefStateView(animation: .loading, title: title, message: message, size: 80)
    }
}

/// Shown at the top of the feed while a pull-to-refresh runs (in place of the system spinner,
/// which CookbookApp makes clear).
struct RefreshingChefView: View {
    var body: some View {
        HStack(spacing: 10) {
            AnimatedChefView(.refresh, size: 48)
            Text("Checking the PC for new recipes…")
                .font(.footnote.weight(.medium))
                .foregroundStyle(Color.muted)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    ScrollView {
        VStack(spacing: 40) {
            RefreshingChefView()
            ChefLoadingView()
            EmptyFavoritesView()
            ChefStateView(animation: .success, title: "All done. Enjoy!")
            ParseErrorView(message: "The video had no ingredient list.") { Button("Try again") {} }
        }
        .padding()
    }
    .background(Color.cream)
}
