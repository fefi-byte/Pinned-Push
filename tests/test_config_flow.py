"""Tests for the config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pinned_push.const import DOMAIN

from .conftest import button_input, flow_input, run_notification_flow


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
    """Main form with button 1, then buttons are added one by one."""
    result = await run_notification_flow(
        hass,
        entry.entry_id,
        flow_input(
            name=" Müll ",
            first=("Erledigt", "answer"),
            expire_minutes=30.0,
            appearance={
                "color": [255, 128, 0],
                "visibility": "public",
                "group": " Haus ",
            },
        ),
        [
            button_input("Morgen erinnern", "answer_keep_open"),
            button_input("Kalender", "open", " /lovelace/kalender "),
        ],
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
    assert event.attributes["event_types"] == ["Erledigt", "Morgen erinnern", "expired"]
    assert hass.states.get("sensor.mull_status") is not None


async def test_only_first_button(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A notification with just the mandatory button."""
    result = await run_notification_flow(
        hass, entry.entry_id, flow_input(name="Nur OK", first=("OK", "answer"))
    )
    assert result["data"]["button_list"] == [
        {"label": "OK", "type": "answer", "target": ""}
    ]


async def test_menu_options(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The menu offers adding until three buttons exist, editing the extra ones."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], flow_input()
    )
    assert result["menu_options"] == ["add_button", "finish"]
    for label in ("Nein", "Später"):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"next_step_id": "add_button"}
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], button_input(label)
        )
    assert result["menu_options"] == ["edit_button_2", "edit_button_3", "finish"]
    assert result["description_placeholders"]["buttons"] == "Ja, Nein, Später"

    # Edit button 2, then remove button 3
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit_button_2"}
    )
    assert result["step_id"] == "edit_button_2"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], button_input("Nein danke", remove=False)
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "edit_button_3"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], button_input("Später", remove=True)
    )
    assert result["menu_options"] == ["add_button", "edit_button_2", "finish"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert [b["label"] for b in result["data"]["button_list"]] == ["Ja", "Nein danke"]


async def test_add_notification_errors(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Invalid input is rejected with errors."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    for kwargs, field, error in (
        ({"persons": []}, "base", "no_recipients"),
        ({"first": ("", "answer")}, "button_1", "empty_button"),
        ({"first": ("Expired", "answer")}, "base", "reserved_button"),
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], flow_input(**kwargs)
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {field: error}

    # Button 1 cannot be a page or snooze button: not offered at all
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], flow_input(first=("Karte", "open"))
        )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], flow_input()
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_button"}
    )
    for button, field, error in (
        (button_input(""), "label", "empty_label"),
        (button_input("ja"), "base", "duplicate_buttons"),
        (button_input("expired"), "base", "reserved_button"),
        (button_input("Karte", "open"), "target", "missing_target"),
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], button
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {field: error}


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """An 0.2 notification opens with its buttons and is saved in the new format."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "sub1"},
    )
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    inner = next(v for k, v in schema.items() if str(k) == "button_1").schema.schema
    assert {str(k): (k.description or {}).get("suggested_value") for k in inner} == {
        "label": "Ja",
        "type": "answer",
    }

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], flow_input()
    )
    # The old second button is there to edit
    assert result["menu_options"] == ["add_button", "edit_button_2", "finish"]
    assert result["description_placeholders"]["button_2"] == "Nein"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "add_button"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], button_input("Später", "snooze", minutes=20)
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    state = hass.states.get("event.fruhschicht")
    assert state.attributes["event_types"] == ["Ja", "Nein", "Später", "expired"]
    assert entry.subentries["sub1"].data["button_list"][2] == {
        "label": "Später",
        "type": "snooze",
        "target": "",
        "minutes": 20,
    }


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
