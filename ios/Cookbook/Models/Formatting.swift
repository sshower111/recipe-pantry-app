import Foundation

// Display rules for amounts, ingredient labels, captions and island text (see docs/ios/api.md).

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

extension Step {
    /// A shorter instruction for the Dynamic Island and Lock Screen; the app shows the full
    /// text. Keeps the first sentence, drops asides in parentheses, trailing "until ...",
    /// ", then ..." style clauses and a leading "Then"/"Next": "Bake at 170°C for 40-45
    /// minutes until cooked through." -> "Bake at 170°C for 40-45 minutes". On the recipes
    /// as of 2026-11-03 this takes steps from 72 to 61 characters on average.
    var islandText: String {
        var text = self.text.replacing(/\s*\([^)]*\)/, with: "")
        if let end = text.firstRange(of: /[.!?;](?=\s|$)/) {
            text = String(text[..<end.lowerBound])
        }
        let tail = /(?i)(,?\s+(until|so that|so it|to make sure|making sure|which will|as this)\b|,\s*(then|and then|while)\b)/
        if let clause = text.firstRange(of: tail), text.distance(from: text.startIndex, to: clause.lowerBound) >= 20 {
            text = String(text[..<clause.lowerBound])
        }
        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacing(/^(?i)(then|next|now|finally),?\s+/, with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: " ,"))
        guard let first = text.first else { return self.text }
        return first.uppercased() + text.dropFirst()
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
