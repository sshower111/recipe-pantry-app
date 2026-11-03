import ActivityKit
import UIKit

/// Starts and ends the cooking-step Live Activity (docs/ios/README.md, section 6).
///
/// It starts when "Watch on Instagram" is tapped (always) or when the app is left while a
/// recipe is on screen (if the Settings switch is on), and ends whenever the app becomes
/// active again. Requests happen while the app is still in front or `.inactive`, because
/// iOS refuses them from the background.
enum LiveActivityController {
    /// @AppStorage key for Settings' "Show steps when you leave a recipe" (default on).
    static let autoStartKey = "liveActivityAutoStart"

    /// The recipe screen on display, set by RecipeDetailView; leaving the app follows it.
    static var onScreen: Recipe?

    /// Set by Watch's start; the next trip to the background shows the expanded island once.
    private static var announcePending = false
    private static var isStarting = false
    /// Activities the app ended itself, so their `.dismissed` isn't taken for the user's swipe.
    private static var endedByApp: Set<String> = []
    /// The step the user swiped the activity away on: leaving the app doesn't bring it back
    /// for that same step (moving to another step, or tapping Watch, does).
    private static var dismissed: (recipeId: Int, step: Int)?

    /// "Watch on Instagram": always starts, and pops the island open once the app is away.
    static func start(_ recipe: Recipe) async {
        dismissed = nil
        if await request(recipe) { announcePending = true }
    }

    /// The app is being left (`.inactive`, again on `.background` in case): follow the recipe
    /// on screen, unless the switch is off, cooking is finished or the user dismissed this step.
    static func startOnLeave() async {
        guard UserDefaults.standard.object(forKey: autoStartKey) as? Bool ?? true,
              let recipe = onScreen, !recipe.steps.isEmpty,
              Activity<CookingActivityAttributes>.activities.isEmpty else { return }
        let progress = CookingStorage.progress(for: recipe.id)
        guard progress.done.count < recipe.steps.count else { return }
        if let dismissed, dismissed.recipeId == recipe.id, dismissed.step == progress.active { return }
        // Pop it open with the instruction too. The pop only happens on `.background`, so a
        // Control Center pull (`.inactive` only) starts the activity without it.
        if await request(recipe) { announcePending = true }
    }

    @discardableResult
    private static func request(_ recipe: Recipe) async -> Bool {
        guard !isStarting, !recipe.steps.isEmpty, ActivityAuthorizationInfo().areActivitiesEnabled else { return false }
        isStarting = true
        defer { isStarting = false }
        let snapshot = CookingSnapshot(recipe)
        CookingStorage.snapshot = snapshot
        await endAll()
        let index = min(CookingStorage.progress(for: recipe.id).active, recipe.steps.count - 1)
        let state = snapshot.state(at: index, timer: CookingStorage.timer)
        let attributes = CookingActivityAttributes(recipeId: recipe.id, recipeTitle: recipe.title)
        do {
            let activity = try Activity.request(attributes: attributes, content: .init(state: state, staleDate: nil))
            watchForDismissal(activity, recipeId: recipe.id)
            return true
        } catch {
            print("Live Activity not started: \(error)")
            return false
        }
    }

    private static func watchForDismissal(_ activity: Activity<CookingActivityAttributes>, recipeId: Int) {
        Task {
            for await state in activity.activityStateUpdates where state == .dismissed {
                if !endedByApp.contains(activity.id) {
                    dismissed = (recipeId, activity.content.state.currentStepIndex)
                }
            }
        }
    }

    /// iOS never keeps the island expanded, but an alert update shows the expanded view for a
    /// few seconds (it only appears once the app is off screen). After that the user can
    /// swipe it away or touch and hold to see it again.
    static func announce() async {
        guard announcePending, let activity = Activity<CookingActivityAttributes>.activities.first else { return }
        announcePending = false
        let state = activity.content.state
        let alert = AlertConfiguration(
            title: "Step \(state.currentStepIndex + 1)/\(state.totalSteps)",
            body: "\(state.instructionText)",
            sound: .named("silence.caf"))  // Resources/silence.caf: half a second of silence
        // The app is on its way to the background; ask for a moment to finish the update.
        let task = UIApplication.shared.beginBackgroundTask()
        await activity.update(activity.content, alertConfiguration: alert)
        UIApplication.shared.endBackgroundTask(task)
    }

    /// Also clears an activity left over from a run that was killed.
    static func endAll() async {
        announcePending = false
        stayAwake(false)
        for activity in Activity<CookingActivityAttributes>.activities {
            endedByApp.insert(activity.id)
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    // MARK: Closing the app ends the island
    //
    // iOS keeps a Live Activity after its app is closed, and a suspended app gets no word when
    // it's swiped away in the app switcher. So after leaving (with an island showing) the app
    // stays awake ~25 s; closing it in that window (the usual "leave, then swipe it off")
    // delivers willTerminate, which ends the island. Later, the island's ✕ does it.

    private static var awakeTask: UIBackgroundTaskIdentifier = .invalid

    /// Called on `.background` (true) and on coming back or ending (false).
    static func stayAwake(_ awake: Bool) {
        if awake {
            guard awakeTask == .invalid, !Activity<CookingActivityAttributes>.activities.isEmpty else { return }
            awakeTask = UIApplication.shared.beginBackgroundTask(withName: "end island on close") { stayAwake(false) }
            Task {
                try? await Task.sleep(for: .seconds(25))
                stayAwake(false)
            }
        } else if awakeTask != .invalid {
            UIApplication.shared.endBackgroundTask(awakeTask)
            awakeTask = .invalid
        }
    }

    /// willTerminate: end every activity before the process goes (iOS allows a few seconds).
    static func endOnTermination() {
        let done = DispatchSemaphore(value: 0)
        Task.detached {
            for activity in Activity<CookingActivityAttributes>.activities {
                await activity.end(nil, dismissalPolicy: .immediate)
            }
            done.signal()
        }
        _ = done.wait(timeout: .now() + 2)
    }
}

extension CookingSnapshot {
    init(_ recipe: Recipe) {
        self.init(recipeId: recipe.id, title: recipe.title, steps: recipe.steps.map { step in
            // The island fits about two lines: the server's short version, else the rule-based one.
            Step(text: step.shortText ?? step.islandText, ingredients: step.ingredients.compactMap { index in
                guard recipe.ingredients.indices.contains(index) else { return nil }
                let ingredient = recipe.ingredients[index]
                return [ingredient.quantity, ingredient.label].filter { !$0.isEmpty }.joined(separator: " ")
            })
        })
    }
}
