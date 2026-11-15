// CLW-07: the shared widget views, ported from the QleanerPro reference
// layouts with os-lab's own tokens and data. Every number comes from the
// snapshot; anything missing renders as an honest dash.

import SwiftUI

func bytes(_ value: Int?) -> String {
    guard let value else { return "—" }
    return ByteCountFormatter.string(fromByteCount: Int64(value), countStyle: .file)
}

func relativeTime(_ seconds: Double?) -> String {
    guard let seconds, seconds > 0 else { return "Never" }
    let date = Date(timeIntervalSince1970: seconds)
    let formatter = RelativeDateTimeFormatter()
    formatter.unitsStyle = .abbreviated
    return formatter.localizedString(for: date, relativeTo: .now)
}

// MARK: - Header

struct WidgetHeader: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot
    let compact: Bool

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        HStack(spacing: 8) {
            Image(systemName: "broom")
                .font(.system(size: compact ? 13 : 15, weight: .semibold))
                .foregroundStyle(colors.accent)
            Text("os-lab")
                .font(.system(size: compact ? 12 : 14, weight: .semibold))
                .foregroundStyle(colors.fg)
            Spacer()
            Circle()
                .fill(statusDot)
                .frame(width: 6, height: 6)
        }
    }

    private var statusDot: Color {
        let colors = WidgetColors.resolved(for: colorScheme)
        switch snapshot.status {
        case "cleaning", "scanning": return colors.warning
        case "ready-to-clean": return colors.accent
        default: return colors.success
        }
    }
}

// MARK: - Metric tile

struct WidgetMetricTile: View {
    @Environment(\.colorScheme) private var colorScheme
    let title: String
    let value: String
    var tint: ((WidgetColors) -> Color)?

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(tint?(colors) ?? colors.accent)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(title)
                .font(.system(size: 9))
                .foregroundStyle(colors.mutedFg)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Progress bar

struct WidgetProgressBar: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 4) {
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(colors.border)
                    Capsule()
                        .fill(colors.warning)
                        .frame(width: proxy.size.width * progressFraction)
                }
            }
            .frame(height: 5)
            Text("Scanning \(snapshot.progress?.done ?? 0)/\(snapshot.progress?.total ?? 0)")
                .font(.system(size: 9))
                .foregroundStyle(colors.mutedFg)
        }
    }

    private var progressFraction: CGFloat {
        guard let progress = snapshot.progress, progress.total > 0 else { return 0.15 }
        return CGFloat(min(1, Double(progress.done) / Double(progress.total)))
    }
}

// MARK: - Disk gauge

struct WidgetDiskGauge: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 4) {
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(colors.border)
                    Capsule()
                        .fill(diskColor(colors))
                        .frame(width: proxy.size.width * snapshot.diskUsedPercent / 100)
                }
            }
            .frame(height: 6)
            Text("\(Int(snapshot.diskUsedPercent))% of disk used")
                .font(.system(size: 9))
                .foregroundStyle(colors.mutedFg)
        }
    }

    private func diskColor(_ colors: WidgetColors) -> Color {
        snapshot.diskUsedPercent >= 90 ? colors.danger : colors.accent
    }
}

// MARK: - Quick clean button

struct QuickCleanButton: View {
    @Environment(\.colorScheme) private var colorScheme
    let compact: Bool

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        Button(intent: QuickCleanIntent()) {
            Label(compact ? "Quick clean" : "Review quick clean", systemImage: "broom")
                .font(.system(size: compact ? 10 : 11, weight: .semibold))
        }
        .buttonStyle(.plain)
        .foregroundStyle(colors.accent)
        .padding(.horizontal, compact ? 8 : 10)
        .padding(.vertical, compact ? 4 : 6)
        .background(colors.accent.opacity(0.14), in: Capsule())
    }
}

// MARK: - Fact row

struct WidgetRow: View {
    @Environment(\.colorScheme) private var colorScheme
    let icon: String
    let text: String

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 10))
                .foregroundStyle(colors.accent)
                .frame(width: 14)
            Text(text)
                .font(.system(size: 11))
                .foregroundStyle(colors.mutedFg)
        }
    }
}

// MARK: - Small layout

