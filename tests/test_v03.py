"""Tests for 0.3: button types, appearance and managed channels."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import USER_A, WEBHOOK_A, make_entry
from .test_notifications import (
    EVENT_ID,
    SENSOR_ID,
    _clears,
    _press,
    _pushes,
    _send,
)

BUTTONS = [
    {"label": "Erledigt", "type": "answer", "target": ""},
    {"label": "Später", "type": "answer_keep_open", "target": ""},
    {"label": "Kalender", "type": "open", "target": "/lovelace/kalender"},
]

CHANNEL = {
    "channel_name": "Haus wichtig",
    "importance": "high",
    "vibration": "0, 500",
    "led_color": [255, 0, 0],
}


async def _setup(hass: HomeAssistant, **kwargs) -> MockConfigEntry:
    entry = make_entry(**kwargs)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_button_types(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """Answer, keep-open and open-page buttons behave differently."""
    await _setup(hass, button_list=BUTTONS)
    assert hass.states.get(EVENT_ID).attributes["event_types"] == [
        "Erledigt",
        "Später",
        "expired",
    ]
    await _send(hass)
    actions = _pushes(notify_calls)[0].data["data"]["actions"]
    assert actions == [
        {"action": "PINNED_PUSH|sub1|1|0", "title": "Erledigt"},
        {"action": "PINNED_PUSH|sub1|1|1", "title": "Später"},
        {"action": "URI", "title": "Kalender", "uri": "/lovelace/kalender"},
    ]
    notify_calls.clear()

    # Keep-open: reported, still open, shown again on that phone
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    event = hass.states.get(EVENT_ID)
    assert event.attributes["event_type"] == "Später"
    assert event.attributes["closes"] is False
    assert hass.states.get(SENSOR_ID).state == "open"
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_a"]
    assert _clears(notify_calls) == []

    # Opening the page sends action "URI", which is no answer
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "URI", "tag": "pinned_push_sub1", "webhook_id": WEBHOOK_A},
        context=Context(user_id=USER_A),
    )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "open"

    # A real answer still closes it
    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "answered"
    assert hass.states.get(EVENT_ID).attributes["closes"] is True


async def test_appearance(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Color, picture, tap target, lock screen, countdown and group."""
    await _setup(
        hass,
        expire_minutes=10,
        color=[255, 128, 0],
        camera="camera.tuer",
        image="/local/ignored.png",
        click_action="/lovelace/kameras",
        visibility="secret",
        countdown=True,
        group="Haus",
    )
    now = dt_util.utcnow()
    await _send(hass)
    data = _pushes(notify_calls)[0].data["data"]
    assert data["color"] == "#ff8000"
    assert data["image"] == "/api/camera_proxy/camera.tuer"
    assert data["clickAction"] == "/lovelace/kameras"
    assert data["visibility"] == "secret"
    assert data["chronometer"] is True
    assert abs(data["when"] - (now + timedelta(minutes=10)).timestamp()) < 2
    assert data["group"] == "Haus"
    notify_calls.clear()

    # Per-send overrides, kept for re-sends
    await _send(hass, image="/media/local/x.jpg", click_action="entityId:sun.sun")
    data = _pushes(notify_calls)[0].data["data"]
    assert data["image"] == "/media/local/x.jpg"
    assert data["clickAction"] == "entityId:sun.sun"


async def test_default_appearance_adds_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """Without options none of the appearance keys are sent."""
    await _send(hass)
    data = _pushes(notify_calls)[0].data["data"]
    for key in ("color", "image", "clickAction", "visibility", "chronometer", "group"):
        assert key not in data


async def test_managed_channel(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """A managed channel is sent with its settings and recreated on change."""
    entry = await _setup(hass, channel_ref="ch1", channels={"ch1": CHANNEL})
    await _send(hass)
    data = _pushes(notify_calls)[0].data["data"]
    assert data["channel"] == "Haus wichtig"
    assert data["importance"] == "high"
    assert data["vibrationPattern"] == "0, 500"
    assert data["ledColor"] == "#ff0000"
    notify_calls.clear()

    # Changing the importance removes the channel from the phone
    sub: ConfigSubentry = entry.subentries["ch1"]
    hass.config_entries.async_update_subentry(
        entry, sub, data={**CHANNEL, "importance": "max"}
    )
    await hass.async_block_till_done()
    removals = [c for c in notify_calls if c.data.get("message") == "remove_channel"]
    assert [(c.service, c.data["data"]["channel"]) for c in removals] == [
        ("mobile_app_phone_a", "Haus wichtig")
    ]
    notify_calls.clear()

    # Unchanged settings: nothing removed on the next reload
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert notify_calls == []

    # The next send creates it with the new importance
    await _send(hass)
    assert _pushes(notify_calls)[0].data["data"]["importance"] == "max"
    notify_calls.clear()

    # Deleting the channel removes it too; the notification falls back
    assert hass.config_entries.async_remove_subentry(entry, "ch1")
    await hass.async_block_till_done()
    removals = [c for c in notify_calls if c.data.get("message") == "remove_channel"]
    assert [c.data["data"]["channel"] for c in removals] == ["Haus wichtig"]
    notify_calls.clear()
    await _send(hass)
    assert "channel" not in _pushes(notify_calls)[0].data["data"]


async def test_alarm_channel(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """The alarm choice sends the alarm stream channel."""
    await _setup(hass, channel_ref="alarm_stream")
    await _send(hass)
    assert _pushes(notify_calls)[0].data["data"]["channel"] == "alarm_stream"
