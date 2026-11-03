# Native iOS app: handoff runbook

Plan for building **Cookbook**, a SwiftUI iPhone app (iOS 17+) with a cooking-step Live
Activity, on a Mac. The iPhone app reads the FastAPI server over Wi-Fi. Nothing runs in the
cloud.

> **Revised 2026-11-03: the backend stays on the Windows PC.** The MacBook Air (M1, 16 GB)
> struggled with Ollama, the server and the Simulator next to Xcode, so the Mac is now only
> the development client (Xcode, Claude Code, git). The pipeline, SQLite, Ollama and
> `uvicorn` run on the PC; the app talks to `http://<PC IP>:8000`. No iOS Simulators: build,
> run and debug on the real iPhone. Sections 1-2 below record the original move to the Mac
> (Xcode, the venv and pytest still work there); sections 3 and 7 are updated for the PC.

Read with: [`api.md`](api.md) (the exact JSON the app decodes) and the root `CLAUDE.md`.

```
iPhone: Cookbook.app (SwiftUI)  --HTTP over Wi-Fi-->  Windows PC: uvicorn api.app:app (FastAPI + SQLite)
        + CookingActivity widget extension                       + main.py ingest (yt-dlp, Whisper, Ollama)
Mac: Xcode + Claude Code only (builds and installs the app on the iPhone)
```

The iPhone can't run the pipeline (yt-dlp, Whisper, a 9B Ollama model), so adding recipes
stays a PC job. The phone needs the PC awake and on the same network; away from home, a
private network such as Tailscale is the later option.

---

## 1. On the Windows PC, before leaving

The code is on GitHub. **The data is not**, and must never be committed (the repo is public).

1. Nothing to merge: `main` stays the published web version. The iOS work lives on the
   **`ios-app`** branch (this runbook, `api.md`, and the pantry/ingredients endpoints) and
   goes back to `main` as a pull request once the native app is built.
2. Stop the API server (Ctrl+C), then export the database **as one file**. Most recent writes
   (e.g. the `reparse` that added steps) sit in `recipes.db-wal`; copying only `recipes.db`
   silently loses them:
   ```powershell
   .\.venv\Scripts\python.exe -c "import sqlite3; sqlite3.connect('data/recipes.db').execute(\"VACUUM INTO 'data/recipes-export.db'\")"
   ```
3. Copy by USB or a cloud folder (not git):
   - `data/recipes-export.db` -> becomes `data/recipes.db` on the Mac
   - `data/thumbnails/` (about 30 MB)
   - `.env`
   - any URL lists or saved recipe pages you keep outside the project
4. Optional sanity number to compare later: run `python main.py list` and note the count.

## 2. Mac setup

1. **Xcode** (App Store, latest). Open it once, accept the license, install the iOS
   platform/simulator it offers. Xcode > Settings > Accounts: add your Apple ID.
   - Free Apple ID: installs on your own iPhone, re-install every 7 days.
   - Apple Developer Program ($99/yr): no expiry, TestFlight. Not needed to start.
