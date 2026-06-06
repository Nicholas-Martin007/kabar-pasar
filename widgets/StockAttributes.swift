import ActivityKit
import Foundation

// Shared between the app (Module.swift) and the widget extension
// (StockLiveActivity.swift). Both targets must compile this file.
struct StockActivityAttributes: ActivityAttributes {
    public typealias ContentState = StockContentState

    // Static data — set once when the activity starts.
    var ticker: String        // e.g. "BBCA"
    var companyName: String    // e.g. "Bank Central Asia"
}

// Dynamic data — updated locally or via push.
struct StockContentState: Codable, Hashable {
    var price: String          // pre-formatted, e.g. "Rp 10.250"
    var changePercent: Double  // e.g. -1.24
    var headline: String       // latest news headline for this ticker
    var updatedAt: String      // ISO 8601 timestamp
}
