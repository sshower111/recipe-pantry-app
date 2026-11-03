//
//  CookbookApp.swift
//  Cookbook
//
//  Created by Keith Lam on 11/3/26.
//

import SwiftUI

@main
struct CookbookApp: App {
    @State private var store = RecipeStore()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // Thumbnails come from the PC; keep them on the phone between launches.
        URLCache.shared = URLCache(memoryCapacity: 50_000_000, diskCapacity: 200_000_000)
    }

    var body: some Scene {
        WindowGroup {
            CookbookView()
                .environment(store)
        }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            // Back in the app (including at launch): the Live Activity has done its job.
            case .active: Task { await LiveActivityController.endAll() }
            // Leaving: start while iOS still allows it (it refuses once in the background).
            case .inactive: Task { await LiveActivityController.startOnLeave() }
            // Try again in case `.inactive` was missed; after Watch, show the expanded island once.
            case .background:
                Task {
                    await LiveActivityController.startOnLeave()
                    await LiveActivityController.announce()
                }
            @unknown default: break
            }
        }
    }
}
