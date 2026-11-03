import ActivityKit
import AppIntents
import Foundation

// Shared by the app and the CookingActivity widget extension. The step buttons in the Live
// Activity run ChangeStepIntent inside the app's process (LiveActivityIntent), so plain
// UserDefaults.standard is enough to share progress; no App Group needed.

/// What the Live Activity needs to show any step of the recipe being cooked, saved when
/// the activity starts so the step buttons work without the network.
nonisolated struct CookingSnapshot: Codable {
    struct Step: Codable {
        var text: String
        var ingredients: [String]    // ready-made labels, e.g. "170 g Butter"
    }

    var recipeId: Int
    var title: String
    var steps: [Step]

    func state(at index: Int) -> CookingActivityAttributes.ContentState {
        let step = steps[index]
        return .init(currentStepIndex: index, totalSteps: steps.count, instructionText: step.text,
                     stepIngredients: step.ingredients, timerEndsAt: nil)
    }
}

/// Step progress lives on the phone, not the server (docs/ios/api.md).
nonisolated enum CookingStorage {
    private static let snapshotKey = "cookingSnapshot"

    static func activeStep(for recipeId: Int) -> Int {
        UserDefaults.standard.integer(forKey: "activeStep:\(recipeId)")
    }

    static func setActiveStep(_ index: Int, for recipeId: Int) {
        UserDefaults.standard.set(index, forKey: "activeStep:\(recipeId)")
    }

    static var snapshot: CookingSnapshot? {
        get {
            UserDefaults.standard.data(forKey: snapshotKey)
                .flatMap { try? JSONDecoder().decode(CookingSnapshot.self, from: $0) }
        }
        set {
            UserDefaults.standard.set(newValue.flatMap { try? JSONEncoder().encode($0) }, forKey: snapshotKey)
        }
    }
}

/// The ‹ › buttons in the Live Activity: move the current step and update the activity.
struct ChangeStepIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Change cooking step"
    static let isDiscoverable = false

    @Parameter(title: "Recipe") var recipeId: Int
    @Parameter(title: "Steps to move") var offset: Int

    init() {}

    init(recipeId: Int, offset: Int) {
        self.recipeId = recipeId
        self.offset = offset
    }

    func perform() async throws -> some IntentResult {
        guard let snapshot = CookingStorage.snapshot, snapshot.recipeId == recipeId, !snapshot.steps.isEmpty else {
            return .result()
        }
        let index = min(max(CookingStorage.activeStep(for: recipeId) + offset, 0), snapshot.steps.count - 1)
        CookingStorage.setActiveStep(index, for: recipeId)
        let content = ActivityContent(state: snapshot.state(at: index), staleDate: nil)
        for activity in Activity<CookingActivityAttributes>.activities where activity.attributes.recipeId == recipeId {
            await activity.update(content)
        }
        return .result()
    }
}
