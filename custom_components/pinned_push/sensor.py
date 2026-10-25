"""Status sensor of a notification."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUSES, SUBENTRY_TYPE_NOTIFICATION
from .entity import PinnedPushEntity
from .manager import PinnedPushConfigEntry, PinnedPushManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PinnedPushConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one status sensor per notification."""
    manager = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_NOTIFICATION:
            continue
        async_add_entities(
            [PinnedPushStatusSensor(manager, subentry_id)],
            config_subentry_id=subentry_id,
        )


class PinnedPushStatusSensor(PinnedPushEntity, SensorEntity):
    """Whether a notification is open, answered or expired."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_translation_key = "status"

    def __init__(self, manager: PinnedPushManager, subentry_id: str) -> None:
        """Initialize."""
        super().__init__(manager, subentry_id, "status")

    @property
    def native_value(self) -> str:
        """Return the status."""
        return self.notification_state["status"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the last send and answer."""
        state = self.notification_state
        answer = state.get("answer") or {}
        return {
            "send_id": state.get("send_id"),
            "resends": state.get("resends"),
            "sent_at": state.get("sent_at"),
            "expires_at": state.get("expires_at"),
            "snoozed_until": state.get("snoozed_until"),
            "recipients": [f"notify.{s}" for s in state.get("targets", [])],
            "answer": answer.get("button"),
            "answer_index": answer.get("button_index"),
            "confirmed": answer.get("confirmed"),
            "answered_by": answer.get("person"),
            "answered_by_name": answer.get("person_name"),
            "answered_on": answer.get("device"),
            "answered_at": answer.get("at"),
        }
