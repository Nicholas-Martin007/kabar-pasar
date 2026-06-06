import SwiftUI
import WidgetKit

@main
struct StockWidgetBundle: WidgetBundle {
    var body: some Widget {
        // Live Activities require iOS 16.2+.
        if #available(iOS 16.2, *) {
            StockLiveActivity()
        }
    }
}
