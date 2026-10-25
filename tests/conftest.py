"""Fixtures for Pinned Push tests."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pinned_push.const import DOMAIN

USER_A = "user-a"
USER_B = "user-b"
WEBHOOK_A = "webhook-a"
WEBHOOK_B = "webhook-b"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture
def notify_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Fake the notify services of two Companion Apps."""
    calls: list[ServiceCall] = []

    async def _handle(call: ServiceCall) -> None:
        calls.append(call)

    for service in ("mobile_app_phone_a", "mobile_app_phone_b"):
        hass.services.async_register("notify", service, _handle)
    return calls


@pytest.fixture
def phones(hass: HomeAssistant, notify_calls: list[ServiceCall]) -> None:
    """Two people, each with a Companion App phone."""
    ent_reg = er.async_get(hass)
    for name, user, webhook, person, friendly in (
        ("Phone A", USER_A, WEBHOOK_A, "person.felix", "Felix"),
        ("Phone B", USER_B, WEBHOOK_B, "person.anna", "Anna"),
    ):
        entry = MockConfigEntry(
            domain="mobile_app",
            data={"device_name": name, "user_id": user, "webhook_id": webhook},
        )
        entry.add_to_hass(hass)
        slug = name.lower().replace(" ", "_")
        tracker = ent_reg.async_get_or_create(
            "device_tracker",
            "mobile_app",
            f"tracker_{slug}",
            config_entry=entry,
            suggested_object_id=slug,
        )
        hass.states.async_set(
            person,
            "home",
            {
                "user_id": user,
                "device_trackers": [tracker.entity_id],
                "friendly_name": friendly,
            },
        )


def notification_data(**overrides: Any) -> dict[str, Any]:
    """Return the data of a notification subentry."""
    data: dict[str, Any] = {
        "persons": ["person.felix"],
        "devices": [],
        "title": "Frühschicht morgen",
        "message": "Kaffee kochen?",
        "confirm_text": "Ja",
        "buttons": ["Nein"],
        "icon": "mdi:coffee",
        "resend_on_dismiss": True,
        "expire_minutes": 0,
    }
    data.update(overrides)
    return data


def make_entry(
    channels: dict[str, dict[str, Any]] | None = None, **overrides: Any
) -> MockConfigEntry:
    """Return a Pinned Push entry with one notification (and channels)."""
    subentries = [
        ConfigSubentryData(
            data=notification_data(**overrides),
            subentry_id="sub1",
            subentry_type="notification",
            title="Frühschicht",
            unique_id=None,
        )
    ]
    for channel_id, data in (channels or {}).items():
        subentries.append(
            ConfigSubentryData(
                data=data,
                subentry_id=channel_id,
                subentry_type="channel",
                title=data["channel_name"],
                unique_id=None,
            )
        )
    return MockConfigEntry(
        domain=DOMAIN, title="Pinned Push", data={}, subentries_data=subentries
    )


@pytest.fixture
async def entry(hass: HomeAssistant, phones: None) -> MockConfigEntry:
    """Set up Pinned Push with one notification."""
    config_entry = make_entry()
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


def flow_input(
    name: str = "Frühschicht",
    buttons: list[tuple[str, str, str]] | None = None,
    appearance: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Return user input for the notification form (0.3 layout)."""
    if buttons is None:
        buttons = [("Ja", "answer", ""), ("Nein", "answer", "")]
    data: dict[str, Any] = {
        "name": name,
        "persons": ["person.felix"],
        "devices": [],
        "title": "Frühschicht morgen",
        "message": "Kaffee kochen?",
        "icon": "mdi:coffee",
        "resend_on_dismiss": True,
        "expire_minutes": 0,
        "appearance": appearance or {},
        "delivery": delivery or {},
    }
    for slot in ("button_1", "button_2", "button_3"):
        data[slot] = {"label": "", "type": "answer", "target": ""}
    for slot, (label, kind, target) in zip(
        ("button_1", "button_2", "button_3"), buttons, strict=False
    ):
        data[slot] = {"label": label, "type": kind, "target": target}
    data.update(overrides)
    return data
