# Remnant demo capture (README media)

Run on the Mac, in the iOS Simulator: the one place the project uses a Simulator, with the
user's OK (2026-11-05). The PC keeps serving the real database (`uvicorn` on
`http://192.168.2.23:8000`); the Simulator's app talks to it like the phone does. Shut the
Simulator down when done: the M1 struggles with it next to Xcode.

## Setup

1. `git pull` on the Mac, open `ios/Cookbook.xcodeproj` (the app is Remnant; the project keeps
   its old name), pick an **iPhone 17 Pro** simulator (Dynamic Island), build and run.
2. In the app's Settings, check the server address reaches the PC (the feed fills in).
3. Simulator: Features > Toggle Appearance should be **Light**; set the status bar to a clean
   9:41, full battery, full Wi-Fi:
   `xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100 --wifiBars 3 --cellularBars 4`
4. Screenshots: `xcrun simctl io booted screenshot docs/media/<name>.png`, then convert to
   JPEG (quality ~85, width 1206 is fine) so the README stays light.
   Video: `xcrun simctl io booted recordVideo --codec h264 /tmp/<name>.mov`, Ctrl+C to stop,
   then make a GIF at ~15 fps and 360 px wide with ffmpeg's palettegen/paletteuse; trim dead
   time and keep each GIF under ~5 MB.

## Shots, in README order

Pick recipes with good photos and real ingredient lists: cookies (54), pork belly (114) or
another colourful dish. Never a 🔖 or "not a recipe" post. Nothing personal in frame.

| File | Screen | What makes it worth showing |
|---|---|---|
| `home.jpg` | Simulator home screen, Remnant icon in the dock or first row | The new name and icon |
| `feed.jpg` | Feed, scrolled to the top: "Remnant" title, 3-4 cards with photos | The brand plus real content |
| `pantry.jpg` | Search with 3 chips (e.g. egg, garlic, rice): re-ranked cards showing "uses" / "missing" | The core idea: what can I make with what's left |
| `recipe.jpg` | Recipe screen: photo, ingredient tiles with icons and amounts | Design quality |
| `cooking.jpg` | Cooking mode mid-recipe: step card with its ingredients and a running timer | It's for actually cooking |
| `island.jpg` | Expanded Dynamic Island: step, timer, ‹ › and ✕ | The standout iOS feature |
| `lockscreen.jpg` | Lock Screen Live Activity (Device > Lock, then wake) | Same, on the Lock Screen |

## GIFs

1. **`share.gif`, "Share a reel, get a recipe" (new).** In Safari open an Instagram reel's
   link, Share > **Remnant** ("Sent to Remnant"), switch to the app: the "Adding..." card,
   then the finished recipe opening. The PC takes minutes, so record the share and the
   "Adding..." card, stop, and record again once it lands; join the two with a short cut.
   Best with a **silent reel whose caption has the ingredients**: the steps then come from
   the vision model watching the video, the newest feature. Use a post not already saved
   (or one deleted from the database first), so the share isn't "Already in Remnant".
2. **`demo.gif`, "the step follows you" (redo).** On a recipe in cooking mode with a timer
   running, swipe up to leave the app: the Dynamic Island opens with the step and timer; tap
   › once. 6-10 s.

## README

Replace the old images (`docs/media/*.jpg`, `demo.gif`) with the new ones, add `home.jpg`
and `share.gif` to the top section, and keep each caption to one line saying what to look
at. Commit the media with the README change; delete images no longer used.

## Status (2026-11-05)

Captured: every still and `demo.gif` (pork belly, recipe 114: the cookies photo shows the
creator). Not yet: `share.gif` (needs a reel the user picks; it adds a real recipe on the PC).
`home.jpg` has the icon at the end of the second row: the simulator tool's drags couldn't move
it to the dock. Notes for next time: Xcode 27 here has no Simulator.app, so create the device
(`xcrun simctl create "iPhone 17 Pro" com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro
com.apple.CoreSimulator.SimRuntime.iOS-27-2`) and run it headless; add `--mask black` to
`screenshot`/`recordVideo` for the island cutout; `recordVideo` and the expanded island after
an app leaves show in screenshots, but an island expanded by long-press doesn't (the video has it).
