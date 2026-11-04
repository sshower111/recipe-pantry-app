import SwiftUI

/// Cooking mode's step card: the steps side by side in a swipeable pager (big step number, the
/// step, its ingredients, its timer), then "Done, next step". Used on the recipe page and,
/// identical, as the card that pops up at the top while scrolling away from it. Both copies
/// share the CookingSession, so they always show the same step.
struct StepCard: View {
    let session: CookingSession
    let ingredients: [Ingredient]
    let tried: Bool
    let onMarkTried: () -> Void
    /// Swipes, Done and timer taps: the pop-up stays out while it's being used.
    var onInteract: () -> Void = {}
    /// The one-time "swipe" hint shows under the card on the page, not in the pop-up.
    var showsHint = true
    /// The pop-up's version: same look and controls, less padding and a smaller step number.
    var compact = false

    /// The step card in view in the pager.
    @State private var page: Int?
    /// The "swipe to move between steps" hint shows until the first swipe.
    @AppStorage("cooking:swipedSteps") private var hasSwiped = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            focusCard
            if !session.allDone {
                controls.padding(.top, compact ? 10 : 16)
                if showsHint && !hasSwiped && session.steps.count > 1 {
                    Label("Swipe the card to move between steps", systemImage: "hand.draw")
                        .font(.footnote)
                        .foregroundStyle(Color.muted)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 10)
                }
            }
        }
    }

    /// The step card. Steps sit side by side in a paging scroll view, so a swipe tracks the
    /// finger and settles with the system's own momentum; the page in view is the step in
    /// focus (and the step the Live Activity follows).
    private var focusCard: some View {
        ZStack {
            if session.allDone {
                finished
                    .frame(maxWidth: .infinity, minHeight: 256)
                    .padding(24)
                    .background(Color.white.opacity(0.7), in: .rect(cornerRadius: 24))
                    .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
                    .transition(.opacity.combined(with: .offset(y: 12)))
            } else {
                pager
            }
        }
        .animation(.easeOut(duration: 0.3), value: session.allDone)
        .accessibilityAction(named: "Next step") { withAnimation { session.select(session.active + 1) } }
        .accessibilityAction(named: "Previous step") { withAnimation { session.select(session.active - 1) } }
    }

    private var pager: some View {
        ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: 12) {
                ForEach(session.steps.indices, id: \.self) { index in
                    stepContent(index)
                        .frame(maxWidth: .infinity, minHeight: compact ? 0 : 208, maxHeight: .infinity,
                               alignment: .topLeading)
                        .padding(compact ? 16 : 24)
                        .background(Color.white.opacity(0.7), in: .rect(cornerRadius: 24))
                        .overlay { RoundedRectangle(cornerRadius: 24).strokeBorder(Color.sand) }
                        .containerRelativeFrame(.horizontal)
                        .id(index)
                }
            }
            // Every card as tall as the tallest, so the page doesn't jump while swiping.
            .fixedSize(horizontal: false, vertical: true)
            .scrollTargetLayout()
        }
        .scrollTargetBehavior(.viewAligned)
        .scrollIndicators(.hidden)
        .scrollClipDisabled()
        .scrollPosition(id: $page)
        .onAppear { page = session.active }
        // Swiped to a step: it becomes the step in focus.
        .onChange(of: page) { _, new in
            guard let new, new != session.active else { return }
            hasSwiped = true
            onInteract()
            session.select(new)
        }
        // Moved some other way (Done, the progress bar, the list, the Live Activity): follow it.
        .onChange(of: session.active) { _, new in
            guard page != new else { return }
            withAnimation(.snappy(duration: 0.35)) { page = new }
        }
    }

    private func stepContent(_ index: Int) -> some View {
        let step = session.steps[index]
        let isDone = session.progress.done.contains(index)
        return VStack(alignment: .leading, spacing: compact ? 12 : 20) {
            HStack(alignment: .firstTextBaseline) {
                Text(String(format: "%02d", index + 1))
                    .font(.serifTitle(compact ? 40 : 56))
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
            if index == session.active { timerButton }
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
                    onInteract()
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
                    .frame(minHeight: compact ? 36 : 44)
                    .overlay { Capsule().strokeBorder(remaining <= 0 ? Color.terracotta : Color.sand) }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Cancel timer")
                .sensoryFeedback(.warning, trigger: remaining <= 0) { _, up in up }
            }
        } else if let seconds = session.activeDuration {
            Button {
                onInteract()
                session.startTimer()
            } label: {
                Label("Start \(StepTimer.label(seconds)) timer", systemImage: "timer")
                    .font(.subheadline)
                    .foregroundStyle(Color.ink)
                    .padding(.horizontal, 16)
                    .frame(minHeight: compact ? 36 : 44)
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
                    Text("Mark as cooked")
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
                onInteract()
                withAnimation { session.completeStep() }
            } label: {
                Label(session.active == session.steps.count - 1 ? "Finish" : "Done, next step", systemImage: "checkmark")
                    .font(.body.weight(.medium))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: compact ? 42 : 48)
                    .background(Color.terracotta, in: .capsule)
            }
            .buttonStyle(.plain)
            .sensoryFeedback(.success, trigger: session.allDone) { _, done in done }
        }
    }
}
