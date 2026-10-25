"""Reading the stored configuration of notifications and channels.

Keeps the knowledge of old storage formats in one place: notifications
created by 0.1/0.2 store ``confirm_text``/``buttons`` and per-notification
channel fields; they are read here as if they used the 0.3 format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    ANSWER_TYPES,
    BUTTON_ANSWER,
    BUTTON_OPEN,
    CHANNEL_ALARM,
    CHANNEL_DEFAULT,
    CONF_BUTTON_LIST,
    CONF_BUTTONS,
    CONF_CAMERA,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_REF,
    CONF_CLICK_ACTION,
    CONF_COLOR,
    CONF_CONFIRM_TEXT,
    CONF_COUNTDOWN,
    CONF_GROUP,
    CONF_IMAGE,
    CONF_IMPORTANCE,
    CONF_LABEL,
    CONF_LED_COLOR,
    CONF_MINUTES,
    CONF_TARGET,
    CONF_TYPE,
    CONF_VIBRATION,
    CONF_VISIBILITY,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_IMPORTANCE,
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VISIBILITY,
    EVENT_TYPE_EXPIRED,
)


@dataclass(frozen=True)
class Button:
    """One button of a notification."""

    label: str
    type: str
    target: str = ""
    minutes: int = DEFAULT_SNOOZE_MINUTES

    @property
    def answers(self) -> bool:
        """Whether pressing it is reported as an answer."""
        return self.type in ANSWER_TYPES


def buttons_of(config: dict[str, Any]) -> list[Button]:
    """Return the buttons of a notification, in slot order."""
    if CONF_BUTTON_LIST in config:
        return [
            Button(
                label=b[CONF_LABEL],
                type=b.get(CONF_TYPE, BUTTON_ANSWER),
                target=b.get(CONF_TARGET, ""),
                minutes=int(b.get(CONF_MINUTES) or DEFAULT_SNOOZE_MINUTES),
            )
            for b in config[CONF_BUTTON_LIST]
        ]
    # 0.1 / 0.2 format: a confirm button plus answer buttons
    labels = [
        config.get(CONF_CONFIRM_TEXT) or DEFAULT_CONFIRM_TEXT,
        *config.get(CONF_BUTTONS, []),
    ]
    return [Button(label=label, type=BUTTON_ANSWER) for label in labels]


def answer_labels(config: dict[str, Any]) -> list[str]:
    """Return the labels of the buttons that report an answer."""
    return [b.label for b in buttons_of(config) if b.answers]


def event_types_for(config: dict[str, Any]) -> list[str]:
    """Return the event types of a notification: answer labels plus expired."""
    return [*answer_labels(config), EVENT_TYPE_EXPIRED]


def rgb_to_hex(value: Any) -> str | None:
    """Turn a color selector value ([r, g, b]) into #rrggbb."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        r, g, b = (max(0, min(255, int(c))) for c in value)
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def vibration_pattern(value: str | None) -> str | None:
    """Normalize a vibration pattern like '0, 500,250 ,500'."""
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return ", ".join(parts)


@dataclass(frozen=True)
class Channel:
    """Android notification channel settings."""

    name: str
    importance: str = DEFAULT_IMPORTANCE
    vibration: str | None = None
    led_color: str | None = None

    def as_data(self) -> dict[str, Any]:
        """Return the notification data keys for this channel."""
        data: dict[str, Any] = {"channel": self.name, "importance": self.importance}
        if self.vibration:
            data["vibrationPattern"] = self.vibration
        if self.led_color:
            data["ledColor"] = self.led_color
        return data

    def fingerprint(self) -> list[Any]:
        """Return what Android fixes at channel creation."""
        return [self.name, self.importance, self.vibration, self.led_color]


def channel_from_subentry(data: dict[str, Any]) -> Channel:
    """Return the channel described by a channel subentry."""
    return Channel(
        name=data[CONF_CHANNEL_NAME],
        importance=data.get(CONF_IMPORTANCE) or DEFAULT_IMPORTANCE,
        vibration=vibration_pattern(data.get(CONF_VIBRATION)),
        led_color=rgb_to_hex(data.get(CONF_LED_COLOR)),
    )


def channel_ref_of(config: dict[str, Any]) -> str:
    """Return the channel choice of a notification (0.2 fields included)."""
    if ref := config.get(CONF_CHANNEL_REF):
        return ref
    if config.get("alarm_stream"):
        return CHANNEL_ALARM
    return CHANNEL_DEFAULT


def legacy_channel(config: dict[str, Any]) -> Channel | None:
    """Return a channel typed directly into a 0.2 notification."""
    if config.get(CONF_CHANNEL_REF):
        return None
    name = (config.get("channel") or "").strip()
    if not name:
        return None
    return Channel(
        name=name, importance=config.get(CONF_IMPORTANCE) or DEFAULT_IMPORTANCE
    )


def appearance_data(
    config: dict[str, Any],
    *,
    image: str | None = None,
    click_action: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """Return the notification data keys of the appearance options."""
    data: dict[str, Any] = {}
    if color := rgb_to_hex(config.get(CONF_COLOR)):
        data["color"] = color
    if image is None:
        if camera := config.get(CONF_CAMERA):
            image = f"/api/camera_proxy/{camera}"
        else:
            image = config.get(CONF_IMAGE) or None
    if image:
        data["image"] = image
    if click_action is None:
        click_action = config.get(CONF_CLICK_ACTION) or None
    if click_action:
        data["clickAction"] = click_action
    visibility = config.get(CONF_VISIBILITY) or DEFAULT_VISIBILITY
    if visibility != DEFAULT_VISIBILITY:
        data["visibility"] = visibility
    if config.get(CONF_COUNTDOWN) and expires_at:
        data["chronometer"] = True
        data["when"] = int(expires_at)
    if group := (config.get(CONF_GROUP) or "").strip():
        data["group"] = group
    return data


def action_entries(buttons: list[Button], action_id: Any) -> list[dict[str, Any]]:
    """Return the Companion App action list for the buttons.

    ``action_id`` maps a slot index to the action id of an answer button.
    """
    actions: list[dict[str, Any]] = []
    for index, button in enumerate(buttons):
        if button.type == BUTTON_OPEN:
            actions.append(
                {"action": "URI", "title": button.label, "uri": button.target}
            )
        else:
            actions.append({"action": action_id(index), "title": button.label})
    return actions
