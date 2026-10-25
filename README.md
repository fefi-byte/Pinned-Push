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
- **Your own buttons.** A confirm button plus up to two more. The button
  labels are the event types of the event entity, so the automation editor
  shows your labels.
- **Comes back when swiped away** – only on the phone that dismissed it.
- **Cleared everywhere** as soon as one person answers.
- **Optional expiry.** After the configured time the notification is removed
  and an `expired` event fires.
- **Restart-safe.** State is stored; answers, re-sends and expiry survive
  restarts and reloads.
- **Repairs instead of silent failures.** If a person has no phone that can be
  reached, a repair issue tells you who.
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

Requires Home Assistant 2026.3 or newer and the Companion App on Android.

## Setup

Open the Pinned Push entry and choose **Add notification**:

| Field | Meaning |
|---|---|
| Name | Names the device and its entities, e.g. *Early shift* → `event.early_shift` |
| People | Who receives it. Their phones come from the person's tracked devices |
| Additional phones | Companion App devices that receive it in addition |
| Title / Message | Default text; both can be overridden when sending |
| Confirm button | Label of the first button, e.g. *Yes* |
| Additional buttons | Up to two more, e.g. *No*, *Later* |
| Icon | Notification icon (`mdi:` icons) |
| Show again when swiped away | Re-show on the phone that dismissed it |
| Expires after | Minutes until it is removed; 0 = never |

Each notification gets:

- `event.<name>` – fires on every answer. Event types are the button labels
  plus `expired`. Attributes: `person`, `person_name`, `button_index`,
  `confirmed`, `at`.
- `sensor.<name>_status` – `idle`, `open`, `answered` or `expired`, with the
  last answer, who answered, recipients and expiry time as attributes.

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
recipients for this send). Sending again replaces the notification on the
phones. With `response_variable` the action returns where it was sent.

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
  `pinned_push_<id>`; buttons use the action ids `PINNED_PUSH|<id>|<n>`.
- Answers come from `mobile_app_notification_action`; who answered is taken
  from the Home Assistant user behind the Companion App.
- A swipe arrives as `mobile_app_notification_cleared`; the notification is
  re-sent after two seconds to that phone only (at most 50 times).

## Limitations

- Android only. iOS ignores `persistent`/`sticky`, so notifications can be
  swiped away for good there.
- Android shows at most three buttons.
- The person who answered is identified by the Home Assistant user logged in
  to the Companion App. A shared tablet logged in as one user reports that
  user's person.

## License

MIT
