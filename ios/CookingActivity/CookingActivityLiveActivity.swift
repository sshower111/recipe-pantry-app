//
//  CookingActivityLiveActivity.swift
//  CookingActivity
//
//  Created by Keith Lam on 11/3/26.
//

import ActivityKit
import WidgetKit
import SwiftUI

// Placeholder layouts on the shared CookingActivityAttributes (ios/Shared/);
// the real Lock Screen and Dynamic Island designs come in build step 6.
struct CookingActivityLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CookingActivityAttributes.self) { context in
            VStack(alignment: .leading) {
                Text("Step \(context.state.currentStepIndex + 1)/\(context.state.totalSteps)")
                Text(context.state.instructionText)
            }
            .padding()
            .activityBackgroundTint(Color.black)
            .activitySystemActionForegroundColor(Color.white)

        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.bottom) {
                    Text(context.state.instructionText)
                }
            } compactLeading: {
                Text("Step \(context.state.currentStepIndex + 1)/\(context.state.totalSteps)")
            } compactTrailing: {
                Image(systemName: "frying.pan")
            } minimal: {
                Image(systemName: "frying.pan")
            }
            .widgetURL(URL(string: "cookbook://recipe/\(context.attributes.recipeId)"))
        }
    }
}

extension CookingActivityAttributes {
    fileprivate static var preview: CookingActivityAttributes {
        CookingActivityAttributes(recipeId: 1, recipeTitle: "Garlic Butter Shrimp")
    }
}

extension CookingActivityAttributes.ContentState {
    fileprivate static var firstStep: CookingActivityAttributes.ContentState {
        CookingActivityAttributes.ContentState(
            currentStepIndex: 0, totalSteps: 3,
            instructionText: "Melt the butter in a pan over medium heat.",
            stepIngredients: ["3 tbsp Unsalted butter"], timerEndsAt: nil)
    }
}

#Preview("Notification", as: .content, using: CookingActivityAttributes.preview) {
   CookingActivityLiveActivity()
} contentStates: {
    CookingActivityAttributes.ContentState.firstStep
}
