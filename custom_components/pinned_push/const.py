"""Constants for Pinned Push."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pinned_push"

SUBENTRY_TYPE_NOTIFICATION: Final = "notification"

CONF_PERSONS: Final = "persons"
CONF_DEVICES: Final = "devices"
CONF_TITLE: Final = "title"
CONF_MESSAGE: Final = "message"
CONF_CONFIRM_TEXT: Final = "confirm_text"
CONF_BUTTONS: Final = "buttons"
CONF_ICON: Final = "icon"
CONF_RESEND: Final = "resend_on_dismiss"
CONF_EXPIRE: Final = "expire_minutes"

# Delivery section
CONF_DELIVERY: Final = "delivery"
CONF_URGENT: Final = "urgent"
CONF_ALARM_STREAM: Final = "alarm_stream"
CONF_CHANNEL: Final = "channel"
CONF_IMPORTANCE: Final = "importance"
IMPORTANCES: Final = ["min", "low", "default", "high", "max"]
DEFAULT_IMPORTANCE: Final = "default"
# 0.2 stored alarm_stream/channel/importance per notification; 0.3 uses
# channel_ref. The old keys are still read for notifications not yet changed.
DELIVERY_KEYS: Final = ("urgent", "channel_ref")

# Buttons (since 0.3): three slots, stored as a list of
# {"label", "type", "target"}. confirm_text/buttons of 0.1/0.2 are migrated
# on read.
CONF_BUTTON_LIST: Final = "button_list"
BUTTON_SLOTS: Final = ("button_1", "button_2", "button_3")
CONF_LABEL: Final = "label"
CONF_TYPE: Final = "type"
CONF_TARGET: Final = "target"
BUTTON_ANSWER: Final = "answer"
BUTTON_KEEP_OPEN: Final = "answer_keep_open"
BUTTON_OPEN: Final = "open"
BUTTON_SNOOZE: Final = "snooze"
BUTTON_TYPES: Final = [BUTTON_ANSWER, BUTTON_KEEP_OPEN, BUTTON_SNOOZE, BUTTON_OPEN]
ANSWER_TYPES: Final = (BUTTON_ANSWER, BUTTON_KEEP_OPEN, BUTTON_SNOOZE)
CONF_MINUTES: Final = "minutes"
DEFAULT_SNOOZE_MINUTES: Final = 10
MAX_SNOOZE_MINUTES: Final = 1440

# Appearance section
CONF_APPEARANCE: Final = "appearance"
CONF_COLOR: Final = "color"
CONF_IMAGE: Final = "image"
CONF_CAMERA: Final = "camera"
CONF_CLICK_ACTION: Final = "click_action"
CONF_VISIBILITY: Final = "visibility"
CONF_COUNTDOWN: Final = "countdown"
CONF_GROUP: Final = "group"
VISIBILITIES: Final = ["public", "private", "secret"]
DEFAULT_VISIBILITY: Final = "private"
APPEARANCE_KEYS: Final = (
    CONF_COLOR,
    CONF_IMAGE,
    CONF_CAMERA,
    CONF_CLICK_ACTION,
    CONF_VISIBILITY,
    CONF_COUNTDOWN,
    CONF_GROUP,
)

# Channels (since 0.3): own subentry type, chosen per notification
SUBENTRY_TYPE_CHANNEL: Final = "channel"
CONF_CHANNEL_REF: Final = "channel_ref"
CONF_CHANNEL_NAME: Final = "channel_name"
CONF_VIBRATION: Final = "vibration"
CONF_LED_COLOR: Final = "led_color"
CHANNEL_DEFAULT: Final = "default"
CHANNEL_ALARM: Final = "alarm_stream"

DEFAULT_CONFIRM_TEXT: Final = "OK"
DEFAULT_ICON: Final = "mdi:pin"
DEFAULT_EXPIRE: Final = 0
MAX_EXTRA_BUTTONS: Final = 2
MAX_EXPIRE_MINUTES: Final = 10080

# Identifiers sent to the Companion App
ACTION_PREFIX: Final = "PINNED_PUSH"
TAG_PREFIX: Final = "pinned_push_"

# Event type used on the event entity when a notification expires
EVENT_TYPE_EXPIRED: Final = "expired"

# Bus event fired for every answer or expiry
EVENT_ANSWER: Final = "pinned_push_answer"

STATUS_IDLE: Final = "idle"
STATUS_OPEN: Final = "open"
STATUS_ANSWERED: Final = "answered"
STATUS_EXPIRED: Final = "expired"
STATUS_SNOOZED: Final = "snoozed"
STATUSES: Final = [
    STATUS_IDLE,
    STATUS_OPEN,
    STATUS_SNOOZED,
    STATUS_ANSWERED,
    STATUS_EXPIRED,
]

STORAGE_VERSION: Final = 1

# Seconds to wait before showing a dismissed notification again
RESEND_DELAY: Final = 2
# Upper bound of re-sends per notification, guards against a phone that
# clears notifications on its own in a loop
MAX_RESENDS: Final = 50

AUTOMATION_DOMAIN: Final = "automation"
EVENT_AUTOMATION_RELOADED: Final = "automation_reloaded"

ISSUE_MISSING_RECIPIENTS: Final = "missing_recipients"
ISSUE_RENAMED_BUTTONS: Final = "renamed_buttons"
ISSUE_RESEND_LIMIT: Final = "resend_limit"

MOBILE_APP_DOMAIN: Final = "mobile_app"
NOTIFY_DOMAIN: Final = "notify"
PERSON_DOMAIN: Final = "person"

EVENT_MOBILE_APP_ACTION: Final = "mobile_app_notification_action"
EVENT_MOBILE_APP_CLEARED: Final = "mobile_app_notification_cleared"

SERVICE_SEND: Final = "send"
SERVICE_DISMISS: Final = "dismiss"

ATTR_PERSONS: Final = "persons"
ATTR_TITLE: Final = "title"
ATTR_MESSAGE: Final = "message"
ATTR_IMAGE: Final = "image"
ATTR_CLICK_ACTION: Final = "click_action"
