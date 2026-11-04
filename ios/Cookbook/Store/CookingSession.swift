import Foundation
import Observation
import UserNotifications

/// Cooking progress for the recipe on screen: the step in focus, the steps ticked off and the
/// step timer. Saved per recipe on every change (CookingStorage), so the Live Activity's step
/// buttons and a later visit pick it up.
@Observable
final class CookingSession {
    let recipeId: Int
    let steps: [Step]
    private(set) var progress: CookingProgress
    private(set) var timer: CookingTimer?
    /// 1 when moving forward, -1 when moving back; picks the slide direction.
    private(set) var direction = 1

    init(recipe: Recipe) {
        recipeId = recipe.id
        steps = recipe.steps
        progress = CookingProgress()
        reload()
    }

    var active: Int { progress.active }
    var allDone: Bool { !steps.isEmpty && progress.done.count == steps.count }
    var cookingStarted: Bool { progress.active > 0 || !progress.done.isEmpty || timer != nil }

    /// Ingredient indexes the step in focus uses (highlighted in the ingredient row).
    var activeIngredients: Set<Int> {
        allDone || steps.isEmpty ? [] : Set(steps[active].ingredients)
    }

    /// Seconds the step in focus mentions, if any.
    var activeDuration: Int? {
        steps.isEmpty ? nil : StepTimer.duration(in: steps[active].text)
    }

    var timerForActiveStep: CookingTimer? {
        timer?.step == active ? timer : nil
    }

    /// Re-read storage, e.g. after the Live Activity's buttons moved the step.
    func reload() {
        let saved = CookingStorage.progress(for: recipeId)
        progress = CookingProgress(active: min(saved.active, max(steps.count - 1, 0)),
                                   done: saved.done.filter { $0 < steps.count })
        timer = CookingStorage.timer.flatMap { $0.recipeId == recipeId && $0.step < steps.count ? $0 : nil }
    }

    func select(_ index: Int) {
        let index = min(max(index, 0), max(steps.count - 1, 0))
        direction = index >= progress.active ? 1 : -1
        progress.active = index
        save()
    }

    /// "Done, next step": tick the step off and move to the next one not done yet.
    func completeStep() {
        progress.done.insert(progress.active)
        if let next = steps.indices.first(where: { $0 > progress.active && !progress.done.contains($0) }) {
            direction = 1
            progress.active = next
        }
        save()
    }

    func toggleDone(_ index: Int) {
        if progress.done.contains(index) { progress.done.remove(index) } else { progress.done.insert(index) }
        save()
    }

    func startOver() {
        direction = -1
        progress = CookingProgress()
        save()
        cancelTimer()
    }

    func startTimer() {
        guard let seconds = activeDuration else { return }
        let timer = CookingTimer(recipeId: recipeId, step: active, total: seconds,
                                 endsAt: .now.addingTimeInterval(TimeInterval(seconds)))
        self.timer = timer
        CookingStorage.timer = timer
        TimerNotification.schedule(timer, stepText: steps[active].text)
    }

    func cancelTimer() {
        guard timer != nil else { return }
        timer = nil
        CookingStorage.timer = nil
        TimerNotification.cancel()
    }

    private func save() {
        CookingStorage.setProgress(progress, for: recipeId)
    }
}

/// "Time's up" when a step timer ends while the cook is in another app (e.g. the video).
enum TimerNotification {
    private static let id = "stepTimer"

    static func schedule(_ timer: CookingTimer, stepText: String) {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [id])
        let content = UNMutableNotificationContent()
        content.title = "Time's up"
        content.body = "Step \(timer.step + 1): \(stepText)"
        content.sound = .default
        content.interruptionLevel = .timeSensitive
        let seconds = max(timer.endsAt.timeIntervalSinceNow, 1)
        let request = UNNotificationRequest(
            identifier: id, content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: seconds, repeats: false))
        Task {
            // Asked the first time a timer starts; without permission the timer still runs in the app.
            guard (try? await center.requestAuthorization(options: [.alert, .sound])) == true else { return }
            try? await center.add(request)
        }
    }

    static func cancel() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [id])
    }
}
