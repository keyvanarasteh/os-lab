// CLW-03: the constants shared by the widget extension, the reloader
// framework and the Rust host. The Python engine re-declares the same names
// (cleanup_lab/widget.py) — changing one side changes all of them.

import Foundation

public enum WidgetConfig {
    public static let appGroupID = "group.com.keyvanarasteh.oslab"
    public static let snapshotFileName = "widget-snapshot.json"
    public static let pendingQuickCleanFileName = "widget-pending-quick-clean.txt"
    public static let statusKind = "com.keyvanarasteh.oslab.widget.StatusWidget"
    public static let urlScheme = "oslab"

    /// The file the quick-clean intent writes; the host consumes it once on
    /// focus with a max age so a stale request can never re-trigger.
    public static func requestQuickClean() {
        guard let url = pendingQuickCleanFileURL else { return }
        let timestamp = String(Date.now.timeIntervalSince1970)
        try? timestamp.data(using: .utf8)?.write(to: url, options: [.atomic])
    }

    /// Dashboard routes the widget opens. Values match the overview card
    /// targets and the cleanup island's tab paths.
    public enum Route: String, CaseIterable {
        case dashboard
        case scan
        case results
        case leftovers
        case history
        case space
        case bookmarks = "cleanup-bookmarks"
        case monitor = "cleanup-monitor"
        case permissions = "cleanup-permissions"
        case widgets = "cleanup-widgets"

        public var url: URL? {
            URL(string: "\(WidgetConfig.urlScheme)://\(rawValue)")
        }
    }

    public static var snapshotFileURL: URL? {
        sharedContainerURL()?.appendingPathComponent(snapshotFileName, isDirectory: false)
    }

    public static var pendingQuickCleanFileURL: URL? {
        sharedContainerURL()?.appendingPathComponent(pendingQuickCleanFileName, isDirectory: false)
    }

    private static func sharedContainerURL() -> URL? {
        guard let url = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupID) else { return nil }
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
