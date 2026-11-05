import SwiftUI

/// Plays one of the chef's frame sequences (`Image("chef_<animationPrefix>_<currentFrame>")`)
/// at its own speed. The frame clock is a task tied to the view, so it stops as soon as the
/// view leaves the screen. With Reduce Motion on, the first frame stays still.
///
/// Missing frames fall back to the toss (see `ChefAnimation.available`), so every state shows
/// the chef even before its own frames are drawn.
struct AnimatedChefView: View {
    let animation: ChefAnimation
    var size: CGFloat = 96

    @State private var currentFrame = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(_ animation: ChefAnimation, size: CGFloat = 96) {
        self.animation = animation
        self.size = size
    }

    /// For a sequence not listed in `ChefAnimation`.
    init(animationPrefix: String, frameCount: Int, fps: Double, size: CGFloat = 96, loops: Bool = true) {
        self.init(ChefAnimation(prefix: animationPrefix, frameCount: frameCount, fps: fps, loops: loops),
                  size: size)
    }

    private var shown: ChefAnimation { animation.available }

    var animationPrefix: String { shown.prefix }

    var body: some View {
        ChefSprite(name: "chef_\(animationPrefix)_\(currentFrame)", size: size)
            .task(id: animation) {
                currentFrame = 0
                let sequence = shown
                guard sequence.frameCount > 1, !reduceMotion else { return }
                let interval = Duration.seconds(1 / max(sequence.fps, 1))
                while !Task.isCancelled {
                    try? await Task.sleep(for: interval)
                    guard !Task.isCancelled else { return }
                    let next = currentFrame + 1
                    if next < sequence.frameCount {
                        currentFrame = next
                    } else if sequence.loops {
                        currentFrame = 0
                    } else {
                        return  // played once: hold the last frame
                    }
                }
            }
    }
}

#Preview {
    HStack(spacing: 24) {
        AnimatedChefView(.toss, size: 68)
        AnimatedChefView(.loading, size: 68)
        AnimatedChefView(.success, size: 68)
    }
    .padding()
    .background(Color.cream)
}
