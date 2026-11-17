// CLW-04: the host app's reload bridge. The Tauri process cannot call the
// Swift-only WidgetCenter API directly, so this tiny framework — embedded in
// Contents/Frameworks and dlopen'd from Rust — exposes one @objc class
// method that asks WidgetKit to re-read the published snapshot. Missing
// framework or class degrades to the widget's own 15-minute refresh policy.

import WidgetKit
import Foundation

@objc(OSLabWidgetReloader)
public final class OSLabWidgetReloader: NSObject {
    /// Ask WidgetKit to reload every os-lab widget timeline.
    @objc public static func reloadAllTimelines() {
        WidgetCenter.shared.reloadAllTimelines()
    }
}
