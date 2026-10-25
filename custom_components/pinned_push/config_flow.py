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
    TextSelector,
    TextSelectorConfig,
)
import voluptuous as vol

from .const import (
    CONF_BUTTONS,
    CONF_CONFIRM_TEXT,
    CONF_DEVICES,
    CONF_EXPIRE,
    CONF_ICON,
    CONF_MESSAGE,
    CONF_PERSONS,
    CONF_RESEND,
    CONF_TITLE,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_EXPIRE,
    DEFAULT_ICON,
    DOMAIN,
    EVENT_TYPE_EXPIRED,
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


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)
            ): TextSelector(),
            vol.Optional(
                CONF_PERSONS, default=defaults.get(CONF_PERSONS, [])
            ): EntitySelector(
                EntitySelectorConfig(domain=PERSON_DOMAIN, multiple=True)
            ),
            vol.Optional(
                CONF_DEVICES, default=defaults.get(CONF_DEVICES, [])
            ): DeviceSelector(
                DeviceSelectorConfig(integration=MOBILE_APP_DOMAIN, multiple=True)
            ),
            vol.Required(
                CONF_TITLE, default=defaults.get(CONF_TITLE, vol.UNDEFINED)
            ): TextSelector(),
            vol.Required(
                CONF_MESSAGE, default=defaults.get(CONF_MESSAGE, vol.UNDEFINED)
            ): TextSelector(TextSelectorConfig(multiline=True)),
            vol.Required(
                CONF_CONFIRM_TEXT,
                default=defaults.get(CONF_CONFIRM_TEXT, DEFAULT_CONFIRM_TEXT),
            ): TextSelector(),
            vol.Optional(
                CONF_BUTTONS, default=defaults.get(CONF_BUTTONS, [])
            ): TextSelector(TextSelectorConfig(multiple=True)),
            vol.Optional(
                CONF_ICON, default=defaults.get(CONF_ICON, DEFAULT_ICON)
            ): IconSelector(),
            vol.Required(
                CONF_RESEND, default=defaults.get(CONF_RESEND, True)
            ): BooleanSelector(),
            vol.Required(
                CONF_EXPIRE, default=defaults.get(CONF_EXPIRE, DEFAULT_EXPIRE)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=MAX_EXPIRE_MINUTES,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
        }
    )


def _validate(user_input: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Normalize the input; return (name, data, errors)."""
    errors: dict[str, str] = {}
    name = user_input[CONF_NAME].strip()
    confirm = user_input[CONF_CONFIRM_TEXT].strip()
    buttons = [b.strip() for b in user_input.get(CONF_BUTTONS, []) if b.strip()]
    persons = list(user_input.get(CONF_PERSONS, []))
    devices = list(user_input.get(CONF_DEVICES, []))

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
                _schema({}), user_input or {}
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
        defaults = {CONF_NAME: subentry.title, **subentry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema(defaults), user_input or {}
            ),
            errors=errors,
        )
