import SwiftUI

/// Horizontally scrolling ingredient tiles; the ones the active step uses are highlighted
/// (web: components/IngredientRow.tsx).
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
        return VStack(alignment: .leading, spacing: 8) {
            Text(quantity.isEmpty ? String(ingredient.name.prefix(1)).uppercased() : quantity)
                .font(.serifTitle(quantity.count > 6 ? 20 : 30))
                .foregroundStyle(isActive ? Color.terracotta : Color.ink.opacity(0.8))
                .minimumScaleFactor(0.6)
                .lineLimit(2)
                .multilineTextAlignment(.center)
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
