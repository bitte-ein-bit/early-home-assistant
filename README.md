# EARLY (Timeular) for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)
[![CI](https://github.com/bitte-ein-bit/early-home-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/bitte-ein-bit/early-home-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Brings your [EARLY](https://early.app) (formerly Timeular) time tracking into Home
Assistant: what you are tracking right now, how long you have been at it, how much
you tracked today — and buttons and services to start, stop or discard a tracking.

Sensors for the current activity, its duration and the hours tracked per day, week
and month; a select plus buttons and services to start and stop tracking.

The activity list is read from the EARLY API and refreshed every 15 minutes, so
activities you add, rename or archive in the app show up without a restart and
without anything being hardcoded.

## Entities

| Entity | Type | Description |
| --- | --- | --- |
| `sensor.<account>_current_activity` | sensor | Name of the activity being tracked, `unknown` while idle. Attributes: `activity_id`, `color`, `rgb_color`, `folder_id`, `started_at`, `note`, `tags`, `mentions` |
| `sensor.<account>_tracking_started` | sensor (timestamp) | When the running tracking started |
| `sensor.<account>_current_duration` | sensor (duration, min) | Minutes since the running tracking started |
| `sensor.<account>_tracked_today` | sensor (duration, h) | Tracked hours since local midnight, including the running tracking |
| `sensor.<account>_tracked_this_week` | sensor (duration, h) | Same for the current week (Monday–Sunday) |
| `sensor.<account>_tracked_this_month` | sensor (duration, h) | Same for the current calendar month |
| `sensor.<account>_balance_today` | sensor (duration, h) | Tracked minus target hours. Negative means hours still owed, positive means overtime. Attributes: `tracked_hours`, `target_hours`, `remaining_hours` |
| `sensor.<account>_balance_this_week` | sensor (duration, h) | Same from Monday up to and including today |
| `sensor.<account>_balance_this_month` | sensor (duration, h) | Same from the 1st up to and including today |
| `sensor.<account>_tracked_last_28_days` | sensor (duration, h) | Rolling window ending with today; length configurable, and it appears in the name |
| `sensor.<account>_balance_last_28_days` | sensor (duration, h) | Balance over that same rolling window |
| `binary_sensor.<account>_tracking` | binary sensor | `on` while any tracking runs |
| `select.<account>_activity` | select | Which activity the start button will track |
| `button.<account>_start_tracking` | button | Starts the selected activity |
| `button.<account>_stop_tracking` | button | Stops the running tracking, keeping the time entry |
| `button.<account>_discard_tracking` | button | Discards the running tracking (disabled by default) |

## Services

```yaml
action: early.start_tracking
data:
  activity: Deep Work   # name (case-insensitive) or activity id
  note: Reviewing the quarterly report   # optional
```

```yaml
action: early.stop_tracking
```

```yaml
action: early.cancel_tracking
```

All three take an optional `config_entry_id`, which is only needed if you have more
than one EARLY account set up.

`start_tracking` resolves the activity at call time, so an automation written
against an activity name keeps working when the activity is edited in the app —
only renaming it breaks the reference, and the error message then lists the
activities EARLY actually knows.

## Installation

### HACS

1. HACS → three-dot menu → *Custom repositories*
2. Add `https://github.com/bitte-ein-bit/early-home-assistant`, category *Integration*
3. Install **EARLY (Timeular)** and restart Home Assistant

### Manual

Copy `custom_components/early` into your Home Assistant `config/custom_components`
directory and restart.

## Configuration

1. Create an API key and secret at <https://product.early.app> under *Settings → API*
2. Home Assistant → *Settings → Devices & services → Add integration → EARLY*
3. Paste key and secret

Credentials are stored in the config entry. If EARLY ever rejects them, Home
Assistant starts a reauth flow instead of silently going unavailable.

### Working time target

EARLY lets you set your working hours in its own UI, but **the public API does
not expose that setting** — `/me` and `/users` return only id, name and email,
and nothing in the v4 surface carries a target, capacity or weekly schedule. So
the target lives in Home Assistant instead:

*Settings → Devices & services → EARLY → Configure*

You get one figure per weekday, defaulting to 8/8/8/8/8/0/0. Per weekday rather
than a single daily number, because a flat 8 hours applied to every calendar day
would put every weekend permanently in the red — and it lets you express a four
day week or a short Friday. Changing it reloads the entry, so the balance
sensors follow immediately.

#### How the balance is counted

`balance = tracked − target`, over the same window as the matching
`tracked_*` sensor, and **today always counts with its full target**:

| Situation | `balance_today` |
| --- | --- |
| Monday 09:00, nothing tracked yet | `-8` |
| Monday 13:00, 4 h tracked | `-4` |
| Monday 17:30, 8 h tracked | `0` — done for the day |
| Monday 19:00, 9.5 h tracked | `+1.5` — overtime |
| Sunday, 2 h tracked, target 0 | `+2` |

That makes the number answer "how much until I'm even", and reaching `0` is
exactly the goal of no deficit and no overtime. `remaining_hours` in the
attributes is the same thing clamped at zero, if you only want the countdown.

The weekly and monthly balances work the same way over their window, so they
average out a short day against a long one. A week that ends at `0` on Friday
evening is a week on target.

The **rolling window** pair is the one to watch for staying on target on
average: unlike the calendar month it does not reset on the 1st, so a deficit or
a pile of overtime stays visible until it is actually worked off.

Its length is set under *Configure* and defaults to **28 days**. Four weeks is
deliberate: a whole number of weeks always contains the same weekdays, so the
target stays put as the window slides — 20 weekdays, exactly four times a 40
hour week, whichever day it happens to start on. A 30 day window would hold 21
or 22 weekdays depending on where it starts, and its target would step by eight
hours as it moves, which is noise you would have to read past.

Set it to whatever suits you; the length shows up in the sensor name, so a 14
day window reads as `Tracked last 14 days`.

#### Time off

Track it as an activity. Give holidays and sick days an activity of their own in
EARLY and book the hours against it — the balance then works out on its own,
because `tracked_*` counts every activity, so those hours cancel that day's
target:

| Day | Tracked | Target | `balance_today` |
| --- | --- | --- | --- |
| Day off, 8 h booked as *Holiday* | 8 | 8 | `0` |
| Half sick day, 4 h *Sick* + 4 h work | 8 | 8 | `0` |
| Whole week off, 40 h booked | 40 | 40 | `0` |

The one case that does show a deficit is a day off with **nothing** tracked at
all. EARLY's own leave feature is a separate thing, is not part of every plan,
and this integration does not read the leaves API — tracking time off as an
activity covers the same ground without it.

Note that `tracked_*` then means "tracked", not "worked": a week off reads as 40
tracked hours. If you want the two separated, open an issue.

## How it works

- The running tracking (`GET /api/v4/tracking`) is the only thing polled often,
  and its cadence adapts: **every 30 seconds** normally, dropping to **every 5
  minutes** once nothing has changed for two hours, and snapping back the moment
  a tracking starts, stops or switches activity.

  The back-off costs nothing for anything you do from Home Assistant — buttons
  and services refresh on the spot regardless — so it only delays noticing a
  change made in the EARLY app itself, and only after a quiet stretch. On a day
  with four transitions that is about 7 hours at the fast cadence and 17 at the
  slow one: roughly 1000 requests instead of 2900.
- Completed time entries (`GET /api/v4/time-entries/{from}/{to}`) are the heavy
  call: one request returns every entry in the window. It is therefore
  event driven rather than polled — it runs on startup, whenever a tracking
  starts, stops or switches activity, at midnight when the buckets move, and
  otherwise at most once an hour as a safety net for edits made elsewhere. That
  is around 30 requests a day instead of the 288 a five minute poll would cost.
- All told the integration makes roughly **1200 requests a day**, down from 3300
  before the two changes above. `GET /api/v4/activities` accounts for 96 of them,
  every 15 minutes, so the select follows edits made in the app.
- One time entry request feeds all four windows at once: it spans the earliest
  window start, and each entry is then counted against every window it falls in.
  Shortening the rolling window therefore also shortens what has to be fetched.
- The daily, weekly and monthly totals add the running tracking's elapsed time on
  top of the completed entries, clipped at the window boundary — a tracking that
  crosses midnight only counts its part of each day.
- EARLY returns timestamps without a zone suffix; they are treated as UTC and
  bucketed in your Home Assistant time zone.
- While nothing is being tracked, EARLY answers `GET /tracking` with a 404 rather
  than an empty body. That is read as "idle", not as an error.

## Example automation

Turn a desk lamp on while you are tracking focused work:

```yaml
automation:
  - alias: Focus light
    triggers:
      - trigger: state
        entity_id: sensor.early_current_activity
        to: Deep Work
    actions:
      - action: light.turn_on
        target:
          entity_id: light.desk
```

Tint a WLED strip in the colour of the activity you are tracking, and turn it
off when you stop. The activity colour is published both as the raw `color` hex
string and, ready for `light.turn_on`, as an `rgb_color` triplet:

```yaml
automation:
  - alias: Desk strip follows the tracked activity
    triggers:
      - trigger: state
        entity_id: sensor.early_current_activity
    actions:
      - choose:
          - conditions:
              - condition: template
                value_template: >-
                  {{ state_attr('sensor.early_current_activity', 'rgb_color')
                     is not none }}
            sequence:
              - action: light.turn_on
                target:
                  entity_id: light.wled_desk
                data:
                  rgb_color: >-
                    {{ state_attr('sensor.early_current_activity', 'rgb_color') }}
        default:
          - action: light.turn_off
            target:
              entity_id: light.wled_desk
```

`rgb_color` is `None` while nothing is tracked and whenever the activity has no
usable colour, which is what the `choose` above keys off.

Stop tracking when you leave home:

```yaml
automation:
  - alias: Stop tracking when leaving
    triggers:
      - trigger: state
        entity_id: person.me
        from: home
    conditions:
      - condition: state
        entity_id: binary_sensor.early_tracking
        state: "on"
    actions:
      - action: early.stop_tracking
```

## Notes and limits

- EARLY refuses time entries shorter than one minute, so stopping immediately
  after starting fails.
- `cancel_tracking` throws the running tracking away. The button for it is
  disabled by default; enable it in the entity settings if you want it.
- Only your own trackings are covered. Folders, team members and EARLY's own
  leave feature are not exposed; see [Time off](#time-off) for how that is
  handled instead.
- Polling is used rather than EARLY's webhooks, which would require a publicly
  reachable HTTPS URL.

## Branding

`custom_components/early/brand/` holds a generic stopwatch icon so HACS has brand
assets to show. It is a placeholder, not EARLY's logo. Replacing it with the
official artwork — or getting the integration listed in
[home-assistant/brands](https://github.com/home-assistant/brands) — needs EARLY's
own assets and permission to use them.

## License

MIT
