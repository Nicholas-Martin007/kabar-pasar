import ActivityKit
import SwiftUI
import WidgetKit

// MARK: - Shared helpers

private func changeColor(_ percent: Double) -> Color {
    if percent > 0 { return .green }
    if percent < 0 { return .red }
    return .secondary
}

private func formatPercent(_ percent: Double) -> String {
    let sign = percent > 0 ? "+" : ""
    return "\(sign)\(String(format: "%.2f", percent))%"
}

// MARK: - Lock screen / banner

@available(iOS 16.2, *)
struct StockLockScreenView: View {
    let context: ActivityViewContext<StockActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(context.attributes.ticker)
                        .font(.headline).bold()
                    Text(context.attributes.companyName)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(context.state.price)
                        .font(.headline).monospacedDigit()
                    Text(formatPercent(context.state.changePercent))
                        .font(.caption).bold()
                        .foregroundColor(changeColor(context.state.changePercent))
                }
            }

            Divider()

            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "newspaper.fill")
                    .font(.caption2)
                    .foregroundColor(.accentColor)
                Text(context.state.headline)
                    .font(.caption)
                    .lineLimit(2)
            }
        }
        .padding()
        .activityBackgroundTint(Color.black.opacity(0.55))
        .activitySystemActionForegroundColor(.white)
    }
}

// MARK: - Widget configuration (lock screen + Dynamic Island)

@available(iOS 16.2, *)
struct StockLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: StockActivityAttributes.self) { context in
            StockLockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    VStack(alignment: .leading) {
                        Text(context.attributes.ticker).font(.headline).bold()
                        Text(context.state.price).font(.caption).monospacedDigit()
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(formatPercent(context.state.changePercent))
                        .font(.headline).bold()
                        .foregroundColor(changeColor(context.state.changePercent))
                }
                DynamicIslandExpandedRegion(.bottom) {
                    Text(context.state.headline)
                        .font(.caption)
                        .lineLimit(2)
                }
            } compactLeading: {
                Text(context.attributes.ticker).font(.caption2).bold()
            } compactTrailing: {
                Text(formatPercent(context.state.changePercent))
                    .font(.caption2)
                    .foregroundColor(changeColor(context.state.changePercent))
            } minimal: {
                Text(String(context.attributes.ticker.prefix(2)))
                    .font(.caption2).bold()
            }
            .keylineTint(changeColor(context.state.changePercent))
        }
    }
}
