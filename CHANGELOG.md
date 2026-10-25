# Changelog

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
