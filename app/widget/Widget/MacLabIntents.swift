// System-facing actions for the guarded macOS Lab. These intents only hand a
// short-lived request to the desktop host. They never arm control mode: the
// operator still does that explicitly in the dashboard, and panic stop remains
// safe and idempotent whether control is armed or not.

import AppIntents

public struct OpenMacLabIntent: AppIntent {
    public static let title: LocalizedStringResource = "Open macOS Lab"
    public static let description = IntentDescription("Opens the live macOS application lab in os-lab.")
    public static let openAppWhenRun: Bool = true

    public init() {}

    public func perform() async throws -> some IntentResult {
        try WidgetConfig.requestMacLab(.open)
        return .result()
    }
}

public struct PanicStopMacLabIntent: AppIntent {
    public static let title: LocalizedStringResource = "Panic stop macOS Lab"
    public static let description = IntentDescription("Disarms macOS Lab control, closes deep-inspect sessions, and ends mirror streams.")
    public static let openAppWhenRun: Bool = true

    public init() {}

    public func perform() async throws -> some IntentResult {
        try WidgetConfig.requestMacLab(.panicStop)
        return .result()
    }
}

public struct OSLabAppShortcuts: AppShortcutsProvider {
    public static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: OpenMacLabIntent(),
            phrases: [
                "Open macOS Lab in \(.applicationName)",
                "Show Mac Lab in \(.applicationName)",
            ],
            shortTitle: "Open macOS Lab",
            systemImageName: "macwindow"
        )

        AppShortcut(
            intent: PanicStopMacLabIntent(),
            phrases: [
                "Panic stop macOS Lab in \(.applicationName)",
                "Stop Mac control in \(.applicationName)",
            ],
            shortTitle: "Panic stop Mac Lab",
            systemImageName: "stop.circle"
        )
    }

    public static var shortcutTileColor: ShortcutTileColor { .orange }
}
