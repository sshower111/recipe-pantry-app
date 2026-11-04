import SwiftUI

/// Step-by-step focus mode: a progress bar, the step card (StepCard) and an overview list where
/// finished steps fade back.
struct CookingModeView: View {
    let session: CookingSession
    let ingredients: [Ingredient]
    let tried: Bool
    let onMarkTried: () -> Void
    /// Where the step card is relative to the screen (the recipe screen pops a copy up once
    /// it has been scrolled past going down).
    var onCardPosition: (CardPosition) -> Void = { _ in }

    nonisolated enum CardPosition: Equatable, Sendable { case onScreen, above, below }

    /// The focus card's scroll id, for jumping here from the Live Activity.
    static let focusID = "focus"

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            progressBar
            StepCard(session: session, ingredients: ingredients, tried: tried, onMarkTried: onMarkTried)
                .id(Self.focusID)
                .padding(.top, 20)
                // The scroll view's visible area in the card's own coordinates: below the card's
                // bottom means it was scrolled past going down ("above" the screen).
                .onGeometryChange(for: CardPosition.self) { proxy in
                    guard let visible = proxy.bounds(of: .scrollView) else { return .onScreen }
                    if visible.minY > proxy.size.height { return .above }
                    if visible.maxY < 0 { return .below }
                    return .onScreen
                } action: { position in
                    onCardPosition(position)
                }
            overview.padding(.top, 32)
            if !session.progress.done.isEmpty {
                Button("Start over") { withAnimation(.easeOut(duration: 0.25)) { session.startOver() } }
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
                    .underline()
                    .padding(.top, 16)
            }
        }
        .sensoryFeedback(.selection, trigger: session.active)
    }

    private var progressBar: some View {
        HStack(spacing: 6) {
            ForEach(session.steps.indices, id: \.self) { index in
                let done = session.progress.done.contains(index)
                Button {
                    withAnimation(.easeOut(duration: 0.3)) { session.select(index) }
                } label: {
                    GeometryReader { proxy in
                        Capsule().fill(Color.sand)
                            .overlay(alignment: .leading) {
                                Capsule().fill(Color.terracotta)
                                    .frame(width: proxy.size.width * (done ? 1 : index == session.active ? 0.4 : 0))
                                    .opacity(done ? 0.45 : 1)
                            }
                    }
                    .frame(height: 6)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityHidden(true)
            }
        }
        .animation(.easeOut(duration: 0.35), value: session.progress)
    }

    private var overview: some View {
        VStack(spacing: 0) {
            ForEach(session.steps.indices, id: \.self) { index in
                let isDone = session.progress.done.contains(index)
                let isActive = index == session.active && !session.allDone
                HStack(alignment: .top, spacing: 16) {
                    Button {
                        withAnimation { session.select(index) }
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 16) {
                            Text(String(format: "%02d", index + 1))
                                .font(.serifTitle(24))
                                .foregroundStyle(isActive ? Color.terracotta : Color.ink.opacity(0.7))
                                .frame(width: 36, alignment: .leading)
                            Text(session.steps[index].text)
                                .font(.system(size: 15))
                                .foregroundStyle(Color.ink)
                                .lineSpacing(3)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                        }
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(isActive ? .isSelected : [])

                    Button {
                        withAnimation(.easeOut(duration: 0.2)) { session.toggleDone(index) }
                    } label: {
                        Image(systemName: "checkmark")
                            .font(.system(size: 11, weight: .heavy))
                            .foregroundStyle(isDone ? .white : .clear)
                            .frame(width: 24, height: 24)
                            .background(isDone ? Color.terracotta : Color.white, in: .circle)
                            .overlay { Circle().strokeBorder(isDone ? Color.terracotta : Color.sand) }
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 2)
                    .accessibilityLabel(isDone ? "Mark step \(index + 1) not done" : "Mark step \(index + 1) done")
                }
                .padding(.vertical, 16)
                .opacity(isDone && !isActive ? 0.4 : 1)
                .overlay(alignment: .top) { Rectangle().fill(Color.sand).frame(height: 1) }
            }
        }
    }
}
