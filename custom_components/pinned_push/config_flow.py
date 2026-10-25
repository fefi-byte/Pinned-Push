"""Config flow for Pinned Push."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
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
    BUTTON_KEEP_OPEN,
    BUTTON_OPEN,
    BUTTON_SLOTS,
    BUTTON_SNOOZE,
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
    CONF_MINUTES,
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
    DEFAULT_SNOOZE_MINUTES,
    DEFAULT_VISIBILITY,
    DOMAIN,
    EVENT_TYPE_EXPIRED,
    IMPORTANCES,
    MAX_EXPIRE_MINUTES,
    MAX_SNOOZE_MINUTES,
    MOBILE_APP_DOMAIN,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_CHANNEL,
    SUBENTRY_TYPE_NOTIFICATION,
    VISIBILITIES,
)
from .model import Button, buttons_of, channel_ref_of, vibration_pattern


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


FIRST_BUTTON: Final = "button_1"
FIRST_BUTTON_TYPES: Final = [BUTTON_ANSWER, BUTTON_KEEP_OPEN]
CONF_REMOVE: Final = "remove"


def _first_button_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LABEL, default=DEFAULT_CONFIRM_TEXT): TextSelector(),
            vol.Required(CONF_TYPE, default=BUTTON_ANSWER): SelectSelector(
                SelectSelectorConfig(
                    options=FIRST_BUTTON_TYPES,
                    mode=SelectSelectorMode.LIST,
                    translation_key="button_type",
                )
            ),
        }
    )


def _extra_button_schema(editing: bool) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(CONF_LABEL): TextSelector(),
        vol.Required(CONF_TYPE, default=BUTTON_ANSWER): SelectSelector(
            SelectSelectorConfig(
                options=BUTTON_TYPES,
                mode=SelectSelectorMode.LIST,
                translation_key="button_type",
            )
        ),
        vol.Optional(CONF_TARGET, default=""): TextSelector(),
        vol.Required(CONF_MINUTES, default=DEFAULT_SNOOZE_MINUTES): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=MAX_SNOOZE_MINUTES,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
    }
    if editing:
        schema[vol.Required(CONF_REMOVE, default=False)] = BooleanSelector()
    return vol.Schema(schema)


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
            vol.Required(FIRST_BUTTON, default={}): section(
                _first_button_schema(), {"collapsed": False}
            ),
            vol.Required(CONF_APPEARANCE, default={}): section(
                _appearance_schema(), {"collapsed": True}
            ),
            vol.Required(CONF_DELIVERY, default={}): section(
                _delivery_schema(channels), {"collapsed": True}
            ),
        }
    )


def _button_dict(button: Button) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_LABEL: button.label,
        CONF_TYPE: button.type,
        CONF_TARGET: button.target,
    }
    if button.type == BUTTON_SNOOZE:
        data[CONF_MINUTES] = button.minutes
    return data


def _suggested(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Turn stored data into form values for the main step."""
    first = buttons_of(data)[0]
    return {
        CONF_NAME: name,
        CONF_PERSONS: data.get(CONF_PERSONS, []),
        CONF_DEVICES: data.get(CONF_DEVICES, []),
        CONF_TITLE: data.get(CONF_TITLE, ""),
        CONF_MESSAGE: data.get(CONF_MESSAGE, ""),
        CONF_ICON: data.get(CONF_ICON, DEFAULT_ICON),
        CONF_RESEND: data.get(CONF_RESEND, True),
        CONF_EXPIRE: data.get(CONF_EXPIRE, DEFAULT_EXPIRE),
        FIRST_BUTTON: {CONF_LABEL: first.label, CONF_TYPE: first.type},
        CONF_APPEARANCE: {
            k: data[k] for k in APPEARANCE_KEYS if data.get(k) is not None
        },
        CONF_DELIVERY: {
            CONF_URGENT: data.get(CONF_URGENT, True),
            CONF_CHANNEL_REF: channel_ref_of(data),
        },
    }


def _label_errors(label: str, others: list[dict[str, Any]]) -> str | None:
    """Return an error for a label that is reserved or already used."""
    if label.casefold() == EVENT_TYPE_EXPIRED:
        return "reserved_button"
    if any(b[CONF_LABEL].casefold() == label.casefold() for b in others):
        return "duplicate_buttons"
    return None


def _validate_main(
    user_input: dict[str, Any], others: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, str]]:
    """Normalize the main step; return (name, data, first button, errors)."""
    errors: dict[str, str] = {}
    name = user_input[CONF_NAME].strip()
    persons = list(user_input.get(CONF_PERSONS, []))
    devices = list(user_input.get(CONF_DEVICES, []))
    if not name:
        errors[CONF_NAME] = "empty_name"
    if not persons and not devices:
        errors["base"] = "no_recipients"

    raw = user_input.get(FIRST_BUTTON) or {}
    label = (raw.get(CONF_LABEL) or "").strip()
    kind = raw.get(CONF_TYPE) or BUTTON_ANSWER
    if not label:
        errors[FIRST_BUTTON] = "empty_button"
    elif error := _label_errors(label, others):
        errors["base"] = error
    if kind not in FIRST_BUTTON_TYPES:
        errors[FIRST_BUTTON] = "first_button_answers"
    first = {CONF_LABEL: label, CONF_TYPE: kind, CONF_TARGET: ""}

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
    return name, data, first, errors


