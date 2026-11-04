import SwiftUI

/// Hearts that fly up and fade out of a heart button each time `isFavorite` turns on.
/// Place it over (or centred on) the button; it never takes touches.
struct HeartBurst: View {
    let isFavorite: Bool
    @State private var bursts: [UUID] = []

    var body: some View {
        ZStack {
            ForEach(bursts, id: \.self) { _ in Particles() }
        }
        .allowsHitTesting(false)
        .onChange(of: isFavorite) { _, favorite in
            guard favorite else { return }
            let id = UUID()
            bursts.append(id)
            Task {
                try? await Task.sleep(for: .seconds(1.2))
                bursts.removeAll { $0 == id }
            }
        }
    }

    private struct Particle {
        let x: CGFloat, y: CGFloat, size: CGFloat, delay: Double, tilt: Double
    }

    // One big heart straight up, smaller ones spraying out to the sides.
    private static let particles: [Particle] = [
        Particle(x: 0, y: -70, size: 22, delay: 0, tilt: 0),
        Particle(x: -30, y: -48, size: 11, delay: 0.05, tilt: -20),
        Particle(x: 28, y: -54, size: 12, delay: 0.08, tilt: 18),
        Particle(x: -18, y: -80, size: 9, delay: 0.12, tilt: -10),
        Particle(x: 20, y: -86, size: 8, delay: 0.15, tilt: 12),
    ]

    private struct Motion {
        var offset: CGSize = .zero
        var scale: CGFloat = 0.3
        var opacity: Double = 0
    }

    private struct Particles: View {
        @State private var started = false

        var body: some View {
            ZStack {
                ForEach(HeartBurst.particles.indices, id: \.self) { index in
                    let particle = HeartBurst.particles[index]
                    Image(systemName: "heart.fill")
                        .font(.system(size: particle.size))
                        .foregroundStyle(Color.heart)
                        .rotationEffect(.degrees(particle.tilt))
                        .keyframeAnimator(initialValue: Motion(), trigger: started) { heart, motion in
                            heart
                                .scaleEffect(motion.scale)
                                .offset(motion.offset)
                                .opacity(motion.opacity)
                        } keyframes: { _ in
                            KeyframeTrack(\.offset) {
                                LinearKeyframe(.zero, duration: particle.delay)
                                CubicKeyframe(CGSize(width: particle.x, height: particle.y), duration: 0.8)
                            }
                            KeyframeTrack(\.scale) {
                                LinearKeyframe(0.3, duration: particle.delay)
                                SpringKeyframe(1.1, duration: 0.25)
                                CubicKeyframe(0.8, duration: 0.55)
                            }
                            KeyframeTrack(\.opacity) {
                                LinearKeyframe(0, duration: particle.delay)
                                LinearKeyframe(1, duration: 0.08)
                                LinearKeyframe(1, duration: 0.37)
                                LinearKeyframe(0, duration: 0.35)
                            }
                        }
                }
            }
            .onAppear { started = true }
        }
    }
}
