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

/// Opens the guarded macOS Lab in the workflow used to inspect a submission
/// and capture evidence. The intent deliberately does not identify a student,
/// launch submitted code, arm control, or send input.
public struct VerifyLabSubmissionIntent: AppIntent {
    public static let title: LocalizedStringResource = "Verify Lab Submission"
    public static let description = IntentDescription("Opens macOS Lab to inspect a lab submission and capture evidence safely.")
    public static let openAppWhenRun: Bool = true

    public init() {}

    public func perform() async throws -> some IntentResult {
        try WidgetConfig.requestMacLab(.verifySubmission)
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
            intent: VerifyLabSubmissionIntent(),
            phrases: [
                "Verify a lab submission in \(.applicationName)",
                "Review student lab work in \(.applicationName)",
            ],
            shortTitle: "Verify submission",
            systemImageName: "doc.text.magnifyingglass"
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
