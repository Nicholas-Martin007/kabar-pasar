# iOS Live Activities — Setup & Verification

Stock Live Activity for Kabar Pasar: ticker + price + change + latest headline
on the lock screen and Dynamic Island; tap to open the news in the app.

> **Status:** scaffolded on branch `feature/ios-live-activity`. The native code
> here is written but **unverified** — it must be built and tested on a physical
> iPhone. None of this runs in Expo Go.

---

## What's in this scaffold

| File | Role | Confidence |
|---|---|---|
| `app.json` | Plugin + `NSSupportsLiveActivities` | High |
| `widgets/StockAttributes.swift` | Shared data model (static + dynamic state) | High |
| `widgets/StockLiveActivity.swift` | SwiftUI lock-screen + Dynamic Island UI | High |
| `widgets/StockWidgetBundle.swift` | Widget entry point | High |
| `widgets/Module.swift` | Native bridge (start/update/end) | **Verify** |
| `src/services/liveActivity.ts` | Typed JS wrapper | High |
| `src/hooks/useStockLiveActivity.ts` | Screen-level hook | High |

The **Verify** row is the one integration seam — see step 4.

---

## Prerequisites

- **Apple Developer Program** membership (for code-signing a device build).
- A **physical iPhone**, iOS **16.2+** (Live Activities don't fully work in the
  simulator; push needs iOS 17.2+ for push-to-start).
- **You're on Windows** → no Xcode/simulator locally. Use **EAS Build** to
  compile the dev client in Expo's cloud, then install on your iPhone:
  ```bash
  npm i -g eas-cli && eas login
  eas build --profile development --platform ios
  ```
  Install the resulting build on your device, then `npx expo start --dev-client`.

---

## Steps

### 1. Install the library
```bash
npm i react-native-widget-extension
```

### 2. Config is already wired
`app.json` already has the plugin (`widgetsFolder: "widgets"`,
`deploymentTarget: "16.2"`) and `ios.infoPlist.NSSupportsLiveActivities = true`.

### 3. Prebuild (generates the native iOS project + widget target)
```bash
npx expo prebuild -p ios --clean
```
> ⚠️ **Cross-target gotcha:** `widgets/StockAttributes.swift` must be a compile
> source of **both** the main app target **and** the widget extension target
> (the bridge and the UI both reference it). The plugin adds the `widgets/`
> folder to the extension; confirm in Xcode → the file's *Target Membership*
> includes the app target too. This is the #1 cause of "type not found" build
> errors.

### 4. Verify the native bridge signature  ⚠️
Open the installed `react-native-widget-extension` README / TS types and confirm:
- the exported method names match `widgets/Module.swift`
  (`startActivity`, `updateActivity`, `endActivity`, `areActivitiesEnabled`);
- the **argument order** matches `src/services/liveActivity.ts`
  (`ticker, companyName, price, changePercent, headline, updatedAt`).

If the installed version expects a fixed/different signature, adjust **both**
`Module.swift` and `liveActivity.ts` so they agree. They're the two ends of the
same wire — keep them in lock-step with `StockAttributes.swift`.

### 5. Wire it into a screen
Example for Stock Detail (`app/stock/[ticker].tsx`):
```tsx
import { useStockLiveActivity } from '@/src/hooks/useStockLiveActivity';

const live = useStockLiveActivity();

// when the user taps "Pin to Lock Screen":
live.start(
  { ticker: stock.ticker, companyName: stock.name },
  { price: stock.priceLabel, changePercent: stock.changePercent, headline: latestNews.title }
);

// when fresh data arrives while app is open:
live.update({ price, changePercent, headline });

// to stop:
live.end();
```

### 6. Test on device
- Run the dev client, trigger `start`, lock the phone → activity on lock screen.
- Long-press / Dynamic Island → expanded view.
- Trigger `update` → values change live.

---

## Phase 2 — Push updates (lock screen refreshes when app is closed)

Local updates only fire while the app runs. For "glance anytime", push to the
activity's token via **APNs** (`apns-push-type: liveactivity`):

1. In `Module.swift`, start the activity with `pushType: .token` and forward
   `activity.pushTokenUpdates` to JS; send that token to the backend.
2. Backend stores the per-activity token and POSTs state updates to APNs
   HTTP/2 with a **token-based key (.p8)**.
3. ⚠️ **FCM caveat:** Firebase Cloud Messaging does **not** relay the
   `liveactivity` push type — talk to **APNs directly** (verify against current
   FCM docs before building). This is separate from your existing FCM push for
   regular notifications.
4. Keep the payload tiny (~4 KB): ticker, price, change, headline, deep link.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "type 'StockActivityAttributes' not found" | `StockAttributes.swift` not in app target membership (step 3) |
| JS calls do nothing, no error | Native module not built — running in Expo Go, not the dev client |
| `areActivitiesEnabled()` false | User disabled Live Activities in iOS Settings → app |
| Build fails on deployment target | Confirm widget target is iOS 16.2+ |
