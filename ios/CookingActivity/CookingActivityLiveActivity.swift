//
//  CookingActivityLiveActivity.swift
//  CookingActivity
//
//  The cooking-step Live Activity, designed to Apple's Live Activities guidelines
//  (developer.apple.com/design/human-interface-guidelines/live-activities) in the app's own
//  look: cream text, terracotta accents, Apple's SF Pro throughout, and the pixel chef
//  (Shared/ChefMascot.swift) as the logo mark, without a container, in the leading spot.
//  Live Activities can't run a frame timer, so the chef is a still: one toss pose per step.
//
//  - Compact: the chef's head (chef_head_compact) | a progress ring with the step number (or
//    the step timer). Both fit the 28 pt circle the guidelines ask for (landscape).
//  - Minimal: the chef at the wok (chef_wok_minimal), or the timer when one runs.
//  - Expanded and Lock Screen share one layout: chef + "Step 2/4" with a segment bar, the
//    instruction, then the ingredients and a single ‹ | › control (plus a quiet ✕).
//  - Lock Screen follows the phone's appearance (cream / warm dark, like the app), with the
//    standard 14 pt margins; the island is always black (the system's, not customizable).
//  Keep both under ~160 pt tall or iOS crops them. ‹ › run ChangeStepIntent, ✕ runs
//  EndCookingIntent (ios/Shared/CookingProgress.swift); tapping elsewhere opens the recipe
//  at its step.
//

import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

private extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

/// The app's palette (ios/Cookbook/Design/Theme.swift), for the widget.
private enum Palette {
    static let cream = Color(hex: 0xFAF8F5)
    static let ink = Color(hex: 0x2B2622)
    static let muted = Color(hex: 0x8A817A)
    static let sand = Color(hex: 0xE6E2DD)
    static let terracotta = Color(hex: 0xC86D51)
    static let warmDark = Color(hex: 0x1F1A17)         // Lock Screen background in Dark Mode
}

/// Colors for one surface: the black island, or the Lock Screen in light or dark.
private struct Look {
    var text: Color
    var secondary: Color
    var accent: Color
    var track: Color          // empty part of the progress ring / bar
    var quiet: Color          // the ✕ button's fill

    static let island = Look(text: Palette.cream, secondary: Palette.cream.opacity(0.6),
                             accent: Palette.terracotta,
                             track: Palette.cream.opacity(0.2), quiet: Palette.cream.opacity(0.14))
    static let lockLight = Look(text: Palette.ink, secondary: Palette.muted,
                                accent: Palette.terracotta,
                                track: Palette.sand, quiet: Palette.sand)
    static let lockDark = Look(text: Palette.cream, secondary: Palette.cream.opacity(0.6),
                               accent: Palette.terracotta,
                               track: Palette.cream.opacity(0.18), quiet: Palette.cream.opacity(0.14))
}

struct CookingActivityLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CookingActivityAttributes.self) { context in
            LockScreenLiveActivityView(context: context)
                .widgetURL(recipeURL(context))
        } dynamicIsland: { context in
            let state = context.state
            let look = Look.island
            return DynamicIsland {
                // Expanded: wrapped close around the camera, the chef on the leading side.
                DynamicIslandExpandedRegion(.leading) {
                    // Kept small: the expanded island is cropped past ~160 pt, and the
                    // instruction needs the room while a video plays.
                    ChefStill(animation: .toss, step: state.currentStepIndex, size: 34)
                        .padding(.leading, 6)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    // No maxHeight here: a greedy header made iOS give the camera row most of
                    // the island and cut the instruction to one line.
                    StepHeader(state: state, look: look, alignment: .trailing, size: 14)
                        .padding(.trailing, 6)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    // iOS gives the expanded island a little more height when it pops open by
                    // itself (an alert) than on a long press, so pick the largest version that
                    // fits: the controls must never be cut off, the text gives way first.
                    ViewThatFits(in: .vertical) {
                        StepBody(context: context, look: look, textSize: 16, lines: 3, controlHeight: 30)
                        StepBody(context: context, look: look, textSize: 16, lines: 2, controlHeight: 30)
                        StepBody(context: context, look: look, textSize: 14, lines: 2, controlHeight: 28)
                    }
                    .padding(.horizontal, 6)
                    .padding(.top, 2)
                }
            } compactLeading: {
                ChefStill(animation: .headCompact, step: state.currentStepIndex, size: 24)
            } compactTrailing: {
                if let end = state.timerEndsAt {
                    // Counts down by itself; snug against the camera, no extra padding.
                    Countdown(end: end, color: look.accent)
                        .font(.system(size: 14, weight: .semibold))
                        .frame(maxWidth: 46)
                } else {
                    StepRing(state: state, look: look, size: 24)
                }
            } minimal: {
                // The time left while a step timer runs (live information, like the Timer
                // app), else the chef at the wok.
                if let end = state.timerEndsAt {
                    Countdown(end: end, color: look.accent)
                        .font(.system(size: 12, weight: .semibold))
                        .frame(maxWidth: 40)
                } else {
                    ChefStill(animation: .wokMinimal, step: state.currentStepIndex, size: 24)
                }
            }
            .widgetURL(recipeURL(context))
            .keylineTint(Palette.terracotta)
        }
    }

    private func recipeURL(_ context: ActivityViewContext<CookingActivityAttributes>) -> URL? {
        URL(string: "remnant://recipe/\(context.attributes.recipeId)")
    }
}

