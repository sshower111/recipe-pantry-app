import SwiftUI

/// Step-by-step focus mode: one step at a time with just the ingredients it uses, plus an
/// overview list where finished steps fade back (web: components/CookingMode.tsx).
struct CookingModeView: View {
    let session: CookingSession
    let ingredients: [Ingredient]
    let tried: Bool
    let onMarkTried: () -> Void

    /// The focus card's scroll id, for jumping here from the Live Activity.
    static let focusID = "focus"

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            progressBar
            focusCard
                .id(Self.focusID)
                .padding(.top, 20)
            if !session.allDone {
                controls.padding(.top, 16)
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

    private var focusCard: some View {
        ZStack {
            if session.allDone {
                finished
                    .transition(.opacity.combined(with: .offset(y: 12)))
            } else {
                stepContent(session.active)
                    .id(session.active)
                    .transition(.push(from: session.direction > 0 ? .trailing : .leading))
            }
        }
        .frame(maxWidth: .infinity, minHeight: 256, alignment: .topLeading)
        .padding(24)
        .background(Color.white.opacity(0.7), in: .rect(cornerRadius: 24))
        .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
        .clipShape(.rect(cornerRadius: 24))
        .animation(.spring(response: 0.32, dampingFraction: 0.9), value: session.active)
        .animation(.easeOut(duration: 0.3), value: session.allDone)
    }

    private func stepContent(_ index: Int) -> some View {
        let step = session.steps[index]
        let isDone = session.progress.done.contains(index)
        return VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .firstTextBaseline) {
                Text(String(format: "%02d", index + 1))
                    .font(.serifTitle(56))
                    .foregroundStyle(Color.terracotta)
                Spacer()
                Text("Step \(index + 1) of \(session.steps.count)")
                    .font(.subheadline)
                    .foregroundStyle(Color.muted)
            }
            Text(step.text)
                .font(.title3)
                .foregroundStyle(Color.ink)
                .lineSpacing(4)
                .opacity(isDone ? 0.4 : 1)
                .fixedSize(horizontal: false, vertical: true)
            if !step.ingredients.isEmpty {
                FlowLayout(spacing: 8) {
                    ForEach(step.ingredients.filter(ingredients.indices.contains), id: \.self) { i in
                        ingredientPill(ingredients[i])
                    }
                }
            }
            timerButton
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func ingredientPill(_ ingredient: Ingredient) -> some View {
        let quantity = ingredient.quantity
        return (Text(quantity.isEmpty ? "" : quantity + " ").fontWeight(.medium) + Text(ingredient.label))
            .font(.subheadline)
            .foregroundStyle(Color.ink)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(Color.sandSoft, in: .capsule)
    }

    @ViewBuilder
    private var timerButton: some View {
        if let timer = session.timerForActiveStep {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let remaining = timer.endsAt.timeIntervalSince(context.date)
                Button {
                    session.cancelTimer()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "timer")
                        Text(remaining <= 0 ? "Time's up" : StepTimer.clock(remaining))
                            .monospacedDigit()
                        Image(systemName: "xmark").foregroundStyle(Color.muted)
                    }
                    .font(.subheadline)
                    .foregroundStyle(remaining <= 0 ? Color.terracotta : Color.ink)
                    .padding(.horizontal, 16)
                    .frame(minHeight: 44)
                    .overlay { Capsule().strokeBorder(remaining <= 0 ? Color.terracotta : Color.sand) }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Cancel timer")
                .sensoryFeedback(.warning, trigger: remaining <= 0) { _, up in up }
            }
        } else if let seconds = session.activeDuration {
            Button {
                session.startTimer()
            } label: {
                Label("Start \(StepTimer.label(seconds)) timer", systemImage: "timer")
                    .font(.subheadline)
                    .foregroundStyle(Color.ink)
                    .padding(.horizontal, 16)
                    .frame(minHeight: 44)
                    .overlay { Capsule().strokeBorder(Color.sand) }
            }
            .buttonStyle(.plain)
        }
    }

    private var finished: some View {
        VStack(spacing: 8) {
            Image(systemName: "party.popper")
                .font(.system(size: 30, weight: .light))
                .foregroundStyle(Color.terracotta)
            Text("All done. Enjoy!")
                .font(.serifTitle(30))
                .foregroundStyle(Color.ink)
                .padding(.top, 4)
            Text("You finished all \(session.steps.count) steps.")
                .font(.subheadline)
                .foregroundStyle(Color.muted)
            if !tried {
                Button(action: onMarkTried) {
                    Text("Mark as tried")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 20)
                        .padding(.vertical, 10)
                        .background(Color.terracotta, in: .capsule)
                }
                .buttonStyle(.plain)
                .padding(.top, 12)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 208)
    }

    private var controls: some View {
        HStack(spacing: 12) {
            Button {
                withAnimation { session.select(session.active - 1) }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(Color.ink)
                    .frame(width: 48, height: 48)
                    .background(Color.white.opacity(0.7), in: .circle)
                    .overlay { Circle().strokeBorder(Color.sand) }
            }
            .buttonStyle(.plain)
            .disabled(session.active == 0)
            .opacity(session.active == 0 ? 0.3 : 1)
            .accessibilityLabel("Previous step")

            Button {
                withAnimation { session.completeStep() }
            } label: {
                Label(session.active == session.steps.count - 1 ? "Finish" : "Done, next step", systemImage: "checkmark")
                    .font(.body.weight(.medium))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 48)
                    .background(Color.terracotta, in: .capsule)
            }
            .buttonStyle(.plain)
            .sensoryFeedback(.success, trigger: session.allDone) { _, done in done }
        }
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
                                .lineLimit(isActive ? nil : 2)
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
