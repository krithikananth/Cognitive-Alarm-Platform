# Assets

| File | Purpose | Status |
| --- | --- | --- |
| `alarm.mp3` | Looping alarm tone used as the `icap-alarm` notification channel sound (spec §6.1) | Committed |

`plugins/withAlarmSound.js` copies `alarm.mp3` into
`android/app/src/main/res/raw/` on every `expo prebuild`, so a `--clean` run cannot drop
it. The plugin fails the build if the file is missing — a silent skip would only surface
as a too-quiet alarm on a real phone.

Replacing the tone needs a fresh install (or cleared app data): Android freezes a
notification channel's sound when the channel is first created.

App icon and splash assets are intentionally omitted so Expo's defaults are used until
branding is decided.

