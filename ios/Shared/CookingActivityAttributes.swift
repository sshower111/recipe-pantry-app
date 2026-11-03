import ActivityKit
import Foundation

/// The cooking-step Live Activity's data, compiled into both the app and the
/// CookingActivity widget extension (see docs/ios/README.md, section 6).
nonisolated struct CookingActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var currentStepIndex: Int        // 0-based; show currentStepIndex + 1
        var totalSteps: Int
        var instructionText: String
        var stepIngredients: [String]    // ready-made labels, e.g. "170 g Butter"
        var timerEndsAt: Date?           // compact trailing countdown; nil = no timer
    }

    var recipeId: Int
    var recipeTitle: String
}
