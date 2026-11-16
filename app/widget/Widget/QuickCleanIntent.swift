// CLW-05: the widget's one action — ask the host app to build the quick-clean
// plan of the user's quickClean-flagged bookmarks. The intent only writes a
// timestamped request file and opens the app; the plan → confirm → run flow
// still happens in the dashboard, and the engine's safety guards apply.

import AppIntents
import Foundation

public struct QuickCleanIntent: AppIntent {
    public static let title: LocalizedStringResource = "Quick clean"
    public static let description = IntentDescription("Opens os-lab and reviews a Trash-only cleanup plan of your quick-clean bookmarks.")
    public static let openAppWhenRun: Bool = true

    public init() {}

    public func perform() async throws -> some IntentResult {
        WidgetConfig.requestQuickClean()
        return .result()
    }
}
