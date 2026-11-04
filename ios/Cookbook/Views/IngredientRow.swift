import SwiftUI

/// Horizontally scrolling ingredient tiles; the ones the active step uses are highlighted.
struct IngredientRow: View {
    let ingredients: [Ingredient]
    var active: Set<Int> = []

    var body: some View {
        ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: 12) {
                ForEach(Array(ingredients.enumerated()), id: \.offset) { index, ingredient in
                    tile(ingredient, isActive: active.contains(index))
                }
            }
            .scrollTargetLayout()
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
        }
        .scrollIndicators(.hidden)
        .scrollTargetBehavior(.viewAligned)
    }

    private func tile(_ ingredient: Ingredient, isActive: Bool) -> some View {
        let quantity = ingredient.quantity
        let tint = isActive ? Color.terracotta : Color.ink.opacity(0.8)
        return VStack(alignment: .leading, spacing: 8) {
            Group {
                if let icon = IngredientIcon.asset(for: ingredient.name) {
                    // A black-and-white icon (no ingredient photos exist), the amount under it.
                    VStack(spacing: 8) {
                        Image(icon)
                            .renderingMode(.template)
                            .resizable()
                            .scaledToFit()
                            .frame(width: quantity.isEmpty ? 48 : 40, height: quantity.isEmpty ? 48 : 40)
                        if !quantity.isEmpty {
                            Text(quantity)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
                        }
                    }
                } else {
                    // No icon fits ("aromatic"): the amount alone, as before.
                    Text(quantity.isEmpty ? String(ingredient.name.prefix(1)).uppercased() : quantity)
                        .font(.serifTitle(quantity.count > 6 ? 20 : 30))
                        .minimumScaleFactor(0.6)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
            }
            .foregroundStyle(tint)
                .padding(8)
                .frame(width: 112, height: 112)
                .background(isActive ? Color.terracottaSoft : Color.sandSoft, in: .rect(cornerRadius: 16))
                .overlay {
                    RoundedRectangle(cornerRadius: 16)
                        .strokeBorder(isActive ? Color.terracotta : Color.sand)
                }
            Text(ingredient.label)
                .font(.subheadline)
                .foregroundStyle(Color.ink)
                .lineLimit(2)
                .frame(width: 112, alignment: .leading)
        }
        .offset(y: isActive ? -3 : 0)
        .animation(.spring(response: 0.3, dampingFraction: 0.8), value: isActive)
        .accessibilityElement(children: .combine)
    }
}