/// The Lock Screen banner: the chef mid-toss beside the step, then the expanded layout's body,
/// on the app's cream (or warm dark) background.
private struct LockScreenLiveActivityView: View {
    let context: ActivityViewContext<CookingActivityAttributes>
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let dark = colorScheme == .dark
        let look = dark ? Look.lockDark : Look.lockLight
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 10) {
                ChefStill(animation: .toss, step: context.state.currentStepIndex, size: 44)
                StepHeader(state: context.state, look: look, alignment: .leading)
                Spacer(minLength: 0)
            }
            StepBody(context: context, look: look, textSize: 17)
        }
        .padding(14)  // the standard Lock Screen margin
        .activityBackgroundTint(dark ? Palette.warmDark : Palette.cream)
        .activitySystemActionForegroundColor(dark ? Palette.cream : Palette.ink)
    }
}

/// "Step 2/4", a segment bar under it, and the timer when one runs.
private struct StepHeader: View {
    let state: CookingActivityAttributes.ContentState
    let look: Look
    let alignment: HorizontalAlignment
    var size: CGFloat = 17

    var body: some View {
        VStack(alignment: alignment, spacing: 5) {
            HStack(spacing: 8) {
                if alignment == .trailing, let end = state.timerEndsAt { timer(end) }
                Text("Step \(state.currentStepIndex + 1)/\(state.totalSteps)")
                    .font(.system(size: size, weight: .semibold))
                    .foregroundStyle(look.accent)
                    .contentTransition(.numericText(value: Double(state.currentStepIndex)))
                    .lineLimit(1)
                    .fixedSize()
                if alignment == .leading, let end = state.timerEndsAt { timer(end) }
            }
            SegmentBar(state: state, look: look)
                .frame(width: 72, height: 4)
        }
    }

    private func timer(_ end: Date) -> some View {
        // Timer text reserves room for its longest value; a fixed width keeps it from
        // squeezing "Step 2/4" onto two lines.
        Countdown(end: end, color: look.text)
            .font(.system(size: size - 2, weight: .semibold))
            .frame(width: size * 2.9, alignment: alignment == .leading ? .leading : .trailing)
    }
}

/// The instruction, then the ingredients beside a single ‹ | › control and a quiet ✕.
private struct StepBody: View {
    let context: ActivityViewContext<CookingActivityAttributes>
    let look: Look
    let textSize: CGFloat
    /// 3 in the expanded island (a smaller header leaves room), 2 on the Lock Screen.
    var lines = 2
    var controlHeight: CGFloat = 34

    var body: some View {
        let state = context.state
        VStack(alignment: .leading, spacing: lines > 2 ? 6 : 8) {
            Text(state.instructionText)
                .font(.system(size: textSize, weight: .semibold))
                .foregroundStyle(look.text)
                .lineLimit(lines)
                .minimumScaleFactor(0.8)
                // Claim the height for all its lines first, or iOS squeezes it to one line.
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentTransition(.opacity)
                .id(state.currentStepIndex)
            HStack(alignment: .center, spacing: 10) {
                IngredientLine(ingredients: state.stepIngredients, color: look.secondary)
                Spacer(minLength: 0)  // keeps the control on the right when a step has no ingredients
                StepControl(context: context, look: look, height: controlHeight)
            }
        }
    }
}

