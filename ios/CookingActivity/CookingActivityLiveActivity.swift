//
//  CookingActivityLiveActivity.swift
//  CookingActivity
//
//  The Lock Screen card and Dynamic Island for the step being cooked (docs/ios/README.md,
//  section 6). Styled like a system notification (SF Pro, semibold first line, 15 pt text)
//  and kept under the ~160 pt height iOS allows, or it crops the card. The ‹ › buttons run
//  ChangeStepIntent (ios/Shared/CookingProgress.swift); tapping anywhere else opens the
//  recipe at its current step.
//

import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

private let terracotta = Color(red: 200 / 255, green: 109 / 255, blue: 81 / 255)

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
                    StepTitle(state: state)
                        .padding(.leading, 6)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    StepButtons(context: context)
                        .padding(.trailing, 4)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    StepText(state: state, lines: 3)
                        .padding(.horizontal, 6)
                        .padding(.top, 2)
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
                    Image(systemName: "frying.pan.fill").foregroundStyle(terracotta)
                }
            } minimal: {
                Text("\(state.currentStepIndex + 1)")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(terracotta)
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
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .center) {
                StepTitle(state: context.state)
                Spacer()
                StepButtons(context: context)
            }
            StepText(state: context.state, lines: 2)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }
}

/// "Step 2 of 4", like a notification's bold first line.
private struct StepTitle: View {
    let state: CookingActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "frying.pan.fill")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(terracotta)
            Text("Step \(state.currentStepIndex + 1) of \(state.totalSteps)")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(.white)
            if let end = state.timerEndsAt {
                Countdown(end: end)
                    .font(.system(size: 15, weight: .semibold))
            }
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
                .foregroundStyle(terracotta)
        } else {
            Text("Time's up").foregroundStyle(terracotta)
        }
    }
}

/// The instruction, then the step's ingredients on one quieter line.
private struct StepText: View {
    let state: CookingActivityAttributes.ContentState
    let lines: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(state.instructionText)
                .font(.system(size: 15))
                .foregroundStyle(.white)
                .lineLimit(lines)
                .frame(maxWidth: .infinity, alignment: .leading)
            IngredientLine(ingredients: state.stepIngredients)
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

private struct StepButtons: View {
    let context: ActivityViewContext<CookingActivityAttributes>

    var body: some View {
        let state = context.state
        let id = context.attributes.recipeId
        HStack(spacing: 8) {
            StepButton(systemImage: "chevron.left", label: "Previous step",
                       intent: ChangeStepIntent(recipeId: id, offset: -1),
                       enabled: state.currentStepIndex > 0)
            StepButton(systemImage: "chevron.right", label: "Next step",
                       intent: ChangeStepIntent(recipeId: id, offset: 1),
                       enabled: state.currentStepIndex < state.totalSteps - 1)
        }
    }
}

private struct StepButton: View {
    let systemImage: String
    let label: String
    let intent: ChangeStepIntent
    let enabled: Bool

    var body: some View {
        Button(intent: intent) {
            Image(systemName: systemImage)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(enabled ? .white : .white.opacity(0.3))
                .frame(width: 36, height: 36)
                .background(enabled ? terracotta : .white.opacity(0.12), in: Circle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(label)
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
            instructionText: "Add the garlic and shrimp and cook for 3 minutes per side.",
            stepIngredients: ["1 lb Shrimp", "2 cloves garlic, minced"], timerEndsAt: nil)
    }
}

#Preview("Lock Screen", as: .content, using: CookingActivityAttributes.preview) {
    CookingActivityLiveActivity()
} contentStates: {
    CookingActivityAttributes.ContentState.secondStep
}
