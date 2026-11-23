// CLW-06: the widget-side mirror of the engine's widget snapshot
// (cleanup-lab/engine/cleanup_lab/widget.py). The extension is a separate
// module and cannot import the Python engine, so the field names here are the
// contract — keep them in sync with the payload GET /api/cleanup/widget
// writes into the App Group container. Times are epoch seconds (the console
// style), not ISO dates.

import Foundation

public struct WidgetSnapshot: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var capturedAt: Double
    public var platform: String
    public var capable: Bool
    public var disk: Disk
    public var lastScan: LastScan?
    public var progress: Progress?
    public var cleanup: Cleanup
    public var monitor: Monitor
    public var bookmarks: Bookmarks
    public var permissions: Permissions
    public var status: String

    public struct Disk: Codable, Equatable, Sendable {
        public var mountPoint: String?
        public var totalBytes: Int?
        public var freeBytes: Int?
        public var usedPercent: Double?

        public init(mountPoint: String? = nil, totalBytes: Int? = nil, freeBytes: Int? = nil, usedPercent: Double? = nil) {
            self.mountPoint = mountPoint
            self.totalBytes = totalBytes
            self.freeBytes = freeBytes
            self.usedPercent = usedPercent
        }
    }

    public struct LastScan: Codable, Equatable, Sendable {
        public var finishedAt: Double?
        public var foundItems: Int
        public var foundBytes: Int
        public var unreadable: Int

        public init(finishedAt: Double? = nil, foundItems: Int = 0, foundBytes: Int = 0, unreadable: Int = 0) {
            self.finishedAt = finishedAt
            self.foundItems = foundItems
            self.foundBytes = foundBytes
            self.unreadable = unreadable
        }
    }

    public struct Progress: Codable, Equatable, Sendable {
        public var done: Int
        public var total: Int

        public init(done: Int = 0, total: Int = 0) {
            self.done = done
            self.total = total
        }
    }

    public struct Cleanup: Codable, Equatable, Sendable {
        public var totalReclaimedBytes: Int
        public var lastRunAt: Double?

        public init(totalReclaimedBytes: Int = 0, lastRunAt: Double? = nil) {
            self.totalReclaimedBytes = totalReclaimedBytes
            self.lastRunAt = lastRunAt
        }
    }

    public struct Monitor: Codable, Equatable, Sendable {
        public var enabled: Bool
        public var intervalSeconds: Int?
        public var nextCheckAt: Double?
        public var lastWarningAt: Double?
        public var warningCount: Int

        public init(enabled: Bool = false, intervalSeconds: Int? = nil, nextCheckAt: Double? = nil,
                    lastWarningAt: Double? = nil, warningCount: Int = 0) {
            self.enabled = enabled
            self.intervalSeconds = intervalSeconds
            self.nextCheckAt = nextCheckAt
            self.lastWarningAt = lastWarningAt
            self.warningCount = warningCount
        }
    }

    public struct Bookmarks: Codable, Equatable, Sendable {
        public var count: Int
        public var quickCleanCount: Int
        public var hookCount: Int
        public var alertCount: Int

        public init(count: Int = 0, quickCleanCount: Int = 0, hookCount: Int = 0, alertCount: Int = 0) {
            self.count = count
            self.quickCleanCount = quickCleanCount
            self.hookCount = hookCount
            self.alertCount = alertCount
        }
    }

    public struct Permissions: Codable, Equatable, Sendable {
        public var fullDiskAccess: Bool?

        public init(fullDiskAccess: Bool? = nil) {
            self.fullDiskAccess = fullDiskAccess
        }
    }

    public init(
        schemaVersion: Int = 1,
        capturedAt: Double = 0,
        platform: String = "macos",
        capable: Bool = false,
        disk: Disk = .init(),
        lastScan: LastScan? = nil,
        progress: Progress? = nil,
        cleanup: Cleanup = .init(totalReclaimedBytes: 0, lastRunAt: nil),
        monitor: Monitor = .init(enabled: false, intervalSeconds: nil, nextCheckAt: nil, lastWarningAt: nil, warningCount: 0),
        bookmarks: Bookmarks = .init(count: 0, quickCleanCount: 0, hookCount: 0, alertCount: 0),
        permissions: Permissions = .init(fullDiskAccess: nil),
        status: String = "up-to-date"
    ) {
        self.schemaVersion = schemaVersion
        self.capturedAt = capturedAt
        self.platform = platform
        self.capable = capable
        self.disk = disk
        self.lastScan = lastScan
        self.progress = progress
        self.cleanup = cleanup
        self.monitor = monitor
        self.bookmarks = bookmarks
        self.permissions = permissions
        self.status = status
    }

    /// The engine's derivation, repeated defensively for hand-written files.
    public var statusLabel: String {
        switch status {
        case "cleaning": return "Cleaning"
        case "scanning": return "Scanning"
        case "ready-to-clean": return "Ready to clean"
        default: return "Up to date"
        }
    }

    public var diskUsedPercent: Double {
        min(100, max(0, disk.usedPercent ?? 0))
    }

    /// The demo state the widget gallery renders while nothing is published.
    public static let placeholder = WidgetSnapshot(
        capturedAt: Date.now.timeIntervalSince1970,
        capable: true,
        disk: .init(mountPoint: "/", totalBytes: 500_000_000_000, freeBytes: 232_800_000_000, usedPercent: 53.4),
        lastScan: .init(finishedAt: Date.now.timeIntervalSince1970 - 3_600, foundItems: 18, foundBytes: 4_200_000_000, unreadable: 0),
        cleanup: .init(totalReclaimedBytes: 32_000_000_000, lastRunAt: Date.now.timeIntervalSince1970 - 86_400),
        monitor: .init(enabled: true, intervalSeconds: 300, nextCheckAt: Date.now.timeIntervalSince1970 + 300, lastWarningAt: nil, warningCount: 0),
        bookmarks: .init(count: 3, quickCleanCount: 2, hookCount: 1, alertCount: 0),
        permissions: .init(fullDiskAccess: true),
        status: "ready-to-clean"
    )

    public static let empty = WidgetSnapshot()
}

public enum WidgetSnapshotStore {
    /// Reads the snapshot the console publishes. A missing or unreadable file
    /// degrades to `.empty` — never a crash inside the extension process.
    public static func load() -> WidgetSnapshot {
        guard let url = WidgetConfig.snapshotFileURL,
              let data = try? Data(contentsOf: url),
              let snapshot = try? JSONDecoder().decode(WidgetSnapshot.self, from: data) else {
            return .empty
        }
        return snapshot
    }
}
