import SwiftUI

/// Colors and fonts from the web app (`web/app/globals.css`).
extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }

    static let cream = Color(hex: 0xFAF8F5)          // background
    static let sand = Color(hex: 0xE6E2DD)           // cards, borders
    static let sandSoft = Color(hex: 0xF1EDE8)       // tiles
    static let terracotta = Color(hex: 0xC86D51)     // accent, active
    static let terracottaSoft = Color(hex: 0xF6E4DD) // active fills
    static let ink = Color(hex: 0x2B2622)            // text
    static let muted = Color(hex: 0x8A817A)
    static let heart = Color(hex: 0xB0272B)           // filled favorite heart (deeper than terracotta)
    static let heartOutline = Color(hex: 0x9A9089)    // empty heart: a touch lighter than muted
    static let softWhite = Color(hex: 0xF3EFEA)       // icons over photos: warm, not pure white
}

extension Font {
    /// Garamond-style titles; the system serif until EB Garamond is bundled.
    static func serifTitle(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }
}
