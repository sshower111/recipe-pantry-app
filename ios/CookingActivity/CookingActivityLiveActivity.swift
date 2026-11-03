//
//  CookingActivityLiveActivity.swift
//  CookingActivity
//
//  The Lock Screen card and Dynamic Island for the step being cooked (docs/ios/README.md,
//  section 6): "Step 2/4" and the power-up emblem on top, the (shortened) instruction large,
//  the step's ingredients on one line, and wide ‹ › buttons at the bottom. Kept under the
//  ~160 pt height iOS allows, or it crops the card. The buttons run ChangeStepIntent
//  (ios/Shared/CookingProgress.swift); tapping anywhere else opens the recipe at its step.
//

import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

private let terracotta = Color(red: 200 / 255, green: 109 / 255, blue: 81 / 255)
private let cookYellow = Color(red: 0.96, green: 0.78, blue: 0.26)   // the cook's outlines

struct CookingActivityLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CookingActivityAttributes.self) { context in
            LockScreenView(context: context)
                .activityBackgroundTint(.black)
                .activitySystemActionForegroundColor(.white)
                .widgetURL(recipeURL(context))
        } dynamicIsland: { context in
            let state = context.state
            return DynamicIsland {
                // Expanded (touch and hold, or briefly when the activity starts).
                DynamicIslandExpandedRegion(.leading) {
                    StepHeader(state: state, size: 17)
                        .padding(.leading, 8)
                        .frame(maxHeight: .infinity)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    CookFlipbook(since: context.attributes.startedAt, size: 40)
                        .padding(.trailing, 6)
                }
                // Kept short: the expanded island crops anything past ~160 pt in all.
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 12) {
                        Instruction(state: state, size: 17)
                        StepButtons(context: context, height: 32)
                    }
                    .padding(.horizontal, 8)
                    .padding(.bottom, 2)
                }
            } compactLeading: {
                Text("Step \(state.currentStepIndex + 1)/\(state.totalSteps)")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(terracotta)
            } compactTrailing: {
                // A running step timer counts down here by itself (no app updates needed).
                if let end = state.timerEndsAt {
                    Countdown(end: end)
                        .font(.system(size: 14, weight: .semibold))
                        .frame(maxWidth: 50)
                } else {
                    // A still frame: plain text in the CookFlip font, no ticking clock.
                    CookFrame(size: 24)
                }
            } minimal: {
                CookFrame(size: 22)
            }
            .widgetURL(recipeURL(context))
            .keylineTint(terracotta)
        }
    }

    private func recipeURL(_ context: ActivityViewContext<CookingActivityAttributes>) -> URL? {
        URL(string: "cookbook://recipe/\(context.attributes.recipeId)")
    }
}

private struct LockScreenView: View {
    let context: ActivityViewContext<CookingActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .center) {
                StepHeader(state: context.state, size: 16)
                Spacer()
                CookFlipbook(since: context.attributes.startedAt, size: 38)
            }
            Instruction(state: context.state, size: 17)
            StepButtons(context: context, height: 30)
                .padding(.top, 8)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}

/// "Step 2/4", plus the countdown when this step's timer runs.
private struct StepHeader: View {
    let state: CookingActivityAttributes.ContentState
    let size: CGFloat

    var body: some View {
        HStack(spacing: 8) {
            Text("Step \(state.currentStepIndex + 1)/\(state.totalSteps)")
                .foregroundStyle(terracotta)
            if let end = state.timerEndsAt {
                Countdown(end: end)
            }
        }
        .font(.system(size: size, weight: .semibold))
    }
}

/// The instruction, then the step's ingredients on one quieter line.
private struct Instruction: View {
    let state: CookingActivityAttributes.ContentState
    let size: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(state.instructionText)
                .font(.system(size: size, weight: .semibold))
                .foregroundStyle(.white)
                .lineLimit(2)
                .minimumScaleFactor(0.85)
                .frame(maxWidth: .infinity, alignment: .leading)
            IngredientLine(ingredients: state.stepIngredients)
        }
    }
}

/// Counts down on its own; "Time's up" once it has passed (checked when the view is drawn).
private struct Countdown: View {
    let end: Date

    var body: some View {
        if end > .now {
            Text(timerInterval: Date.now...end, countsDown: true)
                .monospacedDigit()
                .multilineTextAlignment(.trailing)
                .foregroundStyle(.white)
        } else {
            Text("Time's up").foregroundStyle(.white)
        }
    }
}

