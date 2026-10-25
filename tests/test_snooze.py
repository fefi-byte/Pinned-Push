"""Tests for the snooze button: close now, show again after N minutes."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from .conftest import USER_A, WEBHOOK_A, flow_input, make_entry
from .test_notifications import EVENT_ID, SENSOR_ID, _clears, _press, _pushes, _send

BUTTONS = [
    {"label": "Erledigt", "type": "answer", "target": ""},
    {"label": "Später", "type": "snooze", "target": "", "minutes": 15},
]


async def _setup(hass: HomeAssistant, **kwargs) -> MockConfigEntry:
    entry = make_entry(button_list=BUTTONS, **kwargs)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta) -> None:
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_snooze(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Snooze hides the push everywhere and shows it again after the minutes."""
    await _setup(hass)
    await _send(hass, message="Müll raus?")
    notify_calls.clear()

    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    event = hass.states.get(EVENT_ID)
    assert event.attributes["event_type"] == "Später"
    assert event.attributes["closes"] is False
    assert event.attributes["snoozed_until"] is not None
    sensor = hass.states.get(SENSOR_ID)
    assert sensor.state == "snoozed"
    assert sensor.attributes["snoozed_until"] is not None
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]
    notify_calls.clear()

    # Swiping or pressing while snoozed changes nothing
    await _tick(hass, freezer, minutes=14)
    assert _pushes(notify_calls) == []
    assert hass.states.get(SENSOR_ID).state == "snoozed"

    await _tick(hass, freezer, minutes=2)
    pushes = _pushes(notify_calls)
    assert [c.service for c in pushes] == ["mobile_app_phone_a"]
    assert pushes[0].data["message"] == "Müll raus?"
    assert hass.states.get(SENSOR_ID).state == "open"

    # The re-shown push can be answered normally
    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "answered"


async def test_snooze_survives_restart(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A snooze is stored; after a restart the push still comes back."""
    entry = await _setup(hass)
    await _send(hass)
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "snoozed"
    notify_calls.clear()
    await _tick(hass, freezer, minutes=16)
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_a"]
    assert hass.states.get(SENSOR_ID).state == "open"


async def test_snooze_elapsed_while_down(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """If the snooze ran out while Home Assistant was down, it shows at start."""
    entry = await _setup(hass)
    await _send(hass)
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    notify_calls.clear()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_a"]
    assert hass.states.get(SENSOR_ID).state == "open"


async def test_expiry_during_snooze(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Expiry still applies while snoozed; the push does not come back."""
    await _setup(hass, expire_minutes=10)
    await _send(hass)
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    await _tick(hass, freezer, minutes=11)
    assert hass.states.get(SENSOR_ID).state == "expired"
    assert hass.states.get(EVENT_ID).attributes["event_type"] == "expired"
    notify_calls.clear()
    await _tick(hass, freezer, minutes=10)
    assert _pushes(notify_calls) == []


async def test_dismiss_snoozed(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Dismissing a snoozed push cancels the snooze."""
    await _setup(hass)
    await _send(hass)
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "pinned_push", "dismiss", {"entity_id": EVENT_ID}, blocking=True
    )
    assert hass.states.get(SENSOR_ID).state == "idle"
    notify_calls.clear()
    await _tick(hass, freezer, minutes=20)
    assert _pushes(notify_calls) == []


async def test_snooze_in_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The minutes are stored for snooze buttons; button 1 cannot snooze."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        flow_input(name="Müll", buttons=[("Später", "snooze", "", 5)]),
    )
    assert result["errors"] == {"button_1": "first_button_answers"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        flow_input(
            name="Müll",
            buttons=[("Erledigt", "answer", "", 5), ("Später", "snooze", "", 45.0)],
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["button_list"] == [
        {"label": "Erledigt", "type": "answer", "target": ""},
        {"label": "Später", "type": "snooze", "target": "", "minutes": 45},
    ]
