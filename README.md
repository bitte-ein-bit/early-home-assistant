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
| `sensor.<account>_current_activity` | sensor | Name of the activity being tracked, `unknown` while idle. Attributes: `activity_id`, `color`, `folder_id`, `started_at`, `note`, `tags`, `mentions` |
| `sensor.<account>_tracking_started` | sensor (timestamp) | When the running tracking started |
| `sensor.<account>_current_duration` | sensor (duration, min) | Minutes since the running tracking started |
| `sensor.<account>_tracked_today` | sensor (duration, h) | Tracked hours since local midnight, including the running tracking |
| `sensor.<account>_tracked_this_week` | sensor (duration, h) | Same for the current week (Monday–Sunday) |
| `sensor.<account>_tracked_this_month` | sensor (duration, h) | Same for the current calendar month |
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

## How it works

- The running tracking is polled every 30 seconds (`GET /api/v4/tracking`).
- Completed time entries are fetched every 5 minutes, and immediately whenever a
  tracking starts or stops, so the daily total is right the moment you hit stop.
- The daily, weekly and monthly totals add the running tracking's elapsed time on
  top of the completed entries, clipped at the window boundary — a tracking that
  crosses midnight only counts its part of each day.
- EARLY returns timestamps without a zone suffix; they are treated as UTC and
  bucketed in your Home Assistant time zone.

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
- Only your own trackings are covered. Folders, team members and leaves are not
  exposed.
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
