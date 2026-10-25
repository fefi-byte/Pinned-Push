"""Config flow for Pinned Push."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol

from .const import (
    APPEARANCE_KEYS,
    BUTTON_ANSWER,
    BUTTON_OPEN,
    BUTTON_SLOTS,
    BUTTON_TYPES,
    CHANNEL_ALARM,
    CHANNEL_DEFAULT,
    CONF_APPEARANCE,
    CONF_BUTTON_LIST,
    CONF_CAMERA,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_REF,
    CONF_CLICK_ACTION,
    CONF_COLOR,
    CONF_COUNTDOWN,
    CONF_DELIVERY,
    CONF_DEVICES,
    CONF_EXPIRE,
    CONF_GROUP,
    CONF_ICON,
    CONF_IMAGE,
    CONF_IMPORTANCE,
    CONF_LABEL,
    CONF_LED_COLOR,
    CONF_MESSAGE,
    CONF_PERSONS,
    CONF_RESEND,
    CONF_TARGET,
    CONF_TITLE,
    CONF_TYPE,
    CONF_URGENT,
    CONF_VIBRATION,
    CONF_VISIBILITY,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_EXPIRE,
    DEFAULT_ICON,
    DEFAULT_IMPORTANCE,
    DEFAULT_VISIBILITY,
    DOMAIN,
    EVENT_TYPE_EXPIRED,
    IMPORTANCES,
    MAX_EXPIRE_MINUTES,
    MOBILE_APP_DOMAIN,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_CHANNEL,
    SUBENTRY_TYPE_NOTIFICATION,
    VISIBILITIES,
)
from .model import buttons_of, channel_ref_of, vibration_pattern


class PinnedPushConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the integration (single instance)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup."""
        if user_input is not None:
            return self.async_create_entry(title="Pinned Push", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Notifications and channels are added as subentries."""
        return {
            SUBENTRY_TYPE_NOTIFICATION: NotificationSubentryFlow,
            SUBENTRY_TYPE_CHANNEL: ChannelSubentryFlow,
        }


# ----------------------------------------------------------------------
# Notification


def _button_schema(first: bool) -> vol.Schema:
    label = (
        vol.Required(CONF_LABEL, default=DEFAULT_CONFIRM_TEXT)
        if first
        else vol.Optional(CONF_LABEL, default="")
    )
    return vol.Schema(
        {
            label: TextSelector(),
            vol.Required(CONF_TYPE, default=BUTTON_ANSWER): SelectSelector(
                SelectSelectorConfig(
                    options=BUTTON_TYPES,
                    mode=SelectSelectorMode.LIST,
                    translation_key="button_type",
                )
            ),
            vol.Optional(CONF_TARGET, default=""): TextSelector(),
        }
    )


def _appearance_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_COLOR): ColorRGBSelector(),
            vol.Optional(CONF_CAMERA): EntitySelector(
                EntitySelectorConfig(domain="camera")
            ),
            vol.Optional(CONF_IMAGE, default=""): TextSelector(),
            vol.Optional(CONF_CLICK_ACTION, default=""): TextSelector(),
            vol.Required(CONF_VISIBILITY, default=DEFAULT_VISIBILITY): SelectSelector(
                SelectSelectorConfig(
                    options=VISIBILITIES,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_VISIBILITY,
                )
            ),
            vol.Required(CONF_COUNTDOWN, default=False): BooleanSelector(),
            vol.Optional(CONF_GROUP, default=""): TextSelector(),
        }
    )


def _channel_options(entry: ConfigEntry, language: str) -> list[SelectOptionDict]:
    german = language.startswith("de")
    options = [
        SelectOptionDict(
            value=CHANNEL_DEFAULT,
            label="Standard (Android)" if german else "Default (Android)",
        ),
        SelectOptionDict(
            value=CHANNEL_ALARM,
            label="Wecker – klingelt auch bei lautlos"
            if german
            else "Alarm – rings even on silent",
        ),
    ]
    options.extend(
        SelectOptionDict(value=sid, label=sub.title)
        for sid, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_TYPE_CHANNEL
    )
    return options


def _delivery_schema(channels: list[SelectOptionDict]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URGENT, default=True): BooleanSelector(),
            vol.Required(CONF_CHANNEL_REF, default=CHANNEL_DEFAULT): SelectSelector(
                SelectSelectorConfig(options=channels, mode=SelectSelectorMode.DROPDOWN)
            ),
        }
    )


def _notification_schema(channels: list[SelectOptionDict]) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Optional(CONF_PERSONS, default=[]): EntitySelector(
            EntitySelectorConfig(domain=PERSON_DOMAIN, multiple=True)
        ),
        vol.Optional(CONF_DEVICES, default=[]): DeviceSelector(
            DeviceSelectorConfig(integration=MOBILE_APP_DOMAIN, multiple=True)
        ),
        vol.Required(CONF_TITLE): TextSelector(),
        vol.Required(CONF_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        vol.Optional(CONF_ICON, default=DEFAULT_ICON): IconSelector(),
        vol.Required(CONF_RESEND, default=True): BooleanSelector(),
        vol.Required(CONF_EXPIRE, default=DEFAULT_EXPIRE): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_EXPIRE_MINUTES,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
    }
    for index, slot in enumerate(BUTTON_SLOTS):
        schema[vol.Required(slot, default={})] = section(
            _button_schema(first=index == 0), {"collapsed": index > 0}
        )
    schema[vol.Required(CONF_APPEARANCE, default={})] = section(
        _appearance_schema(), {"collapsed": True}
    )
    schema[vol.Required(CONF_DELIVERY, default={})] = section(
        _delivery_schema(channels), {"collapsed": True}
    )
    return vol.Schema(schema)


def _suggested(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Turn stored data into form values, with sections nested."""
    buttons = buttons_of(data)
    values: dict[str, Any] = {
        CONF_NAME: name,
        CONF_PERSONS: data.get(CONF_PERSONS, []),
        CONF_DEVICES: data.get(CONF_DEVICES, []),
        CONF_TITLE: data.get(CONF_TITLE, ""),
        CONF_MESSAGE: data.get(CONF_MESSAGE, ""),
        CONF_ICON: data.get(CONF_ICON, DEFAULT_ICON),
        CONF_RESEND: data.get(CONF_RESEND, True),
        CONF_EXPIRE: data.get(CONF_EXPIRE, DEFAULT_EXPIRE),
        CONF_APPEARANCE: {
            k: data[k] for k in APPEARANCE_KEYS if data.get(k) is not None
        },
        CONF_DELIVERY: {
            CONF_URGENT: data.get(CONF_URGENT, True),
            CONF_CHANNEL_REF: channel_ref_of(data),
        },
    }
    for index, slot in enumerate(BUTTON_SLOTS):
        if index < len(buttons):
            b = buttons[index]
            values[slot] = {
                CONF_LABEL: b.label,
                CONF_TYPE: b.type,
                CONF_TARGET: b.target,
            }
    return values


def _validate(
    user_input: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Normalize the input; return (name, data, errors)."""
    errors: dict[str, str] = {}
    name = user_input[CONF_NAME].strip()
    persons = list(user_input.get(CONF_PERSONS, []))
    devices = list(user_input.get(CONF_DEVICES, []))

    if not name:
        errors[CONF_NAME] = "empty_name"
    if not persons and not devices:
        errors["base"] = "no_recipients"

    buttons: list[dict[str, str]] = []
    for index, slot in enumerate(BUTTON_SLOTS):
        raw = user_input.get(slot) or {}
        label = (raw.get(CONF_LABEL) or "").strip()
        if not label:
            if index == 0:
                errors[slot] = "empty_button"
            continue
        kind = raw.get(CONF_TYPE) or BUTTON_ANSWER
        target = (raw.get(CONF_TARGET) or "").strip()
        if kind == BUTTON_OPEN and not target:
            errors[slot] = "missing_target"
        buttons.append({CONF_LABEL: label, CONF_TYPE: kind, CONF_TARGET: target})

    labels = [b[CONF_LABEL].casefold() for b in buttons]
    if EVENT_TYPE_EXPIRED in labels:
        errors["base"] = "reserved_button"
    elif len(set(labels)) != len(labels):
        errors["base"] = "duplicate_buttons"
    if buttons and buttons[0][CONF_TYPE] == BUTTON_OPEN:
        errors[BUTTON_SLOTS[0]] = "first_button_answers"

    appearance = user_input.get(CONF_APPEARANCE) or {}
    delivery = user_input.get(CONF_DELIVERY) or {}
    data: dict[str, Any] = {
        CONF_PERSONS: persons,
        CONF_DEVICES: devices,
        CONF_TITLE: user_input[CONF_TITLE],
        CONF_MESSAGE: user_input[CONF_MESSAGE],
        CONF_ICON: user_input.get(CONF_ICON) or DEFAULT_ICON,
        CONF_RESEND: user_input[CONF_RESEND],
        CONF_EXPIRE: int(user_input[CONF_EXPIRE]),
        CONF_BUTTON_LIST: buttons,
        CONF_URGENT: delivery.get(CONF_URGENT, True),
        CONF_CHANNEL_REF: delivery.get(CONF_CHANNEL_REF) or CHANNEL_DEFAULT,
        CONF_COLOR: appearance.get(CONF_COLOR),
        CONF_CAMERA: appearance.get(CONF_CAMERA) or None,
        CONF_IMAGE: (appearance.get(CONF_IMAGE) or "").strip(),
        CONF_CLICK_ACTION: (appearance.get(CONF_CLICK_ACTION) or "").strip(),
        CONF_VISIBILITY: appearance.get(CONF_VISIBILITY) or DEFAULT_VISIBILITY,
        CONF_COUNTDOWN: bool(appearance.get(CONF_COUNTDOWN)),
        CONF_GROUP: (appearance.get(CONF_GROUP) or "").strip(),
    }
    return name, data, errors


class NotificationSubentryFlow(ConfigSubentryFlow):
    """Add or change a notification."""

    def _channels(self) -> list[SelectOptionDict]:
        return _channel_options(self._get_entry(), self.hass.config.language)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a notification."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data, errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title=name, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _notification_schema(self._channels()), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a notification."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data, errors = _validate(user_input)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name, data=data
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _notification_schema(self._channels()),
                user_input or _suggested(dict(subentry.data), subentry.title),
            ),
            errors=errors,
        )


# ----------------------------------------------------------------------
# Channel


def _channel_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CHANNEL_NAME): TextSelector(),
            vol.Required(CONF_IMPORTANCE, default=DEFAULT_IMPORTANCE): SelectSelector(
                SelectSelectorConfig(
                    options=IMPORTANCES,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_IMPORTANCE,
                )
            ),
            vol.Optional(CONF_VIBRATION, default=""): TextSelector(),
            vol.Optional(CONF_LED_COLOR): ColorRGBSelector(),
        }
    )


def _validate_channel(
    entry: ConfigEntry, user_input: dict[str, Any], own_id: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    name = user_input[CONF_CHANNEL_NAME].strip()
    vibration = (user_input.get(CONF_VIBRATION) or "").strip()
    if not name:
        errors[CONF_CHANNEL_NAME] = "empty_name"
    elif name.casefold() in (CHANNEL_ALARM, "general"):
        errors[CONF_CHANNEL_NAME] = "reserved_channel"
    elif any(
        sub.subentry_type == SUBENTRY_TYPE_CHANNEL
        and sid != own_id
        and sub.data.get(CONF_CHANNEL_NAME, "").casefold() == name.casefold()
        for sid, sub in entry.subentries.items()
    ):
        errors[CONF_CHANNEL_NAME] = "duplicate_channel"
    if vibration and vibration_pattern(vibration) is None:
        errors[CONF_VIBRATION] = "invalid_vibration"
    data = {
        CONF_CHANNEL_NAME: name,
        CONF_IMPORTANCE: user_input.get(CONF_IMPORTANCE) or DEFAULT_IMPORTANCE,
        CONF_VIBRATION: vibration_pattern(vibration) or "",
        CONF_LED_COLOR: user_input.get(CONF_LED_COLOR),
    }
    return data, errors


class ChannelSubentryFlow(ConfigSubentryFlow):
    """Add or change an Android notification channel."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a channel."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_channel(self._get_entry(), user_input, None)
            if not errors:
                return self.async_create_entry(title=data[CONF_CHANNEL_NAME], data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _channel_schema(), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a channel."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_channel(
                self._get_entry(), user_input, subentry.subentry_id
            )
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=data[CONF_CHANNEL_NAME],
                    data=data,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _channel_schema(), user_input or dict(subentry.data)
            ),
            errors=errors,
        )
