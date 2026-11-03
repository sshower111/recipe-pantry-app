import SwiftUI

/// One row of the cookbook feed (web: components/RecipeCard.tsx). Opens the recipe;
/// the heart sits above the link so tapping it doesn't navigate.
struct RecipeCard: View {
    let recipe: RecipeSummary
    let thumbnailURL: URL?
    let onToggleFavorite: () -> Void

    private var meta: String {
        var parts = ["\(recipe.ingredientCount) ingredients"]
        if recipe.stepCount > 0 { parts.append("\(recipe.stepCount) steps") }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        NavigationLink(value: recipe.id) { card }
            .buttonStyle(.plain)
            .overlay(alignment: .topTrailing) { heart }
    }

    private var card: some View {
        HStack(spacing: 16) {
            Thumbnail(url: thumbnailURL, title: recipe.title)
                .frame(width: 96, height: 96)
                .clipShape(.rect(cornerRadius: 16))

            VStack(alignment: .leading, spacing: 6) {
                Text(recipe.title)
                    .font(.serifTitle(20))
                    .foregroundStyle(Color.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(meta)
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
                if recipe.yieldLabel != nil || recipe.tried {
                    HStack(spacing: 6) {
                        if let yieldLabel = recipe.yieldLabel {
                            Pill(text: yieldLabel)
                        }
                        if recipe.tried {
                            Pill(text: "Tried", systemImage: "checkmark", foreground: .terracotta, background: .terracottaSoft)
                        }
                    }
                }
            }
            .padding(.vertical, 4)
            .padding(.trailing, 36)  // room for the heart
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Color.white.opacity(0.6), in: .rect(cornerRadius: 24))
        .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
        .contentShape(.rect(cornerRadius: 24))
    }

    private var heart: some View {
        Button(action: onToggleFavorite) {
            Image(systemName: recipe.favorite ? "heart.fill" : "heart")
                .font(.system(size: 17, weight: .medium))
                .symbolRenderingMode(.monochrome)
                .foregroundStyle(recipe.favorite ? Color.heart : Color.heartOutline)
                .symbolEffect(.bounce, value: recipe.favorite)
                .frame(width: 36, height: 36)
                .contentShape(.circle)
                .overlay { HeartBurst(isFavorite: recipe.favorite) }
        }
        .buttonStyle(.plain)
        .padding(12)
        .accessibilityLabel(recipe.favorite ? "Remove from favorites" : "Add to favorites")
        .sensoryFeedback(.selection, trigger: recipe.favorite)
    }
}

/// Small rounded label: a yield ("serves 4") or a status ("Tried").
struct Pill: View {
    let text: String
    var systemImage: String?
    var foreground: Color = .muted
    var background: Color = .sandSoft

    var body: some View {
        HStack(spacing: 4) {
            if let systemImage {
                Image(systemName: systemImage).font(.system(size: 10, weight: .bold))
            }
            Text(text).lineLimit(1)
        }
        .font(.caption.weight(systemImage == nil ? .regular : .medium))
        .foregroundStyle(foreground)
        .padding(.horizontal, 10)
        .padding(.vertical, 3)
        .background(background, in: .capsule)
    }
}
