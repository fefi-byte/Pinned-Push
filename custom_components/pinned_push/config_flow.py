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
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol

from .const import (
    CONF_ALARM_STREAM,
    CONF_BUTTONS,
    CONF_CHANNEL,
    CONF_CONFIRM_TEXT,
    CONF_DELIVERY,
    CONF_DEVICES,
    CONF_EXPIRE,
    CONF_ICON,
    CONF_IMPORTANCE,
    CONF_MESSAGE,
    CONF_PERSONS,
    CONF_RESEND,
    CONF_TITLE,
    CONF_URGENT,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_EXPIRE,
    DEFAULT_ICON,
    DEFAULT_IMPORTANCE,
    DELIVERY_KEYS,
    DOMAIN,
    EVENT_TYPE_EXPIRED,
    IMPORTANCES,
    MAX_EXPIRE_MINUTES,
    MAX_EXTRA_BUTTONS,
    MOBILE_APP_DOMAIN,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_NOTIFICATION,
)


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
        """Notifications are added as subentries."""
        return {SUBENTRY_TYPE_NOTIFICATION: NotificationSubentryFlow}


def _delivery_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URGENT, default=True): BooleanSelector(),
            vol.Required(CONF_ALARM_STREAM, default=False): BooleanSelector(),
            vol.Optional(CONF_CHANNEL, default=""): TextSelector(),
            vol.Required(CONF_IMPORTANCE, default=DEFAULT_IMPORTANCE): SelectSelector(
                SelectSelectorConfig(
                    options=IMPORTANCES,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_IMPORTANCE,
                )
            ),
        }
    )


def _schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Optional(CONF_PERSONS, default=[]): EntitySelector(
                EntitySelectorConfig(domain=PERSON_DOMAIN, multiple=True)
            ),
            vol.Optional(CONF_DEVICES, default=[]): DeviceSelector(
                DeviceSelectorConfig(integration=MOBILE_APP_DOMAIN, multiple=True)
            ),
            vol.Required(CONF_TITLE): TextSelector(),
            vol.Required(CONF_MESSAGE): TextSelector(
                TextSelectorConfig(multiline=True)
            ),
            vol.Required(
                CONF_CONFIRM_TEXT, default=DEFAULT_CONFIRM_TEXT
            ): TextSelector(),
            vol.Optional(CONF_BUTTONS, default=[]): TextSelector(
                TextSelectorConfig(multiple=True)
            ),
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
            vol.Required(CONF_DELIVERY, default={}): section(
                _delivery_schema(), {"collapsed": True}
            ),
        }
    )


def _suggested(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Turn stored data into form values, delivery options in their section."""
    values = {k: v for k, v in data.items() if k not in DELIVERY_KEYS}
    values[CONF_NAME] = name
    values[CONF_DELIVERY] = {k: data[k] for k in DELIVERY_KEYS if k in data}
    return values


def _validate(
    user_input: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Normalize the input; return (name, data, errors)."""
    errors: dict[str, str] = {}
    name = user_input[CONF_NAME].strip()
    confirm = user_input[CONF_CONFIRM_TEXT].strip()
    buttons = [b.strip() for b in user_input.get(CONF_BUTTONS, []) if b.strip()]
    persons = list(user_input.get(CONF_PERSONS, []))
    devices = list(user_input.get(CONF_DEVICES, []))
    delivery = user_input.get(CONF_DELIVERY, {})

    if not name:
        errors[CONF_NAME] = "empty_name"
    if not persons and not devices:
        errors["base"] = "no_recipients"
    if not confirm:
        errors[CONF_CONFIRM_TEXT] = "empty_button"
    if len(buttons) > MAX_EXTRA_BUTTONS:
        errors[CONF_BUTTONS] = "too_many_buttons"
    labels = [confirm.casefold(), *(b.casefold() for b in buttons)]
    if EVENT_TYPE_EXPIRED in labels:
        errors[CONF_BUTTONS] = "reserved_button"
    elif len(set(labels)) != len(labels):
        errors[CONF_BUTTONS] = "duplicate_buttons"

    data = {
        CONF_PERSONS: persons,
        CONF_DEVICES: devices,
        CONF_TITLE: user_input[CONF_TITLE],
        CONF_MESSAGE: user_input[CONF_MESSAGE],
        CONF_CONFIRM_TEXT: confirm,
        CONF_BUTTONS: buttons,
        CONF_ICON: user_input.get(CONF_ICON) or DEFAULT_ICON,
        CONF_RESEND: user_input[CONF_RESEND],
        CONF_EXPIRE: int(user_input[CONF_EXPIRE]),
        CONF_URGENT: delivery.get(CONF_URGENT, True),
        CONF_ALARM_STREAM: delivery.get(CONF_ALARM_STREAM, False),
        CONF_CHANNEL: (delivery.get(CONF_CHANNEL) or "").strip(),
        CONF_IMPORTANCE: delivery.get(CONF_IMPORTANCE, DEFAULT_IMPORTANCE),
    }
    return name, data, errors


class NotificationSubentryFlow(ConfigSubentryFlow):
    """Add or change a notification."""

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
                _schema(), user_input or {}
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
                _schema(), user_input or _suggested(dict(subentry.data), subentry.title)
            ),
            errors=errors,
        )