2. **Command line tools and packages** (Homebrew from https://brew.sh first):
   ```bash
   brew install python@3.12 node@22 ffmpeg gh git
   brew install --cask ollama
   ollama pull qwen3.5:9b
   ```
3. **Project**:
   ```bash
   git clone -b ios-app https://github.com/sshower111/recipe-pantry-app.git && cd recipe-pantry-app
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt          # + requirements-ocr.txt if you want OCR
   mkdir -p data && cp <copied>/recipes-export.db data/recipes.db
   cp -R <copied>/thumbnails data/thumbnails && cp <copied>/.env .env
   ```
   The copied `.env` already suits a Mac (`RECIPE_WHISPER_DEVICE=cpu`, `int8`: no CUDA on
   Macs; Ollama uses the Apple GPU by itself).
4. **Check the move before any iOS work**:
   ```bash
   pytest                                         # expect all passing (215 at handoff)
   python main.py list                            # same count as on Windows (89 ready)
   uvicorn api.app:app --host 0.0.0.0 --port 8000
   curl http://localhost:8000/api/recipes | head -c 300
   ```
   Optionally run the web app too (`cd web && npm install && npm run dev`) and open
   http://localhost:3000: thumbnails and steps should all be there.
5. **Claude Code on the Mac**: update the "Environment Notes (this machine)" section of
   `CLAUDE.md` (it describes the Windows PC), and change `.claude/launch.json`'s
   `.venv/Scripts/python.exe` to `.venv/bin/python`. Claude's memory from the Windows
   sessions does not carry over; `CLAUDE.md` and these docs are the context.

## 3. Let the iPhone reach the server

The server runs on the Windows PC (see the revision note at the top).

- On the PC, start the API with `uvicorn api.app:app --host 0.0.0.0 --port 8000` (the default
  `127.0.0.1` only accepts the PC itself).
- Windows Firewall: allow Python on **Private** networks when Windows asks, or add an inbound
  rule for TCP 8000. The home Wi-Fi must be a Private network, not Public.
- Use the PC's LAN IP (`ipconfig` -> IPv4 Address), e.g. `http://192.168.2.20:8000`. Give
  the PC a fixed address (a DHCP reservation in the router) so it doesn't change. The app
  keeps it in a Settings screen (`@AppStorage("serverURL")`); `APIClient.defaultServerURL`
  is the starting value. The app sets `NSAllowsLocalNetworking` for plain `http://` on the
  LAN; confirm on the first device run that loads to the IP aren't blocked by ATS.
- Check from the iPhone first: Safari -> `http://<PC IP>:8000/api/recipes` shows JSON.
- **No Simulator.** Build and run on the iPhone (USB first; Xcode > Window > Devices and
  Simulators > "Connect via network" for Wi-Fi after that). From the terminal:
  `xcodebuild -project ios/Cookbook.xcodeproj -scheme Cookbook -destination 'generic/platform=iOS' -allowProvisioningUpdates build`,
  then `xcrun devicectl device install app --device <name> <path to Cookbook.app>`.
- iPhone: same Wi-Fi as the PC; Settings > Privacy & Security > Developer Mode on (appears
  after Xcode sees the phone); with a free Apple ID, trust the developer certificate under
  Settings > General > VPN & Device Management; allow the app's Local Network prompt on
  first launch.

## 4. Create the Xcode project (by hand, 5 minutes)

Xcode 16+ uses folders that sync with disk, so after this, Swift files written into these
folders (by you or Claude Code) are picked up without editing the project file.

1. File > New > Project > iOS **App**. Product Name `Cookbook`, Interface **SwiftUI**,
   Language Swift, Storage **None**, no tests. Save inside the repo as `ios/` (so the project
   is `ios/Cookbook.xcodeproj`). Don't let Xcode create a second git repository.
2. Target **Cookbook** > General: Minimum Deployments **iOS 17.0**; iPhone only; Signing:
   your team, bundle id e.g. `com.<you>.cookbook`.
3. Target **Cookbook** > Info (custom properties):
   | Key | Value |
   |---|---|
   | `NSSupportsLiveActivities` | YES |
   | `NSLocalNetworkUsageDescription` | Cookbook loads your recipes from the server on your Mac. |
   | `NSAppTransportSecurity` > `NSAllowsLocalNetworking` | YES (plain `http://` to `.local` / LAN) |
4. File > New > Target > **Widget Extension**. Name `CookingActivity`, check **Include Live
   Activity**, uncheck Include Configuration App Intent. Activate the scheme if asked.
   Deployment iOS 17.0. Delete the sample widget code it generates (keep the folder).
5. Create a folder `ios/Shared/` for code both targets compile (the `ActivityAttributes`).
   Add it to the project and tick **both** targets' membership (File Inspector).
6. Build and run the empty app in an iPhone 16 Pro simulator once, so signing is sorted.

## 5. App structure

```
ios/
  Cookbook/
    CookbookApp.swift            @main; injects RecipeStore + LiveActivityController; watches scenePhase
    Design/Theme.swift           Color(hex:), cream/sand/terracotta/ink/muted, serif title font
    Models/Models.swift          Codable structs from docs/ios/api.md
    Networking/APIClient.swift   async/await URLSession; base URL from Settings; snake_case decoding
    Store/RecipeStore.swift      @Observable: list, detail cache, optimistic favorite/tried
    Store/CookingSession.swift   @Observable: active step, done set, timer; persisted per recipe
    Views/CookbookView.swift     LazyVStack feed, search, filter chips (All/Favorites/Tried/To try)
    Views/RecipeCard.swift       thumbnail, title, "N ingredients · M steps", Tried badge, heart
    Views/RecipeDetailView.swift hero, title, caption, pills, action bar, ingredients, steps
    Views/IngredientRow.swift    ScrollView(.horizontal) of amount tiles + names
    Views/CookingModeView.swift  focus card + step list (done = opacity 0.4)
    Views/PantryView.swift       pick what you have -> GET /api/pantry
    Views/SettingsView.swift     server URL + "test connection"; Dynamic Island auto-start
    LiveActivity/LiveActivityController.swift   start/update/end, scenePhase hooks, dismiss tracking
  Shared/
    CookingActivityAttributes.swift
  CookingActivity/
    CookingActivityBundle.swift  @main WidgetBundle
    CookingLiveActivity.swift    Lock Screen + Dynamic Island layouts
```

Design tokens (from the web app, `web/app/globals.css`): cream `#FAF8F5` (background), sand
`#E6E2DD` (cards, borders), sand-soft `#F1EDE8` (tiles), terracotta `#C86D51` (accent,
active), terracotta-soft `#F6E4DD` (active fills), ink `#2B2622` (text), muted `#8A817A`.
Titles in a Garamond-style serif (system `.serif` design is fine; EB Garamond can be bundled
later), body in the system font. Black `#000000` for the Live Activity card.

## 6. Live Activity specifics

`CookingActivityAttributes` (in `Shared/`):

```swift
struct CookingActivityAttributes: ActivityAttributes {
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
```

Layouts: compact leading "Step X/Y" (terracotta), compact trailing the countdown
(`Text(timerInterval: .now...end, countsDown: true)`, counts down without app updates) or a
small icon; minimal a terracotta icon; expanded (long press) the full instruction plus
ingredient pills on black; Lock Screen the same card. A starting point already exists in
`web/native/ios/Widget/CookingLiveActivity.swift` (written for the Capacitor plan, never
compiled): rename its state fields to the ones above and drop the Capacitor parts.

**Lifecycle rules (these are the parts that go wrong):**

1. **Start on `.inactive`, not `.background`.** iOS refuses `Activity.request` once the app is
   in the background. `scenePhase` passes through `.inactive` first; request there (and try
   again on `.background` in case). `UIApplication.didEnterBackgroundNotification` alone fails.
2. **End on `.active`** with `activity.end(nil, dismissalPolicy: .immediate)`. That also
   clears it after Control Center / Notification Center pulls, which pass through `.inactive`
   without backgrounding.
3. Only start when: auto-start is on (`@AppStorage("liveActivityAutoStart")`, default true), a
   recipe detail with steps is on screen, not all steps are done, and
   `ActivityAuthorizationInfo().areActivitiesEnabled`.
4. **User dismissal**: watch `activity.activityStateUpdates`. A `.dismissed` the app didn't
   cause means the user swiped it off the Lock Screen: don't restart for that same step.
   Swiping the Dynamic Island sideways only hides it; nothing to do.
5. **End cooking session** button: end every `Activity<CookingActivityAttributes>.activities`
   and stop the timer. On launch, end any activity left from a killed run.
6. Live Activities need no special capability or push setup for this (no push updates).
7. Tapping the Live Activity opens the app: pass `.widgetURL(URL(string: "cookbook://recipe/<id>"))`
   and handle it with `.onOpenURL` to show that recipe (register the `cookbook` URL scheme).

The natural flow: "Watch on Instagram" in the app opens the reel in the Instagram app
(`UIApplication.shared.open(video.url)`), the app goes inactive, and the step appears in the
Dynamic Island while the reel plays.

## 7. Build order (each step ends runnable)

Every check runs on the real iPhone against the PC server (no Simulator, see section 3).

1. Theme + models + API client; a debug list of titles from the server. **Check:** 89 titles.
2. Cookbook feed with thumbnails, search, filters, favorite heart (PATCH).
3. Recipe detail: hero, caption ("See more"), pills, ingredient row, Tried / Watch buttons.
4. Cooking mode: focus card with step ingredients, Next / Previous, done steps at 0.4
   opacity, progress saved per recipe, step timers parsed from step text
   (`web/lib/stepTimer.ts`: "28-32 minutes" -> 28 min, low end of a range).
5. Settings: server URL (the PC's IP), connection test, Dynamic Island switch.
6. Live Activity: attributes, widget layouts, controller + scenePhase. **Check** on the
   iPhone: open a recipe, press Home: island shows; reopen: it's gone.
7. Pantry screen.
8. Later: offline cache of fetched recipes, adding recipes from the phone (share sheet ->
   `POST` an ingest job; needs a new API endpoint and a job queue on the PC).

## 8. Decided / known gaps

- No cook times in the data (see `api.md`). No ingredient photos (no image source): tiles
  show the amount in large serif type, as on the web.
- Step-to-ingredient links come from text matching on the server; some steps have none.
- The web app (`web/`) stays as the desktop/browser version. Its Capacitor Live Activity
  bridge (`web/lib/liveActivity.ts`, `useLiveActivity.ts`, `LiveActivityToggle.tsx`,
  `web/native/ios/`) is superseded by the native app and can be removed once the native
  widget works.
- The server has no authentication: fine on a home network, not on the open internet.

## 9. Kickoff prompt for Claude Code on the Mac

Paste after sections 1 to 4 are done (data moved, server running, empty Xcode project builds):

> We're on the `ios-app` branch; keep all work there (`main` is the published web version).
> Read `CLAUDE.md`, `docs/ios/README.md` and `docs/ios/api.md`. First update CLAUDE.md's
> environment notes for this Mac and fix `.claude/launch.json` for macOS. Then build the
> native SwiftUI app in `ios/` following the build order in section 7, one step at a time:
> after each step, build with `xcodebuild` for the connected iPhone (no Simulator), install
> it, and let me check it against the PC's API before moving on. Decode exactly the JSON in api.md. Follow the
> Live Activity lifecycle rules in section 6.
