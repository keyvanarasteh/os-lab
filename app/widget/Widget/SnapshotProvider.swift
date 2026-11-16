// CLW-06: the timeline provider. One entry per build, re-read from the App
// Group container; WidgetKit refreshes on its own budget (15-minute policy)
// and the host app asks for immediate reloads when data changes.

import WidgetKit
import Foundation

struct SnapshotEntry: TimelineEntry {
    let date: Date
    let snapshot: WidgetSnapshot
}

struct SnapshotProvider: TimelineProvider {
    func placeholder(in context: Context) -> SnapshotEntry {
        SnapshotEntry(date: .now, snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (SnapshotEntry) -> Void) {
        completion(SnapshotEntry(date: .now, snapshot: context.isPreview ? .placeholder : WidgetSnapshotStore.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SnapshotEntry>) -> Void) {
        let snapshot = WidgetSnapshotStore.load()
        let entry = SnapshotEntry(date: .now, snapshot: snapshot)
        // Re-read the published file at least every 15 minutes; the host's
        // reload requests make fresh data appear sooner.
        completion(Timeline(entries: [entry], policy: .after(Date.now.addingTimeInterval(15 * 60))))
    }
}
