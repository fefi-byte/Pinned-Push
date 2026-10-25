"""Tests for sending, answering, re-sending and expiring notifications."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.pinned_push.const import DOMAIN, EVENT_ANSWER

from .conftest import USER_A, USER_B, WEBHOOK_A, WEBHOOK_B, make_entry

EVENT_ID = "event.fruhschicht"
SENSOR_ID = "sensor.fruhschicht_status"
TAG = "pinned_push_sub1"


def _pushes(calls: list[ServiceCall]) -> list[ServiceCall]:
    return [c for c in calls if c.data.get("message") != "clear_notification"]


def _clears(calls: list[ServiceCall]) -> list[ServiceCall]:
    return [c for c in calls if c.data.get("message") == "clear_notification"]


async def _send(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(
        DOMAIN,
        "send",
        {"entity_id": EVENT_ID, **data},
        blocking=True,
        return_response=True,
    )


def _press(hass: HomeAssistant, index: int, user: str, webhook: str) -> None:
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"PINNED_PUSH|sub1|{index}", "tag": TAG, "webhook_id": webhook},
        context=Context(user_id=user),
    )


def _swipe(hass: HomeAssistant, user: str, webhook: str) -> None:
    hass.bus.async_fire(
        "mobile_app_notification_cleared",
        {"tag": TAG, "webhook_id": webhook},
        context=Context(user_id=user),
    )


async def test_entities_created(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """One event entity and one status sensor per notification."""
    event = hass.states.get(EVENT_ID)
    assert event is not None
    assert event.attributes["event_types"] == ["Ja", "Nein", "expired"]
    assert event.attributes["friendly_name"] == "Frühschicht"
    assert hass.states.get(SENSOR_ID).state == "idle"


async def test_send_and_answer(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """Sending pins the push, a button press answers and clears it."""
    answers = []
    hass.bus.async_listen(EVENT_ANSWER, answers.append)

    response = await _send(hass, message="Schicht um 06:00")
    assert response["notifications"][EVENT_ID]["sent_to"] == [
        "notify.mobile_app_phone_a"
    ]
    pushes = _pushes(notify_calls)
    assert len(pushes) == 1
    assert pushes[0].service == "mobile_app_phone_a"
    assert pushes[0].data["title"] == "Frühschicht morgen"
    assert pushes[0].data["message"] == "Schicht um 06:00"
    payload = pushes[0].data["data"]
    assert payload["tag"] == TAG
    assert payload["persistent"] is True
    assert payload["sticky"] == "true"
    assert payload["notification_icon"] == "mdi:coffee"
    assert payload["actions"] == [
        {"action": "PINNED_PUSH|sub1|0", "title": "Ja"},
        {"action": "PINNED_PUSH|sub1|1", "title": "Nein"},
    ]
    assert hass.states.get(SENSOR_ID).state == "open"

    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()

    event = hass.states.get(EVENT_ID)
    assert event.attributes["event_type"] == "Nein"
    assert event.attributes["person"] == "person.felix"
    assert event.attributes["person_name"] == "Felix"
    assert event.attributes["confirmed"] is False
    assert event.attributes["button_index"] == 1

    sensor = hass.states.get(SENSOR_ID)
    assert sensor.state == "answered"
    assert sensor.attributes["answer"] == "Nein"
    assert sensor.attributes["answered_by"] == "person.felix"

    clears = _clears(notify_calls)
    assert [c.service for c in clears] == ["mobile_app_phone_a"]
    assert clears[0].data["data"]["tag"] == TAG

    assert len(answers) == 1
    assert answers[0].data["event_type"] == "Nein"
    assert answers[0].data["notification"] == "Frühschicht"


async def test_foreign_actions_ignored(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """Actions of other notifications do not touch ours."""
    await _send(hass)
    for action in (
        "FRUEH_JA",
        "PINNED_PUSH|other|0",
        "PINNED_PUSH|sub1|x",
        "PINNED_PUSH|sub1|9",
    ):
        hass.bus.async_fire(
            "mobile_app_notification_action",
            {"action": action},
            context=Context(user_id=USER_A),
        )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "open"


async def test_swipe_resends_to_that_phone_only(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A dismissed push comes back only on the phone that dismissed it."""
    config_entry = make_entry(persons=["person.felix", "person.anna"])
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await _send(hass)
    assert sorted(c.service for c in _pushes(notify_calls)) == [
        "mobile_app_phone_a",
        "mobile_app_phone_b",
    ]
    notify_calls.clear()

    _swipe(hass, USER_B, WEBHOOK_B)
    await hass.async_block_till_done()
    assert notify_calls == []

    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_b"]

    # Anna answers: removed everywhere, person resolved from the user
    notify_calls.clear()
    _press(hass, 0, USER_B, WEBHOOK_B)
    await hass.async_block_till_done()
    event = hass.states.get(EVENT_ID)
    assert event.attributes["event_type"] == "Ja"
    assert event.attributes["person"] == "person.anna"
    assert event.attributes["confirmed"] is True
    assert sorted(c.service for c in _clears(notify_calls)) == [
        "mobile_app_phone_a",
        "mobile_app_phone_b",
    ]


