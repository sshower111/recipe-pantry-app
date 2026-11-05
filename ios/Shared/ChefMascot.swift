import SwiftUI
import UIKit

// The pixel-art chef (Shared/ChefMascot.xcassets, sources in ios/Art/chef-mascot), used by the
// app and the Live Activity. Frames are named `chef_<prefix>_<n>`, n from 0. Every Image that
// draws them uses `.interpolation(.none)` so the pixels stay square on Retina screens.
//
// Only the toss (9 frames, 68 x 68 px) exists so far. An animation whose first frame is missing
// from the catalog plays the toss instead; dropping `chef_splash_0...7` etc. into the catalog
// switches that state over with no code change.

/// One frame sequence: its asset prefix, frame count and speed.
nonisolated struct ChefAnimation: Equatable, Sendable {
    let prefix: String
    let frameCount: Int
    let fps: Double
    /// false: play once and hold the last frame (success, error).
    var loops = true

    static let toss = ChefAnimation(prefix: "toss", frameCount: 9, fps: 5)       // 0.2 s per frame
    static let splash = ChefAnimation(prefix: "splash", frameCount: 8, fps: 8)
    static let refresh = ChefAnimation(prefix: "refresh", frameCount: 8, fps: 12)
    static let loading = ChefAnimation(prefix: "loading", frameCount: 6, fps: 6)
    static let empty = ChefAnimation(prefix: "empty", frameCount: 1, fps: 1)
    static let success = ChefAnimation(prefix: "success", frameCount: 1, fps: 1, loops: false)
    static let error = ChefAnimation(prefix: "error", frameCount: 1, fps: 1, loops: false)
    // Live Activity stills (one image each; the island can't run a frame timer).
    static let headCompact = ChefAnimation(prefix: "head_compact", frameCount: 1, fps: 1)
    static let wokMinimal = ChefAnimation(prefix: "wok_minimal", frameCount: 1, fps: 1)

    func imageName(_ frame: Int) -> String { "chef_\(prefix)_\(frame)" }

    /// This animation if its frames are in the catalog, else the toss (looping).
    var available: ChefAnimation {
        UIImage(named: imageName(0)) != nil ? self : .toss
    }

    /// The pose for a cooking step, for stills that change with the step: neighbouring steps
    /// get frames two apart, so each change shows.
    func frame(forStep step: Int) -> Int { (max(step, 0) * 2) % frameCount }
}

/// One frame of the chef, drawn without smoothing.
struct ChefSprite: View {
    let name: String
    var size: CGFloat

    var body: some View {
        Image(name)
            .resizable()
            .interpolation(.none)
            .antialiased(false)
            .scaledToFit()
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// A still of the chef for widgets and other places that can't animate: the given
/// animation's frame for a step, or the toss's when that animation isn't in the catalog yet.
struct ChefStill: View {
    var animation: ChefAnimation = .toss
    var step = 0
    var size: CGFloat

    var body: some View {
        let shown = animation.available
        ChefSprite(name: shown.imageName(shown.frame(forStep: step)), size: size)
    }
}