struct SmallWidgetView: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 10) {
            WidgetHeader(snapshot: snapshot, compact: true)
            Spacer(minLength: 0)
            Text(snapshot.statusLabel)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(colors.fg)
            Text(snapshot.lastScan.map { "\($0.foundItems) items · \(bytes($0.foundBytes))" } ?? "No scan yet")
                .font(.system(size: 11))
                .foregroundStyle(colors.mutedFg)
            Spacer(minLength: 0)
            if snapshot.progress != nil {
                WidgetProgressBar(snapshot: snapshot)
            } else {
                HStack {
                    Text("Scanned \(relativeTime(snapshot.lastScan?.finishedAt))")
                        .font(.system(size: 9))
                        .foregroundStyle(colors.mutedFg)
                    Spacer(minLength: 0)
                    QuickCleanButton(compact: true)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

// MARK: - Medium layout

struct MediumWidgetView: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                WidgetHeader(snapshot: snapshot, compact: false)
                if snapshot.progress == nil && snapshot.bookmarks.quickCleanCount > 0 {
                    QuickCleanButton(compact: true)
                }
            }
            Text(snapshot.statusLabel)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(colors.fg)
            HStack(spacing: 16) {
                WidgetMetricTile(title: "Found", value: snapshot.lastScan.map { "\($0.foundItems) items" } ?? "—")
                WidgetMetricTile(title: "Reclaimable", value: bytes(snapshot.lastScan?.foundBytes))
                WidgetMetricTile(title: "Disk free", value: bytes(snapshot.disk.freeBytes), tint: { $0.success })
            }
            if snapshot.progress != nil {
                WidgetProgressBar(snapshot: snapshot)
            } else if snapshot.monitor.enabled {
                Text("Monitor every \(snapshot.monitor.intervalSeconds ?? 0) s · next \(relativeTime(snapshot.monitor.nextCheckAt))")
                    .font(.system(size: 10))
                    .foregroundStyle(snapshot.monitor.warningCount > 0 ? WidgetColors.resolved(for: colorScheme).danger : WidgetColors.resolved(for: colorScheme).mutedFg)
            } else {
                Text("Scanned \(relativeTime(snapshot.lastScan?.finishedAt))")
                    .font(.system(size: 10))
                    .foregroundStyle(colors.mutedFg)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

// MARK: - Large layout

struct LargeWidgetView: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        let colors = WidgetColors.resolved(for: colorScheme)
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                WidgetHeader(snapshot: snapshot, compact: false)
                if snapshot.progress == nil && snapshot.bookmarks.quickCleanCount > 0 {
                    QuickCleanButton(compact: false)
                }
            }
            Text(snapshot.statusLabel)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(colors.fg)
            HStack(spacing: 16) {
                WidgetMetricTile(title: "Found", value: snapshot.lastScan.map { "\($0.foundItems) items" } ?? "—")
                WidgetMetricTile(title: "Reclaimable", value: bytes(snapshot.lastScan?.foundBytes))
            }
            HStack(spacing: 16) {
                WidgetMetricTile(title: "Disk free", value: bytes(snapshot.disk.freeBytes), tint: { $0.success })
                WidgetMetricTile(title: "Total reclaimed", value: bytes(snapshot.cleanup.totalReclaimedBytes), tint: { $0.accent })
            }
            if snapshot.progress != nil {
                WidgetProgressBar(snapshot: snapshot)
            } else {
                WidgetDiskGauge(snapshot: snapshot)
            }
            Divider().overlay(colors.border)
            VStack(alignment: .leading, spacing: 6) {
                WidgetRow(icon: "clock.arrow.circlepath", text: "Last scan \(relativeTime(snapshot.lastScan?.finishedAt))")
                WidgetRow(icon: "trash", text: "Last cleanup \(relativeTime(snapshot.cleanup.lastRunAt))")
                if snapshot.monitor.enabled {
                    WidgetRow(icon: "waveform.path.ecg",
                              text: snapshot.monitor.warningCount > 0
                                ? "Monitor warning · next check \(relativeTime(snapshot.monitor.nextCheckAt))"
                                : "Monitor every \(snapshot.monitor.intervalSeconds ?? 0) s · next \(relativeTime(snapshot.monitor.nextCheckAt))")
                } else {
                    WidgetRow(icon: "waveform.slash", text: "Background monitor is off")
                }
                WidgetRow(icon: "sparkles",
                          text: snapshot.bookmarks.quickCleanCount > 0
                            ? "\(snapshot.bookmarks.quickCleanCount) bookmarks ready for quick clean"
                            : "\(snapshot.bookmarks.count) bookmarks, none flagged for quick clean")
                if snapshot.permissions.fullDiskAccess == false {
                    WidgetRow(icon: "lock", text: "Full Disk Access missing — some folders stay unreadable")
                }
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}