/// As many of the step's ingredients as fit on one line, then "+N more" for the rest
/// (the full list is one tap away in the app). Never cuts a name in half.
private struct IngredientLine: View {
    let ingredients: [String]

    var body: some View {
        if !ingredients.isEmpty {
            ViewThatFits(in: .horizontal) {
                ForEach((1...ingredients.count).reversed(), id: \.self) { shown in
                    line(shown)
                }
                // Even the first name is too long: let it truncate.
                Text(ingredients[0]).lineLimit(1)
            }
            .font(.system(size: 13))
            .foregroundStyle(.white.opacity(0.6))
        }
    }

    private func line(_ shown: Int) -> some View {
        let rest = ingredients.count - shown
        let names = ingredients.prefix(shown) + (rest > 0 ? ["+\(rest) more"] : [])
        return Text(names.joined(separator: " · "))
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
    }
}

/// Wide ‹ › buttons along the bottom, easy to hit while cooking.
private struct StepButtons: View {
    let context: ActivityViewContext<CookingActivityAttributes>
    let height: CGFloat

    var body: some View {
        let state = context.state
        let id = context.attributes.recipeId
        HStack(spacing: 10) {
            StepButton(systemImage: "chevron.left", label: "Previous step", height: height,
                       intent: ChangeStepIntent(recipeId: id, offset: -1),
                       enabled: state.currentStepIndex > 0)
            StepButton(systemImage: "chevron.right", label: "Next step", height: height,
                       intent: ChangeStepIntent(recipeId: id, offset: 1),
                       enabled: state.currentStepIndex < state.totalSteps - 1)
            // Ends the island now; iOS keeps it after the app is closed otherwise.
            StepButton(systemImage: "xmark", label: "End cooking session", height: height,
                       intent: EndCookingIntent(), enabled: true, style: .quiet)
                .frame(width: height * 1.4)
        }
    }
}

private struct StepButton<Action: AppIntent>: View {
    enum Style { case primary, quiet }

    let systemImage: String
    let label: String
    let height: CGFloat
    let intent: Action
    let enabled: Bool
    var style = Style.primary

    var body: some View {
        Button(intent: intent) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(enabled ? .white : .white.opacity(0.3))
                .frame(maxWidth: .infinity, minHeight: height)
                .background(enabled && style == .primary ? terracotta : .white.opacity(0.12), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(label)
    }
}

/// The cook animation, one frame per second. Live Activities can't animate, but iOS keeps
/// `Text(timerInterval:)` ticking by itself; in the CookFlip font each digit is a frame
/// (`Fonts/CookFlip.ttf`, built by `ios/tools/make_flipbook_font.py` from `ios/Art/cook-frames`),
/// and cropping the clock to its last character leaves the seconds digit: frames 0-9 on loop.
private struct CookFlipbook: View {
    let since: Date
    let size: CGFloat

    var body: some View {
        Text(timerInterval: since...since.addingTimeInterval(12 * 3600), countsDown: false)
            .font(.custom("CookFlip", size: size))
            // The clock reserves room for its longest value and would draw "0:05" at the left
            // of it; right-aligned, the seconds digit sits at the edge the crop keeps.
            .multilineTextAlignment(.trailing)
            .foregroundStyle(cookYellow)
            .fixedSize()
            .frame(width: size, height: size, alignment: .trailing)
            .clipped()
            .accessibilityHidden(true)
    }
}

/// One still frame of the cook (the CookFlip font's "0").
private struct CookFrame: View {
    let size: CGFloat

    var body: some View {
        Text("0")
            .font(.custom("CookFlip", size: size))
            .foregroundStyle(cookYellow)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

extension CookingActivityAttributes {
    fileprivate static var preview: CookingActivityAttributes {
        CookingActivityAttributes(recipeId: 1, recipeTitle: "Garlic Butter Shrimp")
    }
}

extension CookingActivityAttributes.ContentState {
    fileprivate static var secondStep: CookingActivityAttributes.ContentState {
        CookingActivityAttributes.ContentState(
            currentStepIndex: 1, totalSteps: 3,
            instructionText: "Add the garlic and shrimp and cook for 3 minutes per side",
            stepIngredients: ["1 lb Shrimp", "2 cloves garlic, minced"], timerEndsAt: nil)
    }
}

#Preview("Lock Screen", as: .content, using: CookingActivityAttributes.preview) {
    CookingActivityLiveActivity()
} contentStates: {
    CookingActivityAttributes.ContentState.secondStep
}
