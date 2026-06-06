import ActivityKit
import Foundation

// Native bridge that the JS layer (src/services/liveActivity.ts) calls.
//
// ⚠️ VERIFY ON DEVICE: react-native-widget-extension forwards the JS
// `startActivity(...)` / `updateActivity(...)` arguments positionally to the
// methods below. After `npm i react-native-widget-extension`, open the
// installed package's README/TS types and confirm the exposed method names
// and argument ORDER match this file. Adjust either side until they line up.
//
// This struct mirrors StockActivityAttributes — keep the field order in sync
// with src/services/liveActivity.ts.

@objc(WidgetModule)
class WidgetModule: NSObject {

    @objc
    func areActivitiesEnabled(_ resolve: @escaping (Bool) -> Void) {
        if #available(iOS 16.2, *) {
            resolve(ActivityAuthorizationInfo().areActivitiesEnabled)
        } else {
            resolve(false)
        }
    }

    // Returns the new activity id (string) so JS can track / end it later.
    @objc
    func startActivity(
        _ ticker: String,
        companyName: String,
        price: String,
        changePercent: Double,
        headline: String,
        updatedAt: String
    ) -> String {
        guard #available(iOS 16.2, *),
              ActivityAuthorizationInfo().areActivitiesEnabled else {
            return ""
        }

        let attributes = StockActivityAttributes(ticker: ticker, companyName: companyName)
        let state = StockContentState(
            price: price,
            changePercent: changePercent,
            headline: headline,
            updatedAt: updatedAt
        )

        do {
            let activity = try Activity.request(
                attributes: attributes,
                content: .init(state: state, staleDate: nil),
                pushType: nil   // Phase 2: switch to .token for APNs push updates
            )
            return activity.id
        } catch {
            return ""
        }
    }

    @objc
    func updateActivity(
        _ activityId: String,
        price: String,
        changePercent: Double,
        headline: String,
        updatedAt: String
    ) {
        guard #available(iOS 16.2, *) else { return }
        let state = StockContentState(
            price: price,
            changePercent: changePercent,
            headline: headline,
            updatedAt: updatedAt
        )
        Task {
            for activity in Activity<StockActivityAttributes>.activities
            where activity.id == activityId {
                await activity.update(.init(state: state, staleDate: nil))
            }
        }
    }

    @objc
    func endActivity(_ activityId: String) {
        guard #available(iOS 16.2, *) else { return }
        Task {
            for activity in Activity<StockActivityAttributes>.activities
            where activity.id == activityId {
                await activity.end(nil, dismissalPolicy: .immediate)
            }
        }
    }
}
