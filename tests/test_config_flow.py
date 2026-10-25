"""Tests for the config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pinned_push.const import DOMAIN

from .conftest import flow_input


async def test_user_flow(hass: HomeAssistant) -> None:
    """The integration is set up with one click."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pinned Push"


async def test_add_notification(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A notification is added as a subentry and gets its entities."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        flow_input(
            name=" Müll ",
            buttons=[
                ("Erledigt", "answer", ""),
                ("Morgen erinnern", "answer_keep_open", ""),
                ("Kalender", "open", " /lovelace/kalender "),
            ],
            expire_minutes=30.0,
            appearance={
                "color": [255, 128, 0],
                "visibility": "public",
                "group": " Haus ",
            },
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Müll"
    data = result["data"]
    assert data["button_list"] == [
        {"label": "Erledigt", "type": "answer", "target": ""},
        {"label": "Morgen erinnern", "type": "answer_keep_open", "target": ""},
        {"label": "Kalender", "type": "open", "target": "/lovelace/kalender"},
    ]
    assert data["expire_minutes"] == 30
    assert data["color"] == [255, 128, 0]
    assert data["visibility"] == "public"
    assert data["group"] == "Haus"
    assert data["channel_ref"] == "default"
    await hass.async_block_till_done()

    event = hass.states.get("event.mull")
    # The page button is no answer, so no event type
    assert event.attributes["event_types"] == ["Erledigt", "Morgen erinnern", "expired"]
    assert hass.states.get("sensor.mull_status") is not None


async def test_add_notification_errors(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Invalid input is rejected with errors."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    for kwargs, field, error in (
        ({"persons": []}, "base", "no_recipients"),
        ({"buttons": [("", "answer", "")]}, "button_1", "empty_button"),
        (
            {"buttons": [("Ja", "answer", ""), ("ja", "answer", "")]},
            "base",
            "duplicate_buttons",
        ),
        (
            {"buttons": [("Ja", "answer", ""), ("Expired", "answer", "")]},
            "base",
            "reserved_button",
        ),
        (
            {"buttons": [("Ja", "answer", ""), ("Karte", "open", "")]},
            "button_2",
            "missing_target",
        ),
        ({"buttons": [("Karte", "open", "/map")]}, "button_1", "first_button_answers"),
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], flow_input(**kwargs)
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {field: error}


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """An 0.2 notification opens in the new layout and is saved in it."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "sub1"},
    )
    assert result["type"] is FlowResultType.FORM
    # The old confirm_text/buttons are shown as button 1 and 2
    schema = result["data_schema"].schema

    def suggested(slot: str) -> dict:
        inner = next(v for k, v in schema.items() if str(k) == slot).schema.schema
        return {str(k): (k.description or {}).get("suggested_value") for k in inner}

    assert suggested("button_1") == {
        "label": "Ja",
        "type": "answer",
        "target": "",
        "minutes": 10,
    }
    assert suggested("button_2") == {
        "label": "Nein",
        "type": "answer",
        "target": "",
        "minutes": 10,
    }

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        flow_input(
            buttons=[
                ("Ja", "answer", ""),
                ("Nein", "answer", ""),
                ("Später", "answer", ""),
            ]
        ),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    state = hass.states.get("event.fruhschicht")
    assert state.attributes["event_types"] == ["Ja", "Nein", "Später", "expired"]


async def test_add_channel(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A channel is added and offered to notifications."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"channel_name": "Wecker", "importance": "high", "vibration": "1,2,x"},
    )
    assert result["errors"] == {"vibration": "invalid_vibration"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel_name": "alarm_stream", "importance": "high"}
    )
    assert result["errors"] == {"channel_name": "reserved_channel"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "channel_name": "Haus wichtig",
            "importance": "max",
            "vibration": "0,500, 250 ,500",
            "led_color": [255, 0, 0],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haus wichtig"
    assert result["data"]["vibration"] == "0, 500, 250, 500"
    await hass.async_block_till_done()

    # Duplicate names are rejected
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel_name": "haus WICHTIG", "importance": "high"}
    )
    assert result["errors"] == {"channel_name": "duplicate_channel"}

    # The channel shows up in the notification form
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    delivery = next(
        v for k, v in result["data_schema"].schema.items() if str(k) == "delivery"
    )
    options = next(
        v for k, v in delivery.schema.schema.items() if str(k) == "channel_ref"
    ).config["options"]
    assert [o["label"] for o in options][2:] == ["Haus wichtig"]


async def test_single_instance(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Only one Pinned Push entry is allowed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
