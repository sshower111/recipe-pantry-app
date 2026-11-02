// Shared by the app target (LiveActivityManager) and the widget extension
// (CookingLiveActivity): add this file to both targets.

import ActivityKit
import Foundation

struct CookingActivityAttributes: ActivityAttributes {
    /// What changes while cooking. Mirrors `LiveActivityStep` in web/lib/liveActivity.ts.
    public struct ContentState: Codable, Hashable {
        /// 1-based.
        var stepNumber: Int
        var totalSteps: Int
        var stepText: String
        /// Ready-made pill labels, e.g. "170 g Butter".
        var ingredients: [String]
        /// When the step timer runs out, if one is running.
        var timerEndsAt: Date?
    }

    var recipeId: Int
    var recipeTitle: String
}
