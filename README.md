# Pinned Push

[![Validate](https://github.com/fefi-byte/pinned-push/actions/workflows/validate.yml/badge.svg)](https://github.com/fefi-byte/pinned-push/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Pinned, actionable push notifications for Home Assistant – set up in the UI,
answered with buttons, and still tracked after a restart.

Pinned Push sends a notification through the
[Companion App](https://companion.home-assistant.io/) that stays pinned on the
phones of the people you choose. If someone swipes it away, it comes back.
When someone presses a button, it disappears from every phone and your
automations get the answer – including who answered.

## Why

Actionable notifications in plain Home Assistant usually mean a script that
sends the notification and then waits with `wait_for_trigger`. That works
until Home Assistant restarts: the waiting script is gone, the notification is
still on the phone, and pressing the button does nothing.

Pinned Push keeps every open notification in storage and listens for answers
all the time. After a restart, answers still arrive, dismissed notifications
still come back and expiry timers keep running.

## Features

- **No YAML.** Each notification is configured in the UI and becomes a device
  with two entities.
- **People, not services.** Pick `person` entities; the phones are taken from
  each person's tracked Companion App devices. Additional phones can be added
  directly.
- **Your own buttons.** Up to three, each answering and closing, answering
  but staying, or opening a page. The labels are the event types of the event
  entity, so the automation editor shows your labels.
- **Looks the way you want.** Color, camera snapshot or picture, tap target,
  lock screen visibility, countdown and grouping.
- **Notification channels managed in Home Assistant**, including importance,
  vibration and LED – and recreated on the phones when you change them.
- **Comes back when swiped away** – only on the phone that dismissed it.
- **Cleared everywhere** as soon as one person answers.
- **Optional expiry.** After the configured time the notification is removed
  and an `expired` event fires.
- **Restart-safe.** State is stored; answers, re-sends and expiry survive
  restarts and reloads.
- **Repairs instead of silent failures.** A repair issue tells you when a
  person has no reachable phone, when you renamed a button that an automation
  still uses, or when a phone keeps removing the notification on its own.
- **Delivery and sound.** Immediate high-priority delivery (helps with phones
  that delay notifications to save battery), your own notification channel,
  and optionally audible with Do Not Disturb.
- **Late presses do not count.** Every send has a number; pressing a button on
  an outdated, replaced or expired notification is ignored.
- English and German UI.

## Installation

### HACS

1. HACS → three-dot menu → **Custom repositories** → add
   `https://github.com/fefi-byte/pinned-push` with type **Integration**.
2. Install **Pinned Push** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Pinned Push**.

### Manual

Copy `custom_components/pinned_push` into your `config/custom_components`
folder (or unpack `pinned_push.zip` from a release there) and restart.

Requires Home Assistant 2025.6 or newer and the Companion App on Android.
The *Event received* trigger used below needs Home Assistant 2026.7; on older
versions use a state trigger with a condition (see below).

## Setup

### Notifications

Open the Pinned Push entry and choose **Add notification**:

| Field | Meaning |
|---|---|
| Name | Names the device and its entities, e.g. *Early shift* → `event.early_shift` |
| People | Who receives it. Their phones come from the person's tracked devices |
| Additional phones | Companion App devices that receive it in addition |
| Title / Message | Default text; both can be overridden when sending |
| Icon | Status bar icon (`mdi:` icons) |
| Show again when swiped away | Re-show on the phone that dismissed it |
| Expires after | Minutes until it is removed; 0 = never |

**Buttons 1–3** – each with a label and what it does:

| Type | Effect |
|---|---|
| Answer and close | Reported as an answer, removed from every phone |
| Answer, keep showing | Reported as an answer, the notification stays (e.g. *Remind me later*) |
| Close, show again after the minutes | Reported as an answer, removed from every phone, shown again after the button's minutes (snooze; survives restarts) |
| Open page (no answer) | Opens a dashboard path (`/lovelace/cameras`), a URL, `entityId:light.kitchen`, `app://package` or `settings://notification_history` |

Button 1 is the confirmation: it answers and closes, or answers and stays. Android shows at
most three buttons.

**Appearance** (collapsed): accent color, a camera snapshot or picture
(`/media/local/…`, `/local/…`, URL), the page opened when the notification is
tapped, lock screen visibility (show / phone setting / hide), a countdown to
the expiry time, and a group to stack notifications.

**Delivery and sound** (collapsed): *Deliver immediately* (high priority,
arrives at once even when the phone is dozing; on by default) and the
notification channel: *Default*, *Alarm* (rings even on silent) or one of
your own channels.

### Notification channels

Choose **Add notification channel** on the Pinned Push entry to create an
Android channel with its own importance, vibration pattern
(`0, 500, 250, 500`) and LED color, then pick it in any notification.

Android fixes these settings when a channel is first created on a phone. When
you change or delete a channel, Pinned Push removes it from every phone that
has it; the next notification creates it again with the new settings. Sound
settings changed on the phone for that channel are reset by this.

### Entities

Each notification gets:

- `event.<name>` – fires on every answer. Event types are the labels of the
  answer buttons plus `expired`. Attributes: `person`, `person_name`,
  `device`, `button_index`, `confirmed`, `closes`, `send_id`, `at`.
- `sensor.<name>_status` – `idle`, `open`, `snoozed`, `answered` or `expired`, with the
  last answer, who answered and on which phone, recipients, send number,
  number of re-sends and expiry time as attributes.

## Usage

### Send

Action **Pinned Push: Send** (`pinned_push.send`):

```yaml
action: pinned_push.send
data:
  entity_id: event.early_shift
  message: "Shift starts at 06:00. Make coffee at 05:00?"
```

Optional fields: `title`, `message`, `persons` (replaces the configured
recipients for this send), `image` (e.g. `/api/camera_proxy/camera.door`) and
`click_action`. Sending again replaces the notification on the
phones; a button pressed on the old version no longer counts. With
`response_variable` the action returns where it was sent and the `send_id`.

### React to the answer

In the automation editor add the trigger **Event → Event received**, pick the
notification's event entity and choose the button from the list – the list
shows your button labels:

```yaml
triggers:
  - trigger: event.received
    target:
      entity_id: event.early_shift
    options:
      event_type: ["Yes"]
```

`trigger.to_state.attributes.person` tells you who answered. Use
`event_type: ["expired"]` to react when nobody answered in time.

Before Home Assistant 2026.7:

```yaml
triggers:
  - trigger: state
    entity_id: event.early_shift
conditions:
  - condition: state
    entity_id: event.early_shift
    attribute: event_type
    state: "Yes"
```

If you rename a button later, a repair issue lists the automations that still
use the old label and disappears once they are updated.

Every answer is also fired on the event bus as `pinned_push_answer`
(`notification`, `event_type`, `person`, `person_name`, `button_index`,
`confirmed`).

### Remove without an answer

```yaml
action: pinned_push.dismiss
data:
  entity_id: event.early_shift
```

## How it works

- Notifications are sent with `persistent`, `sticky` and a tag
  `pinned_push_<id>`; buttons use the action ids
  `PINNED_PUSH|<id>|<send>|<n>`.
- Answers come from `mobile_app_notification_action`. The phone is identified
  by its webhook; the person is the one tracking that phone, or else the person
  of the Home Assistant user logged in to the app.
- A swipe arrives as `mobile_app_notification_cleared`; the notification is
  re-sent after two seconds to that phone only, at most 50 times.
- Deleting a notification that is still showing removes it from the phones.

## Limitations

- Android only. iOS ignores `persistent`/`sticky`, so notifications can be
  swiped away for good there.
- Android shows at most three buttons.
- A button pressed while Home Assistant is restarting may be lost; the
  Companion App does not resend it.
- On phones with aggressive battery saving (e.g. Xiaomi), exclude the Companion
  App from battery optimization, otherwise dismissals and presses can arrive
  late or not at all.
- A phone that no person tracks is attributed to the person of the logged-in
  Home Assistant user.

## License

MIT
