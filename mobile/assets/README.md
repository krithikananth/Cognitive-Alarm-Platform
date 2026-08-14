# Assets

| File | Purpose | Status |
| --- | --- | --- |
| `alarm.mp3` | Looping alarm tone used as the `icap-alarm` notification channel sound (spec §6.1) | **Not committed** — add a real audio file here |

`alarm.mp3` is binary and cannot be generated. Drop a looping tone in this folder before
running `expo prebuild`; the Notifee channel definition (`src/alarm/channel.js`, task 6)
copies it into `android/app/src/main/res/raw/`.

App icon and splash assets are intentionally omitted so Expo's defaults are used until
branding is decided.
