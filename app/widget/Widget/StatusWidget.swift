// CLW-06: the widget itself. macOS targets only — systemSmall / systemMedium
// / systemLarge in Notification Center or on the desktop. The reference
// app's iOS lock-screen accessory families are deliberately not shipped.

import WidgetKit
import SwiftUI

struct StatusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: WidgetSnapshot

    var body: some View {
        Group {
            switch family {
            case .systemSmall:
                SmallWidgetView(snapshot: snapshot)
            case .systemMedium:
                MediumWidgetView(snapshot: snapshot)
            default:
                LargeWidgetView(snapshot: snapshot)
            }
        }
        .widgetURL(WidgetConfig.Route.dashboard.url)
        .containerBackground(WidgetColors.resolved(for: colorScheme).bg, for: .widget)
    }
}

struct OSLabStatusWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: WidgetConfig.statusKind, provider: SnapshotProvider()) { entry in
            StatusWidgetView(snapshot: entry.snapshot)
        }
        .configurationDisplayName("os-lab Cleanup")
        .description("Disk space, scan status and cleanup totals at a glance, kept fresh by the os-lab console.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}
