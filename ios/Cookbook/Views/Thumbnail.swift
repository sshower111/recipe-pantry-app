import ImageIO
import SwiftUI
import UIKit

/// The video thumbnail, or a warm placeholder with the title's initial when there is none.
///
/// Thumbnails are 150-350 KB photos; decoding them at full size on the main thread made
/// scrolling and screen transitions stutter. They're decoded at the size they're drawn
/// (`maxPoints`), off the main thread, and kept in memory.
struct Thumbnail: View {
    let url: URL?
    let title: String
    let initialSize: CGFloat
    /// The longest side it's drawn at, in points.
    let maxPoints: CGFloat
    @Environment(\.displayScale) private var displayScale
    @State private var image: UIImage?
    @State private var failed = false

    init(url: URL?, title: String, initialSize: CGFloat = 30, maxPoints: CGFloat = 96) {
        self.url = url
        self.title = title
        self.initialSize = initialSize
        self.maxPoints = maxPoints
        // Already decoded (e.g. the card came back after a filter switch): draw it in the
        // first frame instead of flashing the placeholder.
        _image = State(initialValue: url.flatMap { ThumbnailCache.image(for: $0, points: maxPoints) })
    }

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else if url == nil || failed {
                LinearGradient(colors: [.sandSoft, .sand], startPoint: .topLeading, endPoint: .bottomTrailing)
                    .overlay {
                        Text(title.trimmingCharacters(in: .whitespaces).prefix(1).uppercased())
                            .font(.serifTitle(initialSize))
                            .foregroundStyle(Color.muted)
                    }
            } else {
                Color.sandSoft
            }
        }
        .accessibilityHidden(true)
        .task(id: url) { await load() }
    }

    private func load() async {
        guard let url else { return }
        let pixels = maxPoints * displayScale
        if let cached = ThumbnailCache.image(for: url, points: maxPoints) {
            image = cached
            return
        }
        do {
            // Photos rarely change: once downloaded, URLCache (200 MB on disk) serves them,
            // which also keeps them working offline.
            let request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 8)
            let (data, _) = try await URLSession.shared.data(for: request)
            let decoded = await Task.detached(priority: .userInitiated) {
                ThumbnailCache.downsample(data, maxPixels: pixels)
            }.value
            guard !Task.isCancelled else { return }
            if let decoded {
                ThumbnailCache.store(decoded, for: url, points: maxPoints)
                image = decoded
            } else {
                failed = true
            }
        } catch {
            if !Task.isCancelled { failed = true }
        }
    }
}

/// Decoded thumbnails by URL and size, in memory (iOS empties it under memory pressure).
enum ThumbnailCache {
    private static let cache: NSCache<NSString, UIImage> = {
        let cache = NSCache<NSString, UIImage>()
        cache.totalCostLimit = 60_000_000  // bytes of decoded pixels
        return cache
    }()

    /// Keyed by drawn size in points (one phone has one display scale).
    static func image(for url: URL, points: CGFloat) -> UIImage? {
        cache.object(forKey: key(url, points))
    }

    static func store(_ image: UIImage, for url: URL, points: CGFloat) {
        let cost = Int(image.size.width * image.size.height * image.scale * image.scale * 4)
        cache.setObject(image, forKey: key(url, points), cost: cost)
    }

    private static func key(_ url: URL, _ points: CGFloat) -> NSString {
        "\(url.absoluteString)#\(Int(points))" as NSString
    }

    /// Decodes straight to the needed size (ImageIO), instead of the full photo.
    nonisolated static func downsample(_ data: Data, maxPixels: CGFloat) -> UIImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary)
        else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,  // decode now, not on the main thread at draw time
            kCGImageSourceThumbnailMaxPixelSize: max(maxPixels, 1),
        ]
        guard let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        return UIImage(cgImage: cgImage)
    }
}
