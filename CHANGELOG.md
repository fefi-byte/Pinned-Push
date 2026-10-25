# Changelog

## 0.5.0

- Buttons are added one by one: the main form holds the mandatory button 1
  (confirmation, answers and closes or answers and stays); a menu afterwards
  adds, changes or removes up to two more buttons.
- German UI says "Button" instead of "Knopf".

## 0.4.0

- New button type *Close, show again after the minutes* (snooze). The minutes
  are set per button (1–1440). The notification disappears from every phone
  and comes back after that time with the same text and buttons; the press is
  reported like an answer. The snooze is stored and survives restarts; if it
  ran out while Home Assistant was down, the notification comes back at start.
  Expiry still applies while snoozed.
- New status `snoozed` with the attribute `snoozed_until`.

## 0.3.0

- Buttons 1–3 with a type each: answer and close, answer and keep showing, or
  open a page/URL (no answer). Notifications from 0.1/0.2 are shown in the new
  layout and saved in it on the next change.
- Appearance: accent color, camera snapshot or picture, tap target, lock
  screen visibility, countdown until expiry, group.
- Notification channels as their own entries (importance, vibration, LED);
  changed or deleted channels are removed from the phones so Android creates
  them again with the new settings.
- The send action accepts `image` and `click_action`.

## 0.2.0

- Repair issue when a renamed button is still used by an automation; it
  disappears once no automation uses the old label.
- Deleting a notification that is still showing removes it from the phones.
- Delivery options: immediate high-priority delivery (default on), audible with
  Do Not Disturb, notification channel and importance.
- Repair issue when a phone keeps removing a notification on its own.
- Every send has a number; presses on outdated notifications are ignored.
  Notifications sent by 0.1 can still be answered.
- The person who answered is taken from the phone (who tracks it) before the
  logged-in user; the answer also names the phone.
- Tested from Home Assistant 2025.6 on.

## 0.1.0

- First release.
