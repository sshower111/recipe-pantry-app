# iOS Live Activity (cooking step on the Lock Screen / Dynamic Island)

Native code for a Capacitor iOS build of the web app. There is no Xcode project in this
repo yet, and none of this has been compiled: it needs a Mac with Xcode 15+ and iOS 16.2+.

## What it does

- While a recipe with steps is open, the web app keeps the native side told about the active
  step (`lib/useLiveActivity.ts` -> `LiveActivity.setSession`).
- Leaving the app starts a Live Activity for that step; coming back ends it immediately
  (`dismissalPolicy: .immediate`), so the island is clear while the app is on screen.
- The recipe page's **Dynamic Island** switch turns auto-start off (`setAutoStart`).
- **End cooking session** ends every cooking Live Activity (`Activity.end`) and stops the
  timer; nothing starts again until you move to another step or start a timer.
- Swiping the banner away on the Lock Screen is remembered for that step, so it isn't shown
  again until the step changes. Swiping the Dynamic Island sideways only hides it (system
  behavior; nothing to handle).
- Compact island: "Step 2/5" on the left, the timer (or a fork-and-knife icon) on the right.
  Minimal: the step number. Expanded (touch and hold): the step text and ingredient pills.
  The timer counts down by itself and shows "Time's up" once it ends.

## Platform limits to know

- iOS only lets an app **start** a Live Activity while it is in the foreground. By
  `didEnterBackgroundNotification` it no longer is, so the request is made on
  `willResignActiveNotification` (just before), with `didEnterBackground` as a second try.
- Because of that, pulling down Control Center or Notification Center also starts it
  briefly; it is ended again on `didBecomeActiveNotification` (`willEnterForeground` is not
  sent when the app never reached the background).
- If iOS suspends or kills the app, the activity stays until you reopen it (then it's ended)
  or iOS removes it (8 hours active at most).

## Adding it to a Capacitor app

```bash
cd web
npm install @capacitor/cli @capacitor/ios
npx cap init "Cookbook" com.example.cookbook --web-dir out
npx cap add ios
```

The app reads `/api` from the FastAPI server on your PC, so point the iOS shell at the
Next.js dev server on your LAN (in `capacitor.config.ts`: `server: { url: "http://<pc-ip>:3000",
cleartext: true }`), or build a static export with an absolute API origin.

In Xcode (`npx cap open ios`):

1. **App target:** add `App/LiveActivityManager.swift`, `App/MainViewController.swift` and
   `Shared/CookingActivityAttributes.swift`. In `Main.storyboard`, set the Bridge View
   Controller's custom class to `MainViewController`. In `Info.plist` add
   `NSSupportsLiveActivities` = `YES`. Deployment target: iOS 16.2 or later.
2. **Widget extension:** File > New > Target > Widget Extension (no configuration intent),
   delete the generated Swift files, add `Widget/CookingLiveActivity.swift` and
   `Shared/CookingActivityAttributes.swift` (target membership: both targets).
3. Run on a device or a simulator with an iPhone that has a Dynamic Island, open a recipe,
   and press Home.
