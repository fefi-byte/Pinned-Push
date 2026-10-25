"""Actions of Pinned Push."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
import voluptuous as vol

from .const import (
    ATTR_CLICK_ACTION,
    ATTR_IMAGE,
    ATTR_MESSAGE,
    ATTR_PERSONS,
    ATTR_TITLE,
    DOMAIN,
    SERVICE_DISMISS,
    SERVICE_SEND,
)
from .manager import PinnedPushManager

SEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_PERSONS): vol.All(
            cv.ensure_list, [cv.entity_domain("person")]
        ),
        vol.Optional(ATTR_IMAGE): cv.string,
        vol.Optional(ATTR_CLICK_ACTION): cv.string,
    }
)

DISMISS_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids})


def _resolve(hass: HomeAssistant, entity_id: str) -> tuple[PinnedPushManager, str]:
    """Find the manager and notification behind an event entity."""
    entry = er.async_get(hass).async_get(entity_id)
    if (
        entry is None
        or entry.platform != DOMAIN
        or entry.config_entry_id is None
        or entry.config_subentry_id is None
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_notification",
            translation_placeholders={"entity_id": entity_id},
        )
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    manager: PinnedPushManager = config_entry.runtime_data
    if entry.config_subentry_id not in manager.states:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_notification",
            translation_placeholders={"entity_id": entity_id},
        )
    return manager, entry.config_subentry_id


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def _send(call: ServiceCall) -> ServiceResponse:
        results: dict[str, Any] = {}
        targets = [_resolve(hass, eid) + (eid,) for eid in call.data[ATTR_ENTITY_ID]]
        for manager, subentry_id, entity_id in targets:
            results[entity_id] = await manager.async_send(
                subentry_id,
                title=call.data.get(ATTR_TITLE),
                message=call.data.get(ATTR_MESSAGE),
                persons=call.data.get(ATTR_PERSONS),
                image=call.data.get(ATTR_IMAGE),
                click_action=call.data.get(ATTR_CLICK_ACTION),
            )
        if call.return_response:
            return {"notifications": results}
        return None

    async def _dismiss(call: ServiceCall) -> None:
        targets = [_resolve(hass, eid) for eid in call.data[ATTR_ENTITY_ID]]
        for manager, subentry_id in targets:
            await manager.async_dismiss(subentry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND,
        _send,
        schema=SEND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS, _dismiss, schema=DISMISS_SCHEMA
    )
