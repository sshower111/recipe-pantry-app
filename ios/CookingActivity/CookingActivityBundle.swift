//
//  CookingActivityBundle.swift
//  CookingActivity
//
//  Created by Keith Lam on 11/3/26.
//

import WidgetKit
import SwiftUI

@main
struct CookingActivityBundle: WidgetBundle {
    var body: some Widget {
        CookingActivity()
        CookingActivityLiveActivity()
    }
}
