import ActivityKit
import AppIntents
import Foundation

// Shared by the app and the CookingActivity widget extension. The step buttons in the Live
// Activity run ChangeStepIntent inside the app's process (LiveActivityIntent), so plain
// UserDefaults.standard is enough to share progress; no App Group needed.

/// Where the cook is in one recipe: the step in focus and the steps ticked off.
/// Kept on the phone, not the server (docs/ios/api.md).
nonisolated struct CookingProgress: Codable, Equatable {
    var active = 0
    var done: Set<Int> = []
}

/// A running step timer ("Bake for 28-32 minutes" -> 28 min). One at a time, app-wide.
nonisolated struct CookingTimer: Codable, Equatable {
    var recipeId: Int
    var step: Int
    var total: Int         // seconds
    var endsAt: Date
}

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

    /// The countdown shows only on the step whose timer is running.
    func state(at index: Int, timer: CookingTimer?) -> CookingActivityAttributes.ContentState {
        let step = steps[index]
        let timerHere = timer.flatMap { $0.recipeId == recipeId && $0.step == index ? $0.endsAt : nil }
        return .init(currentStepIndex: index, totalSteps: steps.count, instructionText: step.text,
                     stepIngredients: step.ingredients, timerEndsAt: timerHere)
    }
}

nonisolated enum CookingStorage {
    private static let snapshotKey = "cookingSnapshot"
    private static let timerKey = "cookingTimer"

    static func progress(for recipeId: Int) -> CookingProgress {
        read(CookingProgress.self, key: "progress:\(recipeId)") ?? CookingProgress()
    }

    static func setProgress(_ progress: CookingProgress, for recipeId: Int) {
        write(progress, key: "progress:\(recipeId)")
    }

    static var timer: CookingTimer? {
        get { read(CookingTimer.self, key: timerKey) }
        set { write(newValue, key: timerKey) }
    }

    static var snapshot: CookingSnapshot? {
        get { read(CookingSnapshot.self, key: snapshotKey) }
        set { write(newValue, key: snapshotKey) }
    }

    private static func read<T: Decodable>(_ type: T.Type, key: String) -> T? {
        UserDefaults.standard.data(forKey: key).flatMap { try? JSONDecoder().decode(type, from: $0) }
    }

    private static func write<T: Encodable>(_ value: T?, key: String) {
        UserDefaults.standard.set(value.flatMap { try? JSONEncoder().encode($0) }, forKey: key)
    }
}

/// The ‹ › buttons in the Live Activity: move the step in focus and update the activity.
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
        var progress = CookingStorage.progress(for: recipeId)
        progress.active = min(max(progress.active + offset, 0), snapshot.steps.count - 1)
        CookingStorage.setProgress(progress, for: recipeId)
        let state = snapshot.state(at: progress.active, timer: CookingStorage.timer)
        let content = ActivityContent(state: state, staleDate: nil)
        // iOS shrinks the expanded island by itself after a few seconds and offers no way to
        // keep it open. A (silent) alert re-opens it, so it stays open while the cook keeps
        // tapping ‹ ›; it still shrinks a few seconds after the last tap.
        let alert = AlertConfiguration(
            title: "Step \(state.currentStepIndex + 1)/\(state.totalSteps)",
            body: "\(state.instructionText)",
            sound: .named("silence.caf"))  // in the app bundle; this runs in the app's process
        for activity in Activity<CookingActivityAttributes>.activities where activity.attributes.recipeId == recipeId {
            await activity.update(content, alertConfiguration: alert)
        }
        return .result()
    }
}

/// The ✕ in the Live Activity: ends it right away (also when the app was closed long ago,
/// since a LiveActivityIntent runs in the app's process, launched if needed).
struct EndCookingIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "End cooking session"
    static let isDiscoverable = false

    init() {}

    func perform() async throws -> some IntentResult {
        for activity in Activity<CookingActivityAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
        return .result()
    }
}
