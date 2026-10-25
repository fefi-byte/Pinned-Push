"""Tests for the config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pinned_push.const import DOMAIN

from .conftest import notification_data


async def test_user_flow(hass: HomeAssistant) -> None:
    """The integration is set up with one click."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pinned Push"


def _input(**overrides):
    data = {"name": "Frühschicht", **notification_data()}
    data.update(overrides)
    return data


async def test_add_notification(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A notification is added as a subentry and gets its entities."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        _input(name=" Müll ", buttons=["Morgen", " "], expire_minutes=30.0),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Müll"
    assert result["data"]["buttons"] == ["Morgen"]
    assert result["data"]["expire_minutes"] == 30
    await hass.async_block_till_done()

    assert hass.states.get("event.mull") is not None
    assert hass.states.get("sensor.mull_status") is not None


async def test_add_notification_errors(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Invalid input is rejected with errors."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    for overrides, field, error in (
        ({"persons": [], "devices": []}, "base", "no_recipients"),
        ({"buttons": ["A", "B", "C"]}, "buttons", "too_many_buttons"),
        ({"buttons": ["ja"]}, "buttons", "duplicate_buttons"),
        ({"buttons": ["Expired"]}, "buttons", "reserved_button"),
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], _input(**overrides)
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {field: error}


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Changing a notification updates its event types after the reload."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "sub1"},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _input(buttons=["Nein", "Später"])
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    state = hass.states.get("event.fruhschicht")
    assert state.attributes["event_types"] == ["Ja", "Nein", "Später", "expired"]


async def test_single_instance(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Only one Pinned Push entry is allowed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
