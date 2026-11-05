import SwiftUI

/// The launch splash: the chef on the cream background, the app's name and its line. Shown
/// over the feed for a moment at launch (CookbookApp); the feed loads underneath meanwhile.
struct SplashScreenView: View {
    var body: some View {
        VStack(spacing: 0) {
            AnimatedChefView(.splash, size: 96)
            Text("REMNANT")
                .font(.serifTitle(40, weight: .semibold))
                .tracking(6)
                .foregroundStyle(Color.ink)
                .padding(.top, 24)
            Text("Cook with what's left")
                .font(.subheadline)
                .foregroundStyle(Color.muted)
                .padding(.top, 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.cream)
        .accessibilityElement(children: .combine)
    }
}

#Preview { SplashScreenView() }
