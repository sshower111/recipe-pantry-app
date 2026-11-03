import Foundation

// Display rules shared with the web app (web/lib/api.ts, web/app/recipes/[id]/page.tsx).

extension Ingredient {
    private static let fractions: [(Double, String)] = [
        (0.125, "⅛"), (0.25, "¼"), (1.0 / 3, "⅓"), (0.5, "½"), (2.0 / 3, "⅔"), (0.75, "¾"),
    ]

    /// 1.5 -> "1½", 0.333 -> "⅓", 170 -> "170", nil -> "".
    static func formatAmount(_ amount: Double?) -> String {
        guard let amount else { return "" }
        let whole = amount.rounded(.down)
        if let (_, symbol) = fractions.first(where: { abs(amount - whole - $0.0) < 0.02 }) {
            return (whole > 0 ? String(Int(whole)) : "") + symbol
        }
        return amount.formatted(.number.precision(.fractionLength(0...2)).grouping(.never))
    }

    /// "3 tbsp", "½", or "" when the post gives no amount.
    var quantity: String {
        [Self.formatAmount(amount), unit ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// The original wording, first letter capitalised: "Garlic, minced".
    var label: String {
        let text = rawName.isEmpty ? name : rawName
        return text.prefix(1).uppercased() + text.dropFirst()
    }
}

extension Recipe {
    /// The caption without its hashtag pile.
    var caption: String {
        (description ?? "")
            .replacing(/(^|\s)#[\p{L}\p{N}_]+/, with: "")
            .replacing(/\n{3,}/, with: "\n\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
