// Registers the app's own LiveActivity plugin with Capacitor. In Main.storyboard, set the
// Bridge View Controller's custom class to MainViewController (module: App).

import Capacitor
import UIKit

class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(LiveActivityManager())
    }
}
