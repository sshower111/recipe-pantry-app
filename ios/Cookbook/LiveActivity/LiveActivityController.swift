import ActivityKit
import UIKit

/// Starts and ends the cooking-step Live Activity (docs/ios/README.md, section 6).
///
/// It starts when "Watch on Instagram" is tapped, while the app is still in front (iOS
/// refuses requests from the background), pops the island open once the app has gone to
/// the background, and ends whenever the app becomes active again.
enum LiveActivityController {
    /// Set by `start`; the next trip to the background shows the expanded island once.
    private static var announcePending = false

    static func start(_ recipe: Recipe) async {
        guard !recipe.steps.isEmpty, ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let snapshot = CookingSnapshot(recipe)
        CookingStorage.snapshot = snapshot
        await endAll()
        let index = min(CookingStorage.progress(for: recipe.id).active, recipe.steps.count - 1)
        let state = snapshot.state(at: index, timer: CookingStorage.timer)
        let attributes = CookingActivityAttributes(recipeId: recipe.id, recipeTitle: recipe.title)
        do {
            _ = try Activity.request(attributes: attributes, content: .init(state: state, staleDate: nil))
            announcePending = true
        } catch {
            print("Live Activity not started: \(error)")
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
            title: "Step \(state.currentStepIndex + 1) of \(state.totalSteps)",
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
        for activity in Activity<CookingActivityAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }
}

extension CookingSnapshot {
    init(_ recipe: Recipe) {
        self.init(recipeId: recipe.id, title: recipe.title, steps: recipe.steps.map { step in
            // The island fits about two lines: the server's short version when there is one.
            Step(text: step.shortText ?? step.text, ingredients: step.ingredients.compactMap { index in
                guard recipe.ingredients.indices.contains(index) else { return nil }
                let ingredient = recipe.ingredients[index]
                return [ingredient.quantity, ingredient.label].filter { !$0.isEmpty }.joined(separator: " ")
            })
        })
    }
}