def _validate_button(
    user_input: dict[str, Any], others: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize an additional button; return (button, errors)."""
    errors: dict[str, str] = {}
    label = (user_input.get(CONF_LABEL) or "").strip()
    kind = user_input.get(CONF_TYPE) or BUTTON_ANSWER
    target = (user_input.get(CONF_TARGET) or "").strip()
    if not label:
        errors[CONF_LABEL] = "empty_label"
    elif error := _label_errors(label, others):
        errors["base"] = error
    if kind == BUTTON_OPEN and not target:
        errors[CONF_TARGET] = "missing_target"
    button: dict[str, Any] = {
        CONF_LABEL: label,
        CONF_TYPE: kind,
        CONF_TARGET: target if kind == BUTTON_OPEN else "",
    }
    if kind == BUTTON_SNOOZE:
        button[CONF_MINUTES] = int(
            user_input.get(CONF_MINUTES) or DEFAULT_SNOOZE_MINUTES
        )
    return button, errors


class NotificationSubentryFlow(ConfigSubentryFlow):
    """Add or change a notification.

    The main form holds everything plus the mandatory first button. A menu
    afterwards adds, changes or removes the optional buttons one by one.
    """

    def __init__(self) -> None:
        """Initialize."""
        self._name = ""
        self._data: dict[str, Any] = {}
        self._buttons: list[dict[str, Any]] = []
        self._edit_index: int | None = None

    def _channels(self) -> list[SelectOptionDict]:
        return _channel_options(self._get_entry(), self.hass.config.language)

    async def _main_step(
        self, step_id: str, user_input: dict[str, Any] | None, suggested: dict
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data, first, errors = _validate_main(user_input, self._buttons[1:])
            if not errors:
                self._name, self._data = name, data
                self._buttons = [first, *self._buttons[1:]]
                return await self.async_step_buttons()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _notification_schema(self._channels()), user_input or suggested
            ),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a notification: main form with the first button."""
        return await self._main_step("user", user_input, {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a notification: main form with the first button."""
        subentry = self._get_reconfigure_subentry()
        if user_input is None and not self._buttons:
            self._buttons = [_button_dict(b) for b in buttons_of(dict(subentry.data))]
        return await self._main_step(
            "reconfigure", user_input, _suggested(dict(subentry.data), subentry.title)
        )

    async def async_step_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Menu: add, change or remove buttons, or save."""
        options = []
        if len(self._buttons) < len(BUTTON_SLOTS):
            options.append("add_button")
        options.extend(
            f"edit_button_{index + 1}" for index in range(1, len(self._buttons))
        )
        options.append("finish")
        labels = [b[CONF_LABEL] for b in self._buttons]
        return self.async_show_menu(
            step_id="buttons",
            menu_options=options,
            description_placeholders={
                "buttons": ", ".join(labels),
                "button_2": labels[1] if len(labels) > 1 else "",
                "button_3": labels[2] if len(labels) > 2 else "",
            },
        )

    async def async_step_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add one more button."""
        self._edit_index = None
        return await self._button_step("add_button", user_input)

    async def async_step_edit_button_2(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change or remove button 2."""
        self._edit_index = 1
        return await self._button_step("edit_button_2", user_input)

    async def async_step_edit_button_3(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change or remove button 3."""
        self._edit_index = 2
        return await self._button_step("edit_button_3", user_input)

    async def _button_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        index = self._edit_index
        editing = index is not None and index < len(self._buttons)
        errors: dict[str, str] = {}
        if user_input is not None:
            if editing and user_input.get(CONF_REMOVE):
                del self._buttons[index]
                return await self.async_step_buttons()
            others = [b for i, b in enumerate(self._buttons) if i != index]
            button, errors = _validate_button(user_input, others)
            if not errors:
                if editing:
                    self._buttons[index] = button
                else:
                    self._buttons.append(button)
                return await self.async_step_buttons()
        suggested = user_input or (
            {
                CONF_MINUTES: DEFAULT_SNOOZE_MINUTES,
                **self._buttons[index],
            }
            if editing
            else {}
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _extra_button_schema(editing), suggested
            ),
            errors=errors,
            description_placeholders={
                "number": str((index if editing else len(self._buttons)) + 1)
            },
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Save the notification."""
        data = {**self._data, CONF_BUTTON_LIST: self._buttons}
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=self._name,
                data=data,
            )
        return self.async_create_entry(title=self._name, data=data)


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
