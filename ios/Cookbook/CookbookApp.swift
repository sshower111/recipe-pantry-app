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

    init() {
        // Thumbnails come from the Mac; keep them on the phone between launches.
        URLCache.shared = URLCache(memoryCapacity: 50_000_000, diskCapacity: 200_000_000)
    }

    var body: some Scene {
        WindowGroup {
            CookbookView()
                .environment(store)
        }
    }
}
