# 📘 ICAP User Guide

**Intelligent Cognitive Alarm Platform**

This guide covers everything the product actually does today, for all three
roles: **user**, **wellness coach** and **administrator**. Screens, buttons and
labels below match the shipped interface.

- Integrating against the API instead? See
  [api_documentation.md](api_documentation.md).
- Setting the platform up? See the [README](../README.md).

---

## Contents

1. [What ICAP does](#1-what-icap-does)
2. [Creating your account](#2-creating-your-account)
3. [Signing in](#3-signing-in)
4. [Finding your way around](#4-finding-your-way-around)
5. [Setting up your profile](#5-setting-up-your-profile)
6. [Creating and managing alarms](#6-creating-and-managing-alarms)
7. [Waking up: the challenge cycle](#7-waking-up-the-challenge-cycle)
8. [Practice mode](#8-practice-mode)
9. [Your dashboard](#9-your-dashboard)
10. [Challenge analytics](#10-challenge-analytics)
11. [Recommendations](#11-recommendations)
12. [Reports](#12-reports)
13. [Notifications](#13-notifications)
14. [How your scores are calculated](#14-how-your-scores-are-calculated)
15. [For wellness coaches](#15-for-wellness-coaches)
16. [For administrators](#16-for-administrators)
17. [Troubleshooting](#17-troubleshooting)
18. [Your data](#18-your-data)

---

## 1. What ICAP does

ICAP is an alarm platform that will not let you dismiss an alarm until you have
solved a cognitive challenge — a maths problem, a logic puzzle, a memory
sequence, a word game, a pattern, a riddle or a quick quiz.

Around that core it:

- **adapts** the difficulty to your measured performance,
- **records** every wake-up, snooze and challenge attempt,
- **scores** your morning habit out of 100,
- **analyses** your sleep, snooze and wake patterns,
- **coaches** you with recommendations you can rate,
- **reports** all of it, exportable as PDF or Excel.

There are three roles. A **user** owns alarms and habits. A **wellness coach**
sees read-only analytics for the clients an administrator assigns to them. An
**administrator** manages accounts, assignments and platform settings.

---

## 2. Creating your account

1. Open the app and choose **Sign up** on the login page (or go to `/register`).
2. Fill in the form:

   | Field         | Required | Rules                                                       |
   | ------------- | -------- | ----------------------------------------------------------- |
   | **Full Name** | No       | Display name                                                 |
   | **Username**  | Yes      | At least 3 characters; letters, digits and underscores only  |
   | **Email**     | Yes      | Must be unique                                               |
   | **Password**  | Yes      | At least 8 characters, with an uppercase letter, a lowercase letter and a digit |

3. Your **timezone** is detected from your browser and shown in an information
   box. Everything in the product — alarm times, quiet hours, streak days — is
   evaluated in this timezone. You can change it later in **Profile**.
4. Select **Create Account**. You are returned to the sign-in page with the
   message *"Account created! Check your email to verify, then log in."*

### Verifying your email

A verification link is emailed to you. Opening it lands on `/verify-email`,
which verifies the token automatically and offers **Continue to Sign In**.

If the link is missing, expired or already used, the same page shows an error
and a small form: enter your email and select **Resend Verification Email**.

> You can sign in and use the product before verifying, but verification keeps
> password resets and email reminders working. Verification and reset emails are
> limited to **3 requests per 15 minutes**.

---

## 3. Signing in

### With a password

Enter your **email** and **password** and select **Sign In**. You may also type
your username in the email field.

After five failed attempts on the same account the account is locked for
15 minutes and the page reports how long to wait. A successful sign-in clears
the counter.

Your session is held in secure, HttpOnly cookies — no tokens are stored in the
browser where a script could read them. Access is refreshed automatically in
the background, so you stay signed in without re-entering your password.

### With Google

Select **Continue with Google**. You are sent to Google's consent screen and
returned to the app already signed in. If Google sign-in has not been configured
by your administrator, you are returned to the login page with an explanatory
message.

### If you forget your password

1. Select **Forgot password?** on the login page.
2. Enter your email and select **Send Reset Link**. The confirmation is
   deliberately generic — *"If an account with that email exists, a password
   reset link has been sent"* — so nobody can use the form to discover which
   addresses are registered.
3. Open the link, set a new password twice, and select **Reset Password**.

Changing your password **signs you out everywhere**. Every existing session for
the account is invalidated.

### Signing out

Select **Logout** in the sidebar. To end sessions on other devices too, use
**Sign out on all devices** in **Profile → Profile**.

---

## 4. Finding your way around

The left sidebar is the main navigation, and what it contains depends on your
role.

| Role              | Sidebar items                                                                     |
| ----------------- | --------------------------------------------------------------------------------- |
| **User**          | Dashboard · Alarms · Challenges · Recommendations · Reports · Profile              |
| **Wellness coach**| Dashboard (opens the coach workspace) · Profile                                    |
| **Administrator** | Admin Panel · Profile                                                              |

Other things on screen:

- **Notification bell** (top right, users and coaches) — unread count, recent
  notifications, *Mark all read*, and a test button.
- **Gear icon** (top right, users and coaches) — opens **Profile**.
- **Maintenance banner** — an amber bar reading *"Maintenance mode. Some
  features may be unavailable…"* appears when an administrator has put the
  platform into maintenance. Reading works; saving changes does not.
- **Practice Challenge** has no sidebar entry. Reach it from **Quick Actions**
  on the dashboard, or go to `/practice` directly.

If you open a page your role cannot use, you get an **Access Denied** screen
with a button back to your own home page. An unknown address shows a **404 Page
Not Found** screen inside the app shell.

---

## 5. Setting up your profile

**Profile** has three tabs for users and administrators. Wellness coaches see
only the **Profile** tab, because the sleep schedule, challenge preferences and
reminder settings are user-facing features.

### Tab: Profile

- **Personal Information** — full name, username and timezone. Select **Save
  Changes**.
- **Email Address** — change the address the platform writes to. Password
  resets, verification links and reminder emails all go here, so verify a new
  address after changing it.
- **Active Sessions** — **Sign out on all devices** revokes every token issued
  to your account, on every browser and device.
- **Danger Zone** — **Delete Account** permanently removes your account, alarms,
  preferences and habit data after a confirmation prompt.

### Tab: Sleep Schedule

Set your **Preferred Wake-up Time** and **Sleep Duration** (in hours, in steps
of half an hour). The card computes and displays your **recommended bedtime**
from those two values. Select **Update Schedule**.

These two values drive quite a lot: sleep-adherence scoring, the bedtime
reminder, the suggested bedtime in recommendations, and the on-time tolerance
used for wake consistency.

### Tab: Preferences

This tab contains four cards plus your habit score.

**Notification Preferences** — see [§13](#13-notifications).

**Preferred Challenge Types** — pick the puzzle family you want. Alarms set to
the `Random` challenge type use this preference when choosing what to serve.

**Default Difficulty** — Beginner, Easy, Medium, Hard or Expert. This is your
baseline; the platform adapts around it and individual alarms can override it.

**Productivity Goals** — free text, one goal per line or comma separated. Goals
appear in your productivity insights and feed the recommendation engine.

Select **Save All Preferences** to apply everything on the tab. Below it, the
**Habit Score** card shows your current score and its four components.

---

## 6. Creating and managing alarms

Open **Alarms**. With no alarms you see *"No Alarms Yet"* and a **Create
Alarm** button; otherwise your alarms appear as cards. **New Alarm** is at the
top right.

### The alarm form

| Field                      | Notes                                                                              |
| -------------------------- | ---------------------------------------------------------------------------------- |
| **Alarm Label**            | Optional name shown on the card                                                     |
| **Description**            | Optional note                                                                       |
| **Alarm Type**             | Daily (every day) · Weekday (Mon–Fri) · Weekend (Sat–Sun) · One-Time (specific date) · Smart (adaptive) |
| **Alarm Time**             | Hour, minute and AM/PM. Interpreted in your profile timezone                        |
| **One-Time Date**          | Shown only for One-Time alarms                                                       |
| **Days**                   | Mon–Sun chips. Days outside the type's own range are disabled and pruned automatically when you switch type. One-Time alarms have no day picker |
| **Challenge Type**         | 🎲 Random · 🔢 Math · 🧩 Logic · 🧠 Memory · 📝 Word · 🔗 Pattern · ❓ Riddle · 📚 Quiz |
| **Challenge Count**        | How many challenges you must solve to dismiss                                       |
| **Challenge Difficulty**   | Beginner → Expert; overrides your profile default for this alarm                    |
| **Snooze Limit**           | How many snoozes are allowed. **Set it to 0 for anti-snooze** — the snooze button is then refused outright |
| **Snooze Interval**        | Minutes added per snooze                                                             |
| **Volume**                 | 0–100 %                                                                              |
| **Vibrate**                | On or off                                                                            |

Choosing days **narrows** the alarm type: a Weekday alarm can be limited to
Monday and Friday, but it can never ring on Sunday. If you clear the selection
entirely, the alarm falls back to its type's full set rather than becoming
unschedulable.

A One-Time alarm remembers its date. Editing its time or switching it off and
back on does **not** silently move it to today.

### The alarm card

Each card shows the time, label, badges for alarm type / challenge type /
difficulty, the day strip, and a details row with the snooze policy (or
*Anti-snooze*), challenge type, one-time date, volume and vibrate state. The
switch on the right enables or disables the alarm.

Four buttons sit at the bottom of every card:

| Button                 | What it does                                                        |
| ---------------------- | ------------------------------------------------------------------- |
| **Test Ring**          | Starts the full wake cycle immediately, so you can rehearse it       |
| **Challenge history**  | Opens a paginated table of that alarm's attempts — when, type, difficulty, result, seconds and points |
| **Edit**               | Reopens the form                                                     |
| **Delete**             | Removes the alarm and its delivery history                           |

### When alarms ring

- With the app open in a browser tab, the alarm rings in the page. The tab
  checks every few seconds and rings within about two minutes of the trigger
  time.
- If push notifications are configured and you have granted permission, the
  server also sends a push at the trigger time, so the alarm reaches you with
  the tab closed. Opening the push takes you straight into the wake cycle.
- An alarm left unattended well past its time is rolled forward to its next
  occurrence — or switched off, if it was a one-time alarm — so a missed
  morning never parks a recurring alarm permanently in the past. A missed
  trigger that the open app observes is also recorded as an analytics event.

---

## 7. Waking up: the challenge cycle

When an alarm fires, a full-screen **WAKE UP!** panel takes over with
*"Solve the challenge to turn off the alarm."*

What you see:

- A **countdown timer** for the challenge, colour-coded green → amber → red as
  time runs out. Running out of time does not dismiss the alarm for you; it
  keeps ringing until you solve it, snooze it or give up.
- A **step indicator** when the alarm asks for more than one challenge —
  *"Challenge 2 of 3"*, a progress bar and per-step dots.
- An **escalation banner** — *"Anti-snooze active — difficulty raised N levels
  after snooze"* — after you have snoozed.
- The **challenge** itself: either multiple-choice buttons or a free-text answer
  with **Submit Answer**. A wrong answer shakes the panel and lets you try
  again.
- **Memory challenges** show the sequence first (*"Memorize this sequence…"*,
  *"Hides in Ns"*), then hide it and ask you to type it from memory. The display
  time is shorter at higher difficulties.
- Challenges generated by AI carry a small **AI** badge; everything else comes
  from the built-in generators.

Two buttons sit at the bottom:

| Button              | Behaviour                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------- |
| **Snooze (n/N used)** | Postpones the alarm by the configured interval and **raises the difficulty of the next challenge**. Replaced by an explanatory line once the limit is reached, or when anti-snooze is on |
| **Give up this wake** | Asks for confirmation, then ends the cycle as a failed wake and increases your failure streak |

Solving the final step confirms the wake. You get a toast with your
**wakefulness score**, the alarm is dismissed, and your dashboard refreshes.

**What each outcome records**

| Outcome                    | Effect                                                                  |
| -------------------------- | ----------------------------------------------------------------------- |
| Solved, no snoozes         | Verified wake · day streak continues · success streak +1                 |
| Solved after some snoozes  | Verified wake, with a smaller consistency penalty for the snoozes         |
| Snooze limit exhausted     | Larger consistency penalty                                               |
| Gave up                    | Failed wake · failure streak +1 · day streak resets                      |
| Never answered             | Counted as an abandoned or timed-out challenge in your completion rate    |

---

## 8. Practice mode

**Practice Challenge** (`/practice`, or **Quick Actions → Practice Challenge**)
lets you train on real puzzles at any time.

> Practice does **not** affect wake streaks, your habit score or the attempt log
> behind your analytics. It is purely for training.

1. Pick a **challenge type** (Random, Math, Logic, Memory, Word, Pattern,
   Riddle, Quiz) and a **difficulty** (Beginner → Expert). Both selectors are
   locked while a challenge is running.
2. Select **Start Practice**.
3. Answer within the timer — options are click-to-answer, otherwise type and
   select **Submit Answer**.
4. The result card shows correct/incorrect, the type, the difficulty and the
   points scored. Select **Next Challenge** to continue.

A session counter at the top tracks **Correct**, **Wrong**, **Accuracy** and
**Points** for the current visit.

---

## 9. Your dashboard

**Dashboard** is the home page for users. It opens with a greeting, a **New
Alarm** shortcut, and four headline figures: **Active Alarms**, **Habit Score**,
**Day Streak** (consecutive successful wake-up days) and **Success Rate**.

Below them is the **period toggle** — **Weekly** (last 7 days) or **Monthly**
(last 30 days) — plus a refresh button. Every panel underneath follows this
toggle.

| Panel                            | What it tells you                                                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------- |
| **Alarm History**                | Activity breakdown (dismissed / abandoned / snoozed), an activity trend chart, and a paginated timeline of recent events |
| **Wake-up Statistics**           | Wake counts by weekday and by hour, success and first-try rates, average time to dismiss, average snoozes and failed attempts, plus **Verification Accuracy** — how often the wake check reached the right verdict |
| **Habit Score**                  | Current score out of 100 with a trend badge, and the four weighted components                      |
| **Snooze & Sleep Schedule**      | The two habit sub-scores explained: snooze pattern (including snoozes per wake-up versus the previous period) and adherence to your target wake time |
| **Challenge Performance**        | Accuracy by challenge type, recent versus previous accuracy, and your **challenge completion rate** — the share of challenges served that you actually finished in time |
| **Productivity Insights**        | Morning routine and cognitive readiness scores with period-over-period deltas across readiness, routine, accuracy and wakefulness |
| **Sleep Patterns**               | Nightly duration, bedtime and wake-time regularity, sleep debt, and whether each night was recorded or estimated |
| **Behaviour ↔ productivity correlations** | Which behaviours track with which outcomes, with the sample size and whether the result is statistically significant |
| **Upcoming Alarms**              | Your next active alarms, with a link to the alarm manager                                          |
| **Quick Actions**                | Create Alarm · Practice Challenge · View Analytics · View Reports                                  |

### Logging your sleep

The **Sleep Patterns** panel has a **Log sleep now** button. Press it when you
go to bed, and again when you get up. The first press records the start of a
night, the second closes it. Recorded nights are used in preference to
estimated ones — an estimate can only ever be an upper bound on real sleep.

---

## 10. Challenge analytics

**Challenges** in the sidebar opens *Challenge Analytics*: accuracy,
personalization and attempt history for your wake-up challenges.

- **Summary cards** — Accuracy, Attempts, Avg Time, Points.
- **Completion Analysis** — plain-language insights plus your strengths and
  weaknesses, and challenge recommendations.
- **Accuracy by Challenge Type** and **By Difficulty** charts.
- **Personalization** — your baseline difficulty and where the engine is
  projecting it next.
- **Learning Patterns** — accuracy trend, mastery by challenge type, and
  **adaptation effectiveness**: whether difficulty changes actually moved you
  toward the target accuracy band. A falling accuracy after a difficulty rise is
  not a failure — the goal is fit, not a perfect score.
- **Engagement** — your engagement level and how it compares with 14 days ago.
- **Challenge History** — a paginated table of every attempt.

---

## 11. Recommendations

**Recommendations** is your coaching feed, generated from your wake
consistency, snooze frequency, challenge accuracy, sleep target, habit score and
saved goals.

- **Today's Plan** — the highest-priority actions for today and the schedule
  they assume (morning focus, suggested bedtime, wake goal).
- **What your data shows** — the observations behind the advice.
- **All Recommendations** — every card, filterable by chips: **All · Sleep ·
  Wake-up · Habit · Productivity · Challenge**, each with a count. Selecting
  Sleep, Wake-up or Productivity also loads a *"… focus"* block of insights
  scoped to that category.
- Each card carries a category badge, a priority badge (high / medium / low),
  the advice, and — where relevant — a link to the page where you can act on it.

### Rating advice

Every card has three buttons: **Helpful**, **Not helpful** and **Dismiss**. Your
rating replaces any previous rating for that card; it never stacks.

The **How relevant has this advice been?** panel at the bottom turns those
ratings into a measurement: your relevance rate (helpful out of the cards you
judged either way), how many you dismissed, the confidence the engine claimed,
and the gap between the two. You need to rate at least three cards as helpful or
not helpful before it unlocks.

> Rating does not change what the engine recommends or in what order. It exists
> so the quality of the advice can be measured honestly.

---

## 12. Reports

**Reports** produces *Lifestyle Reports* over habit, wake, challenge,
productivity and sleep analytics.

1. Choose a **date filter**: **7 days**, **30 days**, **90 days**, or **Custom
   range** with explicit start and end dates. A custom range must have both
   dates, must not be inverted, and may not exceed 365 days.
2. Choose a **report type**: Habit, Wake, Challenge, Productivity or Sleep.
3. The preview loads with a summary grid, insights and detail tables.
4. Export with the **PDF** or **Excel** buttons at the top right. The file
   downloads for the currently selected type and date range.

If there is no data in the window, the report still generates and explains what
to do to populate it — for example *"No wake events for this period. Dismiss an
alarm with a verified wake-up to generate wake analytics."*

---

## 13. Notifications

### The bell

The bell in the header shows an unread badge and, when opened, your ten most
recent notifications with a type icon and a relative timestamp. From the panel
you can **Mark all read**, mark a single item read, or send yourself a **test
notification**.

If your browser has not yet granted permission, a banner offers *"🔔 Enable push
notifications for reminders"*. Granting it registers your device for push, so
alarms and reminders arrive with the tab closed. If you block it, you can
re-enable it in your browser's site settings. When background push is
unavailable, reminders still work while the tab is open.

### What ICAP can send

| Notification         | When                                                            |
| -------------------- | ---------------------------------------------------------------- |
| **Bedtime reminder** | A configurable number of minutes before your computed bedtime     |
| **Wake reminder**    | Shortly before an alarm is due                                    |
| **Alarm trigger**    | At the alarm time, so a ring reaches you with no tab open          |
| **Habit reminder**   | When consistency or streaks decline                                |
| **Challenge reminder** | After a couple of days without a challenge                       |
| **Progress update**  | A weekly recap of wake-ups, challenges and streak milestones       |
| **Daily motivational** | One encouraging message a day, at a time you choose               |
| **Announcement**     | Sent by an administrator                                           |

### Preferences

**Profile → Preferences → Notification Preferences**. Changes are applied when
you save, and rescheduling happens immediately.

- **Enable notifications** is the master switch. With it off, every reminder
  option is disabled; turning it back on restores your previous settings.
- Per-type toggles for bedtime, wake, habit, challenge, progress and
  motivational messages. Bedtime and wake reminders take a lead time in minutes
  (5–120 and 5–60 respectively); the motivational message takes a local time.
- **Quiet hours** — a start and end time. Scheduled notifications wait until
  quiet hours end. **Clear quiet hours** removes them.
- **Notification sound** — Default, Gentle, Chime or Silent.
- **Notification frequency** —
  - **All** — bedtime, wake, habit, challenge, progress and motivational
  - **Essential** — bedtime and wake reminders only
  - **Minimal** — wake reminders only

  Choosing a narrower tier disables the types it excludes.

> Alarm triggers and administrator announcements are always delivered. They
> intentionally ignore quiet hours, the master switch and the per-type toggles,
> because an alarm that silently fails to ring is worse than an unwanted
> notification.

---

## 14. How your scores are calculated

### Habit score (0–100)

| Component                | Weight | Meaning                                                                                     |
| ------------------------ | -----: | ------------------------------------------------------------------------------------------- |
| **Wake-up consistency**  |   35 % | Your rolling wake-consistency score — how reliably your verified wake-ups land near your target |
| **Challenge completion** |   25 % | Your puzzle accuracy once you have attempts on record; before that, the share of wake events ended by a verified dismiss rather than by snoozing out |
| **Snooze reduction**     |   20 % | The share of your wake events that were snooze-free                                          |
| **Sleep adherence**      |   20 % | Your day streak measured against a 30-day target                                             |

### Other measures worth knowing

- **Day streak** — consecutive calendar days (in your timezone) with a
  successful wake-up. Snoozing does not break it; giving up or missing a day
  does. It advances at most once per day.
- **Success / failure streak** — consecutive verified or failed wake cycles.
  These drive difficulty adaptation.
- **Wakefulness score** — how alert you appeared during the cycle, from answer
  accuracy and response time.
- **Challenge accuracy** — correct answers out of answers submitted.
- **Challenge completion rate** — challenges *finished in time* out of
  challenges *served*. A challenge you never answered lowers this without
  touching accuracy, so the two can legitimately disagree.
- **Snooze reduction rate** — snoozes per wake-up this period compared with the
  period before. Normalising by wake-ups is deliberate: simply having fewer
  alarms is not an improvement.

### Adaptive difficulty

After a run of consecutive successes the platform raises your difficulty by one
level; after a run of failures it lowers it. Snoozing escalates difficulty
within the current wake cycle only. The target is an accuracy band that is
challenging but achievable — not 100 %.

---

## 15. For wellness coaches

Coaches sign in exactly like users and land on the **Wellness Coach Dashboard**.
Your access is read-only, and you can only see clients an administrator has
assigned to you. Removing an assignment revokes your access immediately.

### The workspace

- **Period selector** — **7 Days**, **30 Days** or **90 Days** (default 30). It
  drives every panel.
- **Overview cards** — Assigned Clients, Average Habit Score, Needs Attention
  and Engagement for the selected window.
- **My Clients** — your roster, with:
  - a **search** box (name, username or email),
  - a **sort** menu (name, habit score up or down, wake consistency, day streak,
    verified wakes, challenge accuracy, least recently active, recently
    assigned),
  - **status chips**: **All**, **Needs Attention** (a habit, consistency or
    inactivity alert), **On Track**, **Inactive** (no wake or challenge activity
    in the window),
  - pagination, and a habit / wake / streak / wakes summary per row.

Selecting a client opens their detail panels:

| Panel                     | Contents                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------ |
| **Profile Information**   | Name, email, timezone (with their local time), status, last verified wake, current goal |
| **Core Metrics**          | Habit score, wake consistency, sleep adherence, day streak                            |
| **Behaviour Insights**    | Snooze pattern, wake consistency, sleep adherence and snooze reduction, with a weekday snooze chart and weekly/monthly trends |
| **Habit Insights**        | The score, its four weighted components, the change over the window, and a trend chart |
| **Sleep Trends**          | Sleep adherence, wake consistency, schedule adherence, measured sleep, plus daily charts |
| **Challenge Performance** | Attempts, accuracy, average response time, points, completion rate and recent attempts |
| **Recommendations**       | The coaching feed generated for that client                                           |
| **Wellness Analytics**    | A five-metric summary and a habit-component trend chart                               |

Every panel loads independently: if one fails it shows its own error with a
**Try again** button while the rest of the page keeps working. Times are shown
in the **client's** timezone, not yours.

### Notes for coaches

- With no assignments you see *"No clients assigned yet"*. Ask an administrator
  to assign clients to you.
- Coaches have their own home page and are redirected away from the personal
  user dashboard. Your **Profile** page shows only the Profile tab.
- If a client is unassigned while you are looking at them, their panels report
  that the client is no longer on your roster.

---

## 16. For administrators

Administrators land on the **Admin Dashboard** — *"Manage users and monitor
platform activity"*.

### Date controls

Presets of **7 days**, **30 days**, **90 days** or a **Custom range** (both
dates required) apply to every analytics panel. There is a manual refresh and an
opt-in **auto-refresh** every 60 seconds.

### Panels

| Section                        | What it covers                                                                     |
| ------------------------------ | ----------------------------------------------------------------------------------- |
| **Headline cards**             | Total users, total alarms, admin users, active users                                |
| **User Analytics**             | New users, growth rate, engaged and verified users, wake events and success, challenge volume and accuracy, plus a registration trend |
| **Active Users**               | Role mix and top performers                                                          |
| **Alarm Statistics**           | Active/inactive alarms, period wakes, success rate, snoozes, and the alarm and challenge type distributions |
| **Habit Score Overview**       | Platform average and maximum, users above 70 and below 40, and component averages    |
| **Recommendation Statistics**  | Profiles, goals set, average streak and consistency, preferred versus adapted difficulty |
| **Platform Analytics**         | Ingested analytics events, unique users, daily average and ingestion trend           |
| **System Health**              | Runtime status and version, data-integrity issues, missing profiles, orphaned alarms, Redis state, database rows, and last-24h activity |
| **API Performance**            | Measured p50/p95/p99, 5xx rate, the slowest routes against the 400 ms target, and challenge-generation latency against its own budget |
| **Observability**              | Firing threshold alerts, the thresholds themselves, and the active logging configuration |

> API performance and alert counters are **per worker process** and reset when
> the process restarts.

### Managing users

**User Management** offers search (username, email, full name), role and status
filters, page size, and a sortable table. Row actions:

- **Edit** — full name, email and role. You cannot change your own role.
- **Deactivate / Activate** — a deactivated account cannot sign in.
- **Delete** — removes the account.

All three destructive actions ask for confirmation first.

### Coach assignments

**Coach Assignments** is what gives a wellness coach access to a client:

1. Pick a **Coach** and a **Client**, optionally add a **note**, and select
   **Assign**.
2. The table lists coach, client, notes, status, assignment date and a remove
   action.
3. Removing an assignment revokes the coach's access immediately. The row is
   archived rather than erased — tick **Show removed** to audit past
   assignments.

### Platform settings

**Notification Settings** controls the whole platform:

- **Email Notifications** and **Push Notifications** kill-switches (each is
  disabled with an explanation when SMTP or FCM is not configured).
- **Maintenance Mode** plus a maintenance message. While it is on, non-admin
  users can still read, but any change they attempt is refused and the message
  is shown to them in a banner.
- **Alert thresholds** for habit score, wake consistency and snooze reduction —
  these decide which users a coach sees as *needs attention*.

**Broadcast announcement** sends a title and message to every active user, with
an option to also send it as a push. Announcements bypass user notification
preferences, so use them sparingly.

### System reports

Generate **User**, **Alarm**, **Habit** or **Platform** reports for the selected
period and export them as **PDF** or **Excel**.

---

## 17. Troubleshooting

**My alarm did not ring.**
Check that the alarm is switched on and that its day and time are correct in
your profile timezone. In-page ringing needs the app open in a tab; for rings
with the tab closed, push notifications must be configured by your administrator
and permitted in your browser (use the bell's *Enable push notifications*
banner). The bell's test button confirms delivery end to end.

**The snooze button is missing or refuses.**
The alarm has `Snooze Limit = 0` (anti-snooze), or you have used all your
snoozes. Solve the challenge to dismiss.

**The challenge is too hard or too easy.**
Set a **Default Difficulty** in Profile → Preferences, or override it on the
individual alarm. The platform then adapts from there. Note that each snooze
raises the difficulty for the rest of that wake cycle.

**"Not enough data" everywhere.**
Most analytics need a handful of verified wake-ups or challenge attempts before
they will report anything; correlations and relevance have explicit minimum
sample sizes and say what is still missing.

**My habit score dropped after a good morning.**
Habit score is a weighted composite over a window, not a per-day figure. Sleep
adherence and snooze reduction can move it even on a day you woke cleanly.

**I did not get the reset or verification email.**
Check spam first. Requests are limited to three per 15 minutes. If your
deployment has no mail server configured, links are written to the server log
instead — ask your administrator.

**I am locked out after failed sign-ins.**
Five failed attempts lock the account for 15 minutes. The message tells you how
long is left. A successful sign-in clears the counter.

**A page shows an error box with "Try again".**
Only that panel failed. Use its retry button; the rest of the page keeps
working. A whole-page failure offers a reload.

**"Maintenance mode" banner.**
An administrator is working on the platform. You can read, but saving is
blocked until it is switched off.

---

## 18. Your data

ICAP records what it needs to score your habits:

- alarms and their configuration,
- wake events, snooze events and their timing,
- challenges served and challenge attempts, with answers and response times,
- sleep boundaries you log yourself, plus activity-based estimates,
- profile settings, goals and notification preferences,
- product analytics events raised by the app.

Your wellness coach can see analytics for you **only** while an administrator
has an active assignment linking you. Administrators can see account details and
platform-wide aggregates.

To remove everything, use **Profile → Profile → Danger Zone → Delete Account**.
Deletion is permanent.