async def test_swipe_after_answer_not_resent(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Clearing a push we cleared ourselves does not bring it back."""
    await _send(hass)
    _swipe(hass, USER_A, WEBHOOK_A)
    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    notify_calls.clear()
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _pushes(notify_calls) == []


async def test_resend_disabled(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without re-send a dismissed push stays gone but still counts as open."""
    config_entry = make_entry(resend_on_dismiss=False)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)
    notify_calls.clear()
    _swipe(hass, USER_A, WEBHOOK_A)
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert notify_calls == []
    assert hass.states.get(SENSOR_ID).state == "open"


async def test_expiry(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """After the expiry time the push is removed and the event says expired."""
    config_entry = make_entry(expire_minutes=5)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)
    assert hass.states.get(SENSOR_ID).attributes["expires_at"] is not None

    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR_ID).state == "expired"
    assert hass.states.get(EVENT_ID).attributes["event_type"] == "expired"
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]

    # A late press does not count, but removes the stale push
    notify_calls.clear()
    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "expired"
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]


async def test_answer_after_reload(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """An open push is still tracked after a reload (same as a restart)."""
    await _send(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "open"

    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ID).state == "answered"
    assert hass.states.get(EVENT_ID).attributes["event_type"] == "Ja"


async def test_expired_while_down(
    hass: HomeAssistant,
    phones: None,
    notify_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A push that expired while Home Assistant was down expires on start."""
    config_entry = make_entry(expire_minutes=5)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    notify_calls.clear()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR_ID).state == "expired"
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]


async def test_dismiss(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """Dismiss removes the push without an answer."""
    await _send(hass)
    await hass.services.async_call(
        DOMAIN, "dismiss", {"entity_id": EVENT_ID}, blocking=True
    )
    assert hass.states.get(SENSOR_ID).state == "idle"
    assert [c.service for c in _clears(notify_calls)] == ["mobile_app_phone_a"]


async def test_missing_phone_raises_issue(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """A person without a Companion App gets a repair issue."""
    hass.states.async_set("person.gast", "home", {"friendly_name": "Gast"})
    config_entry = make_entry(persons=["person.gast"])
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="No phone found for Frühschicht"):
        await _send(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "missing_recipients_sub1")
    assert issue is not None
    assert issue.translation_placeholders["recipients"] == "Gast"


async def test_partial_recipients(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """One missing person does not stop the others; the issue clears later."""
    hass.states.async_set("person.gast", "home", {"friendly_name": "Gast"})
    config_entry = make_entry(persons=["person.felix", "person.gast"])
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await _send(hass)
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_a"]
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "missing_recipients_sub1") is not None

    await _send(hass, persons=["person.felix"])
    assert issues.async_get_issue(DOMAIN, "missing_recipients_sub1") is None


async def test_user_fallback_without_tracker(
    hass: HomeAssistant, phones: None, notify_calls: list[ServiceCall]
) -> None:
    """Without a tracked phone, the phones of the person's user are used."""
    hass.states.async_set(
        "person.felix", "home", {"user_id": USER_A, "device_trackers": []}
    )
    config_entry = make_entry()
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _send(hass)
    assert [c.service for c in _pushes(notify_calls)] == ["mobile_app_phone_a"]


async def test_send_unknown_entity(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Sending to an entity of another integration is rejected."""
    hass.states.async_set("event.other", "unknown")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "send", {"entity_id": "event.other"}, blocking=True
        )


async def test_event_received_trigger(
    hass: HomeAssistant, entry: MockConfigEntry, notify_calls: list[ServiceCall]
) -> None:
    """The built-in event.received trigger picks the button by its label."""
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import async_mock_service

    calls = async_mock_service(hass, "test", "automation")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "triggers": {
                    "trigger": "event.received",
                    "target": {"entity_id": EVENT_ID},
                    "options": {"event_type": ["Nein"]},
                },
                "actions": {
                    "action": "test.automation",
                    "data": {"who": "{{ trigger.to_state.attributes.person }}"},
                },
            }
        },
    )
    await _send(hass)
    _press(hass, 0, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert calls == []

    await _send(hass)
    _press(hass, 1, USER_A, WEBHOOK_A)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["who"] == "person.felix"
