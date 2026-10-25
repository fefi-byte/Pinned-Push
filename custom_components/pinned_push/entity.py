"""Base entity for Pinned Push."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import PinnedPushManager


class PinnedPushEntity(Entity):
    """Entity belonging to one notification."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: PinnedPushManager, subentry_id: str, key: str) -> None:
        """Initialize."""
        self.manager = manager
        self.subentry_id = subentry_id
        self._attr_unique_id = f"{subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry_id)},
            name=manager.title(subentry_id),
            manufacturer="Pinned Push",
            model="Notification",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def notification_state(self) -> dict[str, Any]:
        """Return the stored state of this notification."""
        return self.manager.states[self.subentry_id]

    async def async_added_to_hass(self) -> None:
        """Subscribe to the manager."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.manager.async_add_listener(self.subentry_id, self._handle_manager)
        )

    def _handle_manager(self, kind: str, payload: dict[str, Any] | None) -> None:
        if kind == "update":
            self.async_write_ha_state()
