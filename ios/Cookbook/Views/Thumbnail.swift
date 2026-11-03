import SwiftUI

/// The video thumbnail, or a warm placeholder with the title's initial when there is none.
struct Thumbnail: View {
    let url: URL?
    let title: String
    var initialSize: CGFloat = 30

    var body: some View {
        AsyncImage(url: url) { phase in
            if let image = phase.image {
                image.resizable().scaledToFill()
            } else if url != nil, phase.error == nil {
                Color.sandSoft
            } else {
                LinearGradient(colors: [.sandSoft, .sand], startPoint: .topLeading, endPoint: .bottomTrailing)
                    .overlay {
                        Text(title.trimmingCharacters(in: .whitespaces).prefix(1).uppercased())
                            .font(.serifTitle(initialSize))
                            .foregroundStyle(Color.muted)
                    }
            }
        }
        .accessibilityHidden(true)
    }
}