/// Back and next as one element (the guidelines prefer a single control), with ✕ beside it.
/// The pill's corners follow the card's (ContainerRelativeShape), concentric with its edge.
private struct StepControl: View {
    let context: ActivityViewContext<CookingActivityAttributes>
    let look: Look
    var height: CGFloat = 34

    var body: some View {
        let state = context.state
        let id = context.attributes.recipeId
        HStack(spacing: 8) {
            HStack(spacing: 0) {
                half("chevron.left", "Previous step", ChangeStepIntent(recipeId: id, offset: -1),
                     enabled: state.currentStepIndex > 0)
                Rectangle().fill(.white.opacity(0.35)).frame(width: 1, height: 16)
                half("chevron.right", "Next step", ChangeStepIntent(recipeId: id, offset: 1),
                     enabled: state.currentStepIndex < state.totalSteps - 1)
            }
            .background(look.accent, in: ContainerRelativeShape())
            .clipShape(ContainerRelativeShape())

            // Ends the island now (iOS keeps it after the app is closed otherwise).
            Button(intent: EndCookingIntent()) {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(look.text.opacity(0.8))
                    .frame(width: height, height: height)
                    .background(look.quiet, in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("End cooking session")
        }
    }

    private func half(_ symbol: String, _ label: String, _ intent: ChangeStepIntent, enabled: Bool) -> some View {
        Button(intent: intent) {
            Image(systemName: symbol)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white.opacity(enabled ? 1 : 0.35))
                .frame(width: 46, height: height)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(label)
    }
}

/// One segment per step, like the app's cooking-mode progress bar.
private struct SegmentBar: View {
    let state: CookingActivityAttributes.ContentState
    let look: Look

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<max(state.totalSteps, 1), id: \.self) { index in
                Capsule().fill(index <= state.currentStepIndex ? look.accent : look.track)
            }
        }
    }
}

/// A ring that fills step by step, the step number inside (compact and minimal).
private struct StepRing: View {
    let state: CookingActivityAttributes.ContentState
    let look: Look
    let size: CGFloat

    var body: some View {
        let progress = Double(state.currentStepIndex + 1) / Double(max(state.totalSteps, 1))
        ZStack {
            Circle().stroke(look.track, lineWidth: size * 0.12)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(look.accent, style: StrokeStyle(lineWidth: size * 0.12, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Text("\(state.currentStepIndex + 1)")
                .font(.system(size: size * 0.46, weight: .bold))
                .foregroundStyle(look.text)
                .contentTransition(.numericText(value: Double(state.currentStepIndex)))
        }
        .frame(width: size, height: size)
        .accessibilityElement()
        .accessibilityLabel("Step \(state.currentStepIndex + 1) of \(state.totalSteps)")
    }
}

/// Counts down on its own; "Done" once it has passed (checked when the view is drawn).
private struct Countdown: View {
    let end: Date
    let color: Color

    var body: some View {
        if end > .now {
            Text(timerInterval: Date.now...end, countsDown: true)
                .monospacedDigit()
                .multilineTextAlignment(.trailing)
                .foregroundStyle(color)
        } else {
            Text("Done").foregroundStyle(color)
        }
    }
}

/// As many of the step's ingredients as fit on one line, then "+N more" for the rest
/// (the full list is one tap away in the app). Never cuts a name in half.
private struct IngredientLine: View {
    let ingredients: [String]
    let color: Color

    var body: some View {
        if !ingredients.isEmpty {
            ViewThatFits(in: .horizontal) {
                ForEach((1...ingredients.count).reversed(), id: \.self) { shown in
                    line(shown)
                }
                // Even the first name is too long: let it truncate.
                Text(ingredients[0]).lineLimit(1)
            }
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(color)
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

extension CookingActivityAttributes {
    fileprivate static var preview: CookingActivityAttributes {
        CookingActivityAttributes(recipeId: 1, recipeTitle: "Garlic Butter Shrimp")
    }
}

extension CookingActivityAttributes.ContentState {
    fileprivate static var secondStep: CookingActivityAttributes.ContentState {
        CookingActivityAttributes.ContentState(
            currentStepIndex: 1, totalSteps: 4,
            instructionText: "Add the garlic and shrimp and cook for 3 minutes per side",
            stepIngredients: ["1 lb Shrimp", "2 cloves garlic, minced"], timerEndsAt: nil)
    }
}

#Preview("Lock Screen", as: .content, using: CookingActivityAttributes.preview) {
    CookingActivityLiveActivity()
} contentStates: {
    CookingActivityAttributes.ContentState.secondStep
}
