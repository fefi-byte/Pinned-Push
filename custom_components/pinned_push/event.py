"""Event entity: fires when a notification is answered or expires."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SUBENTRY_TYPE_NOTIFICATION
from .entity import PinnedPushEntity
from .manager import PinnedPushConfigEntry, PinnedPushManager, event_types_for

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PinnedPushConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one event entity per notification."""
    manager = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_NOTIFICATION:
            continue
        async_add_entities(
            [PinnedPushAnswerEvent(manager, subentry_id)],
            config_subentry_id=subentry_id,
        )


class PinnedPushAnswerEvent(PinnedPushEntity, EventEntity):
    """Answer of a pinned notification."""

    _attr_name = None
    _attr_translation_key = "answer"

    def __init__(self, manager: PinnedPushManager, subentry_id: str) -> None:
        """Initialize."""
        super().__init__(manager, subentry_id, "answer")
        self._attr_event_types = event_types_for(manager.config(subentry_id))

    @callback
    def _handle_manager(self, kind: str, payload: dict[str, Any] | None) -> None:
        if kind != "event" or payload is None:
            return
        attributes = dict(payload)
        event_type = attributes.pop("event_type")
        if event_type not in self.event_types:
            return
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
