// CLW-06: the extension's entry point.

import WidgetKit
import SwiftUI

@main
struct OSLabWidgetsBundle: WidgetBundle {
    var body: some Widget {
        OSLabStatusWidget()
    }
}
