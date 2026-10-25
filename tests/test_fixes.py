"""Tests for the 0.2 fixes: renamed buttons, cleanup, delivery, stale answers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.pinned_push.const import DOMAIN

from .conftest import USER_A, USER_B, WEBHOOK_A, make_entry, notification_data
from .test_notifications import (
    EVENT_ID,
    SENSOR_ID,
    _clears,
    _press,
    _pushes,
    _send,
    _swipe,
)


def _automation(event_type: str) -> dict:
    return {
        "automation": {
            "id": "coffee",
            "alias": "Kaffee",
            # Classic form, works on every supported version
            "triggers": {"trigger": "state", "entity_id": EVENT_ID},
            "conditions": {
                "condition": "state",
                "entity_id": EVENT_ID,
                "attribute": "event_type",
                "state": event_type,
            },
            "actions": {"action": "test.coffee"},
        }
    }


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, **data) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "sub1"},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Frühschicht", **notification_data(**data)}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()


async def test_renamed_button_issue(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Renaming a button an automation uses raises an issue until it is fixed."""
    assert await async_setup_component(hass, "automation", _automation("Nein"))
    await hass.async_block_till_done()
    issues = ir.async_get(hass)

    await _reconfigure(hass, entry, buttons=["Später"])
    issue = issues.async_get_issue(DOMAIN, "renamed_buttons_sub1")
    assert issue is not None
    assert issue.translation_placeholders["labels"] == "Nein"
    assert issue.translation_placeholders["current"] == "Ja, Später"
    assert issue.translation_placeholders["automations"] == "Kaffee"

    # The user fixes the automation: the issue goes away on reload
    with patch(
        "homeassistant.config.load_yaml_config_file",
        return_value=_automation("Später"),
    ):
        await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, "renamed_buttons_sub1") is None


async def test_renamed_button_unused(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Renaming a button nobody uses raises no issue."""
    assert await async_setup_component(hass, "automation", _automation("Ja"))
    await hass.async_block_till_done()
    await _reconfigure(hass, entry, buttons=["Später"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, "renamed_buttons_sub1") is None


async def test_removed_notification_cleared(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """Deleting an open notification takes it off the phones."""
    await _send(hass)
    notify_calls.clear()
    assert hass.config_entries.async_remove_subentry(entry, "sub1")
    await hass.async_block_till_done()
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]
    assert hass.states.get(EVENT_ID) is None


async def test_resend_limit_issue(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Hitting the re-send limit raises an issue; the next send clears it."""
    issues = ir.async_get(hass)
    with patch("custom_components.pinned_push.manager.MAX_RESENDS", 1):
        await _send(hass)
        _swipe(hass, USER_A, WEBHOOK_A)
        freezer.tick(timedelta(seconds=3))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(SENSOR_ID).attributes["resends"] == 1
        notify_calls.clear()

        _swipe(hass, USER_A, WEBHOOK_A)
        freezer.tick(timedelta(seconds=3))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert _pushes(notify_calls) == []
        issue = issues.async_get_issue(DOMAIN, "resend_limit_sub1")
        assert issue is not None
        assert issue.translation_placeholders["count"] == "1"

        await _send(hass)
        assert issues.async_get_issue(DOMAIN, "resend_limit_sub1") is None


async def test_delivery_options(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """Channel, importance and urgency end up in the payload."""
    config_entry = make_entry(
        urgent=False, alarm_stream=False, channel="Pinned Push", importance="high"
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)
    data = _pushes(notify_calls)[0].data["data"]
    assert data["channel"] == "Pinned Push"
    assert data["importance"] == "high"
    assert "ttl" not in data
    assert "priority" not in data


async def test_alarm_stream(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """Do-not-disturb mode uses the alarm stream instead of the channel."""
    config_entry = make_entry(alarm_stream=True, channel="Pinned Push")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)
    data = _pushes(notify_calls)[0].data["data"]
    assert data["channel"] == "alarm_stream"
    assert "importance" not in data


async def test_delivery_in_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The delivery section is stored flat; reconfigure shows it again."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notification"), context={"source": "user"}
    )
    data = {"name": "Müll", **notification_data()}
    data["delivery"] = {
        "urgent": False,
        "alarm_stream": True,
        "channel": " Müll ",
        "importance": "max",
    }
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], data
    )
    assert result["data"]["urgent"] is False
    assert result["data"]["alarm_stream"] is True
    assert result["data"]["channel"] == "Müll"
    assert result["data"]["importance"] == "max"


async def test_stale_send_ignored(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """A press on a replaced notification does not count."""
    await _send(hass)
    await _send(hass, message="neu")
    assert hass.states.get(SENSOR_ID).attributes["send_id"] == 2
    notify_calls.clear()

    _press(hass, 1, USER_A, WEBHOOK_A, send_id=1)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "open"
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]

    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "answered"
    assert hass.states.get(EVENT_ID).attributes["send_id"] == 2


async def test_legacy_action_id(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Notifications sent by 0.1 (no send id) can still be answered."""
    await _send(hass)
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": "PINNED_PUSH|sub1|1", "webhook_id": WEBHOOK_A},
        context=Context(user_id=USER_A),
    )
    await hass.async_block_till_done()
    assert hass.states.get(EVENT_ID).attributes["event_type"] == "Nein"


async def test_person_from_phone_not_user(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The person is the one tracking the phone, even if logged in as another user."""
    await _send(hass)
    # Phone A belongs to Felix but its app is logged in as Anna's user
    _press(hass, 0, USER_B, WEBHOOK_A)
    await hass.async_block_till_done()
    event = hass.states.get(EVENT_ID)
    assert event.attributes["person"] == "person.felix"
    assert event.attributes["device"] == "Phone A"
