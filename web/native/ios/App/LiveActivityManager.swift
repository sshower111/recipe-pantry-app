// Capacitor plugin ("LiveActivity" in JS) that shows the current cooking step as a Live
// Activity while the app is in the background.
//
// The web app keeps a "session" here up to date (the open recipe's active step) with
// setSession / clearSession. The plugin itself starts the Live Activity when the app is
// backgrounded and ends it immediately when the app comes back, because the web view's
// JavaScript may already be suspended by then.
//
// App target only. Requires iOS 16.2+ and NSSupportsLiveActivities = YES in Info.plist.

import ActivityKit
import Capacitor
import UIKit

@objc(LiveActivityManager)
public class LiveActivityManager: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "LiveActivityManager"
    public let jsName = "LiveActivity"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "setSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setAutoStart", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "endSession", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getStatus", returnType: CAPPluginReturnPromise),
    ]

    private typealias State = CookingActivityAttributes.ContentState

    // All state below is only touched on the main queue.
    private var attributes: CookingActivityAttributes?
    private var state: State?
    private var autoStart = true
    private var activity: Activity<CookingActivityAttributes>?
    /// Activities this plugin ended, so their .dismissed update isn't mistaken for the user.
    private var endedByApp = Set<String>()
    /// The step the user swiped away on the Lock Screen: not shown again until it changes.
    private var userDismissedState: State?
    private var observers: [NSObjectProtocol] = []

    override public func load() {
        let center = NotificationCenter.default
        let on = { (name: Notification.Name, action: @escaping (LiveActivityManager) -> Void) in
            center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                if let self { action(self) }
            }
        }
        observers = [
            // iOS only lets an app *start* a Live Activity while it is still in the foreground,
            // and by didEnterBackground it no longer is. willResignActive fires just before,
            // while starting is still allowed; didEnterBackground is a second chance.
            on(UIApplication.willResignActiveNotification) { $0.startIfNeeded() },
            on(UIApplication.didEnterBackgroundNotification) { $0.startIfNeeded() },
            on(UIApplication.willEnterForegroundNotification) { $0.endActivity() },
            // Resigning active without going to the background (Control Center, the
            // notification shade, a system alert) never sends willEnterForeground.
            on(UIApplication.didBecomeActiveNotification) { $0.endActivity() },
        ]
        // Clear anything left over from a previous run that was killed while backgrounded.
        Task { await Self.endAll() }
    }

    deinit {
        observers.forEach(NotificationCenter.default.removeObserver)
    }

    // MARK: - JS methods

    @objc func setSession(_ call: CAPPluginCall) {
        guard let recipeId = call.getInt("recipeId"),
              let stepNumber = call.getInt("stepNumber"),
              let totalSteps = call.getInt("totalSteps"),
              let stepText = call.getString("stepText")
        else {
            call.reject("recipeId, stepNumber, totalSteps and stepText are required")
            return
        }
        let ingredients = (call.getArray("ingredients") ?? []).compactMap { $0 as? String }
        let timerEndsAt = call.getDouble("timerEndsAt").map { Date(timeIntervalSince1970: $0 / 1000) }
        let attributes = CookingActivityAttributes(
            recipeId: recipeId, recipeTitle: call.getString("recipeTitle") ?? "")
        let state = State(stepNumber: stepNumber, totalSteps: totalSteps, stepText: stepText,
                          ingredients: ingredients, timerEndsAt: timerEndsAt)
        DispatchQueue.main.async {
            if self.attributes?.recipeId != recipeId {
                self.endActivity()
                self.userDismissedState = nil
            }
            self.attributes = attributes
            self.state = state
            // Normally nothing is running while the app is open; update it if something is.
            if let activity = self.activity {
                Task { await activity.update(Self.content(state)) }
            }
            call.resolve()
        }
    }

    @objc func clearSession(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.attributes = nil
            self.state = nil
            self.endActivity()
            call.resolve()
        }
    }

    /// The in-app "Dynamic Island" switch. Off: backgrounding the app never starts anything.
    @objc func setAutoStart(_ call: CAPPluginCall) {
        let enabled = call.getBool("enabled") ?? true
        DispatchQueue.main.async {
            self.autoStart = enabled
            if !enabled { self.endActivity() }
            call.resolve()
        }
    }

    /// "End cooking session": forget the session and end every cooking Live Activity.
    @objc func endSession(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.attributes = nil
            self.state = nil
            self.activity = nil
            self.endedByApp.formUnion(Activity<CookingActivityAttributes>.activities.map(\.id))
            Task {
                await Self.endAll()
                call.resolve()
            }
        }
    }

    @objc func getStatus(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            call.resolve([
                "enabled": ActivityAuthorizationInfo().areActivitiesEnabled,
                "autoStart": self.autoStart,
                "active": self.activity != nil,
            ])
        }
    }

    // MARK: - Lifecycle

    private func startIfNeeded() {
        guard autoStart, activity == nil,
              let attributes, let state, state != userDismissedState,
              ActivityAuthorizationInfo().areActivitiesEnabled
        else { return }
        do {
            let activity = try Activity.request(
                attributes: attributes, content: Self.content(state), pushType: nil)
            self.activity = activity
            watch(activity)
        } catch {
            // Most often: the app had already left the foreground. Nothing to clean up.
            CAPLog.print("LiveActivity: could not start: \(error.localizedDescription)")
        }
    }

    private func endActivity() {
        guard let activity else { return }
        self.activity = nil
        endedByApp.insert(activity.id)
        Task { await activity.end(nil, dismissalPolicy: .immediate) }
    }

    /// Notice the user swiping the activity away on the Lock Screen, so it isn't restarted
    /// for the same step the next time the app is backgrounded. Swiping the Dynamic Island
    /// sideways only hides it; the activity stays active and nothing changes here.
    private func watch(_ activity: Activity<CookingActivityAttributes>) {
        Task { [weak self] in
            for await update in activity.activityStateUpdates where update == .dismissed || update == .ended {
                await MainActor.run {
                    guard let self else { return }
                    if update == .dismissed, !self.endedByApp.contains(activity.id) {
                        self.userDismissedState = activity.content.state
                    }
                    if self.activity?.id == activity.id { self.activity = nil }
                }
            }
        }
    }

    private static func content(_ state: State) -> ActivityContent<State> {
        // Past the timer's end the widget shows "Time's up" (context.isStale).
        ActivityContent(state: state, staleDate: state.timerEndsAt)
    }

    private static func endAll() async {
        for activity in Activity<CookingActivityAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }
}
