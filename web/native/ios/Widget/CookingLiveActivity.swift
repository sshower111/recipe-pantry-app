// Widget extension: the Lock Screen banner and Dynamic Island for a cooking step.
// Needs CookingActivityAttributes.swift in this target too.

import ActivityKit
import SwiftUI
import WidgetKit

private let terracotta = Color(red: 200 / 255, green: 109 / 255, blue: 81 / 255)

@main
struct CookingWidgetBundle: WidgetBundle {
    var body: some Widget {
        CookingLiveActivity()
    }
}

struct CookingLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CookingActivityAttributes.self) { context in
            LockScreenView(context: context)
                .activityBackgroundTint(.black)
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let state = context.state
            return DynamicIsland {
                // Expanded (touch and hold): the full step with its ingredients.
                DynamicIslandExpandedRegion(.leading) {
                    StepBadge(state: state)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    TimerLabel(state: state, isStale: context.isStale)
                        .font(.subheadline.weight(.medium))
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(state.stepText)
                            .font(.subheadline)
                            .foregroundStyle(.white)
                            .lineLimit(4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        IngredientPills(ingredients: state.ingredients, limit: 6)
                    }
                    .padding(.top, 4)
                }
            } compactLeading: {
                Text("Step \(state.stepNumber)/\(state.totalSteps)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(terracotta)
            } compactTrailing: {
                if state.timerEndsAt != nil {
                    TimerLabel(state: state, isStale: context.isStale)
                        .font(.caption.weight(.medium))
                        .frame(maxWidth: 52)
                } else {
                    Image(systemName: "fork.knife").foregroundStyle(terracotta)
                }
            } minimal: {
                Text("\(state.stepNumber)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(terracotta)
            }
            .keylineTint(terracotta)
        }
    }
}

private struct LockScreenView: View {
    let context: ActivityViewContext<CookingActivityAttributes>

    var body: some View {
        let state = context.state
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                StepBadge(state: state)
                Text(context.attributes.recipeTitle)
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.6))
                    .lineLimit(1)
                Spacer()
                TimerLabel(state: state, isStale: context.isStale)
                    .font(.subheadline.weight(.medium))
            }
            Text(state.stepText)
                .font(.body)
                .foregroundStyle(.white)
                .lineLimit(3)
            IngredientPills(ingredients: state.ingredients, limit: 4)
        }
        .padding(16)
    }
}

private struct StepBadge: View {
    let state: CookingActivityAttributes.ContentState

    var body: some View {
        Text("Step \(state.stepNumber)/\(state.totalSteps)")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(terracotta, in: Capsule())
    }
}

/// Counts down on its own (no updates from the app needed); "Time's up" once stale.
private struct TimerLabel: View {
    let state: CookingActivityAttributes.ContentState
    let isStale: Bool

    var body: some View {
        if let end = state.timerEndsAt {
            if isStale || end <= .now {
                Text("Time's up").foregroundStyle(terracotta)
            } else {
                Text(timerInterval: Date.now...end, countsDown: true)
                    .monospacedDigit()
                    .multilineTextAlignment(.trailing)
                    .foregroundStyle(.white)
            }
        }
    }
}

private struct IngredientPills: View {
    let ingredients: [String]
    let limit: Int

    var body: some View {
        let shown = Array(ingredients.prefix(limit))
        let extra = ingredients.count - shown.count
        if !shown.isEmpty {
            FlowLayout(spacing: 6) {
                ForEach(shown, id: \.self) { Pill(text: $0) }
                if extra > 0 { Pill(text: "+\(extra)") }
            }
        }
    }
}

private struct Pill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.white.opacity(0.9))
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(.white.opacity(0.12), in: Capsule())
    }
}

/// Wraps pills onto new lines like the web app's flex-wrap.
private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width ?? rows.map(\.width).max() ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.indexes {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var indexes: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows = [Row()]
        for (index, subview) in subviews.enumerated() {
            let size = subview.sizeThatFits(.unspecified)
            let needed = rows[rows.count - 1].indexes.isEmpty ? size.width : rows[rows.count - 1].width + spacing + size.width
            if needed > width, !rows[rows.count - 1].indexes.isEmpty {
                rows.append(Row())
            }
            let last = rows.count - 1
            rows[last].width += (rows[last].indexes.isEmpty ? 0 : spacing) + size.width
            rows[last].height = max(rows[last].height, size.height)
            rows[last].indexes.append(index)
        }
        return rows
    }
}
