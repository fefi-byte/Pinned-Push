"""Runtime core of Pinned Push.

Keeps the state of every configured notification in storage, so an open
notification is still tracked (answers, re-sends after dismissal, expiry)
after Home Assistant restarts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_PREFIX,
    CONF_BUTTONS,
    CONF_CONFIRM_TEXT,
    CONF_DEVICES,
    CONF_EXPIRE,
    CONF_ICON,
    CONF_MESSAGE,
    CONF_PERSONS,
    CONF_RESEND,
    CONF_TITLE,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_ICON,
    DOMAIN,
    EVENT_ANSWER,
    EVENT_MOBILE_APP_ACTION,
    EVENT_MOBILE_APP_CLEARED,
    EVENT_TYPE_EXPIRED,
    MAX_RESENDS,
    MOBILE_APP_DOMAIN,
    NOTIFY_DOMAIN,
    PERSON_DOMAIN,
    RESEND_DELAY,
    STATUS_ANSWERED,
    STATUS_EXPIRED,
    STATUS_IDLE,
    STATUS_OPEN,
    STORAGE_VERSION,
    SUBENTRY_TYPE_NOTIFICATION,
    TAG_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

type PinnedPushConfigEntry = ConfigEntry[PinnedPushManager]

# Listener signature: (kind, payload). kind is "update" or "event".
type Listener = Callable[[str, dict[str, Any] | None], None]


def event_types_for(config: dict[str, Any]) -> list[str]:
    """Return the event types of a notification: its button titles plus expired."""
    return [
        config.get(CONF_CONFIRM_TEXT) or DEFAULT_CONFIRM_TEXT,
        *config.get(CONF_BUTTONS, []),
        EVENT_TYPE_EXPIRED,
    ]


def tag_for(subentry_id: str) -> str:
    """Return the Companion App tag of a notification."""
    return f"{TAG_PREFIX}{subentry_id}"


def action_id_for(subentry_id: str, index: int) -> str:
    """Return the action id of a button."""
    return f"{ACTION_PREFIX}|{subentry_id}|{index}"


def _empty_state() -> dict[str, Any]:
    return {
        "status": STATUS_IDLE,
        "sent_at": None,
        "expires_at": None,
        "targets": [],
        "title": None,
        "message": None,
        "actions": [],
        "icon": None,
        "answer": None,
        "resends": 0,
    }


@dataclass
class Resolution:
    """Result of resolving recipients to notify services."""

    services: list[str]
    problems: list[str]


class PinnedPushManager:
    """Track and drive all notifications of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: PinnedPushConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.states: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, list[Listener]] = {}
        self._expiry_unsub: dict[str, CALLBACK_TYPE] = {}
        self._resend_unsub: dict[str, list[CALLBACK_TYPE]] = {}

    # ------------------------------------------------------------------
    # Lifecycle

    async def async_setup(self) -> None:
        """Load state, listen to the Companion App and re-arm timers."""
        stored = await self._store.async_load() or {}
        notifications = self._notification_subentries()
        for subentry_id in notifications:
            state = _empty_state()
            state.update(stored.get("notifications", {}).get(subentry_id, {}))
            self.states[subentry_id] = state

        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, self._on_action)
        )
        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_MOBILE_APP_CLEARED, self._on_cleared)
        )

        now = dt_util.utcnow()
        for subentry_id, state in self.states.items():
            if state["status"] != STATUS_OPEN or not state["expires_at"]:
                continue
            expires_at = dt_util.parse_datetime(state["expires_at"])
            if expires_at is None or expires_at <= now:
                # Expired while Home Assistant was down
                self.hass.async_create_task(self._async_expire(subentry_id))
            else:
                self._schedule_expiry(subentry_id, expires_at)

        # Drop state of removed notifications
        self._async_save()

    async def async_unload(self) -> None:
        """Cancel timers and flush state."""
        for unsub in self._expiry_unsub.values():
            unsub()
        self._expiry_unsub.clear()
        for unsubs in self._resend_unsub.values():
            for unsub in unsubs:
                unsub()
        self._resend_unsub.clear()
        await self._store.async_save(self._data_to_store())

    def _notification_subentries(self) -> dict[str, ConfigSubentry]:
        return {
            sid: sub
            for sid, sub in self.entry.subentries.items()
            if sub.subentry_type == SUBENTRY_TYPE_NOTIFICATION
        }

    def config(self, subentry_id: str) -> dict[str, Any]:
        """Return the configuration of a notification."""
        return dict(self.entry.subentries[subentry_id].data)

    def title(self, subentry_id: str) -> str:
        """Return the name of a notification."""
        return self.entry.subentries[subentry_id].title

    # ------------------------------------------------------------------
    # Listeners (entities)

    @callback
    def async_add_listener(self, subentry_id: str, listener: Listener) -> CALLBACK_TYPE:
        """Subscribe to changes of one notification."""
        self._listeners.setdefault(subentry_id, []).append(listener)

        @callback
        def _remove() -> None:
            self._listeners[subentry_id].remove(listener)

        return _remove

    @callback
    def _notify(
        self,
        subentry_id: str,
        kind: str = "update",
        payload: dict[str, Any] | None = None,
    ) -> None:
        for listener in list(self._listeners.get(subentry_id, [])):
            listener(kind, payload)

    # ------------------------------------------------------------------
    # Storage

    def _data_to_store(self) -> dict[str, Any]:
        return {"notifications": self.states}

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(self._data_to_store, 1)

    # ------------------------------------------------------------------
    # Recipients

    def _service_for_mobile_entry(self, entry_id: str | None) -> str | None:
        if entry_id is None:
            return None
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != MOBILE_APP_DOMAIN:
            return None
        device_name = entry.data.get("device_name")
        if not device_name:
            return None
        service = f"mobile_app_{slugify(device_name)}"
        if not self.hass.services.has_service(NOTIFY_DOMAIN, service):
            return None
        return service

    def _services_for_person(self, person_id: str) -> list[str]:
        state = self.hass.states.get(person_id)
        if state is None:
            return []
        services: list[str] = []
        ent_reg = er.async_get(self.hass)
        # Preferred: the phones selected as trackers of this person
        for tracker in state.attributes.get("device_trackers") or []:
            entity = ent_reg.async_get(tracker)
            if entity is None or entity.platform != MOBILE_APP_DOMAIN:
                continue
            if service := self._service_for_mobile_entry(entity.config_entry_id):
                services.append(service)
        if services:
            return services
        # Fallback: every Companion App registered by this person's user
        user_id = state.attributes.get("user_id")
        if not user_id:
            return []
        for entry in self.hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
            if entry.data.get("user_id") == user_id:
                if service := self._service_for_mobile_entry(entry.entry_id):
                    services.append(service)
        return services

    def resolve(self, persons: list[str], devices: list[str]) -> Resolution:
        """Map persons and mobile app devices to notify services."""
        services: list[str] = []
        problems: list[str] = []
        for person_id in persons:
            found = self._services_for_person(person_id)
            if not found:
                state = self.hass.states.get(person_id)
                problems.append(state.name if state else person_id)
            services.extend(found)
        dev_reg = dr.async_get(self.hass)
        for device_id in devices:
            device = dev_reg.async_get(device_id)
            found = []
            if device is not None:
                for entry_id in device.config_entries:
                    if service := self._service_for_mobile_entry(entry_id):
                        found.append(service)
            if not found:
                problems.append(
                    (device.name_by_user or device.name or device_id)
                    if device
                    else device_id
                )
            services.extend(found)
        return Resolution(list(dict.fromkeys(services)), problems)

    def _person_for_user(self, user_id: str | None) -> tuple[str | None, str | None]:
        if not user_id:
            return None, None
        for state in self.hass.states.async_all(PERSON_DOMAIN):
            if state.attributes.get("user_id") == user_id:
                return state.entity_id, state.name
        return None, None

    def _services_for_sender(self, event: Event, targets: list[str]) -> list[str]:
        """Find the phone that sent an event, limited to the current targets."""
        webhook_id = event.data.get("webhook_id")
        if webhook_id:
            for entry in self.hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
                if entry.data.get("webhook_id") == webhook_id:
                    service = self._service_for_mobile_entry(entry.entry_id)
                    if service in targets:
                        return [service]
        person_id, _ = self._person_for_user(event.context.user_id)
        if person_id:
            found = [s for s in self._services_for_person(person_id) if s in targets]
            if found:
                return found
        return list(targets)

    @callback
    def _update_issue(self, subentry_id: str, problems: list[str]) -> None:
        issue_id = f"missing_recipients_{subentry_id}"
        if problems:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_recipients",
                translation_placeholders={
                    "notification": self.title(subentry_id),
                    "recipients": ", ".join(problems),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # ------------------------------------------------------------------
    # Talking to the Companion App

    def _payload(self, subentry_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": state["title"],
            "message": state["message"],
            "data": {
                "tag": tag_for(subentry_id),
                "persistent": True,
                "sticky": "true",
                "alert_once": True,
                "notification_icon": state["icon"] or DEFAULT_ICON,
                "actions": state["actions"],
            },
        }

    async def _push(
        self, subentry_id: str, state: dict[str, Any], services: list[str]
    ) -> list[str]:
        """Send the notification, return the services that failed."""
        payload = self._payload(subentry_id, state)
        failed: list[str] = []
        for service in services:
            try:
                await self.hass.services.async_call(
                    NOTIFY_DOMAIN, service, payload, blocking=True
                )
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "Sending %s via notify.%s failed: %s",
                    self.title(subentry_id),
                    service,
                    err,
                )
                failed.append(service)
        return failed

    async def _clear(self, subentry_id: str, services: list[str]) -> None:
        for service in services:
            try:
                await self.hass.services.async_call(
                    NOTIFY_DOMAIN,
                    service,
                    {
                        "message": "clear_notification",
                        "data": {"tag": tag_for(subentry_id)},
                    },
                    blocking=True,
                )
            except HomeAssistantError as err:
                _LOGGER.debug("Clearing via notify.%s failed: %s", service, err)

    # ------------------------------------------------------------------
    # Timers

    @callback
    def _cancel_timers(self, subentry_id: str) -> None:
        if unsub := self._expiry_unsub.pop(subentry_id, None):
            unsub()
        for unsub in self._resend_unsub.pop(subentry_id, []):
            unsub()

    @callback
    def _schedule_expiry(self, subentry_id: str, when: datetime) -> None:
        @callback
        def _fire(_now: datetime) -> None:
            self._expiry_unsub.pop(subentry_id, None)
            self.hass.async_create_task(self._async_expire(subentry_id))

        self._expiry_unsub[subentry_id] = async_track_point_in_utc_time(
            self.hass, _fire, when
        )

    # ------------------------------------------------------------------
    # Public operations

    async def async_send(
        self,
        subentry_id: str,
        *,
        title: str | None = None,
        message: str | None = None,
        persons: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send (or replace) a notification."""
        config = self.config(subentry_id)
        resolution = self.resolve(
            persons if persons is not None else config.get(CONF_PERSONS, []),
            [] if persons is not None else config.get(CONF_DEVICES, []),
        )
        self._update_issue(subentry_id, resolution.problems)
        if not resolution.services:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_recipients",
                translation_placeholders={"notification": self.title(subentry_id)},
            )

        old = self.states.get(subentry_id, _empty_state())
        self._cancel_timers(subentry_id)
        if old["status"] == STATUS_OPEN:
            # Remove it from phones that are no longer addressed
            stale = [s for s in old["targets"] if s not in resolution.services]
            await self._clear(subentry_id, stale)

        titles = [config.get(CONF_CONFIRM_TEXT) or DEFAULT_CONFIRM_TEXT]
        titles.extend(config.get(CONF_BUTTONS, []))
        now = dt_util.utcnow()
        expire = int(config.get(CONF_EXPIRE) or 0)
        expires_at = now + timedelta(minutes=expire) if expire > 0 else None

        state = _empty_state()
        state.update(
            {
                "status": STATUS_OPEN,
                "sent_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "targets": resolution.services,
                "title": title if title is not None else config.get(CONF_TITLE),
                "message": message if message is not None else config.get(CONF_MESSAGE),
                "icon": config.get(CONF_ICON) or DEFAULT_ICON,
                "actions": [
                    {"action": action_id_for(subentry_id, i), "title": t}
                    for i, t in enumerate(titles)
                ],
            }
        )
        self.states[subentry_id] = state

        failed = await self._push(subentry_id, state, resolution.services)
        if len(failed) == len(resolution.services):
            state["status"] = STATUS_IDLE
            self._async_save()
            self._notify(subentry_id)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_failed",
                translation_placeholders={
                    "notification": self.title(subentry_id),
                    "services": ", ".join(f"notify.{s}" for s in failed),
                },
            )

        if expires_at:
            self._schedule_expiry(subentry_id, expires_at)
        self._async_save()
        self._notify(subentry_id)
        return {
            "tag": tag_for(subentry_id),
            "sent_to": [f"notify.{s}" for s in resolution.services if s not in failed],
            "failed": [f"notify.{s}" for s in failed],
            "expires_at": state["expires_at"],
        }

    async def async_dismiss(self, subentry_id: str) -> None:
        """Remove a notification from all phones without an answer."""
        state = self.states.get(subentry_id)
        if state is None or state["status"] != STATUS_OPEN:
            return
        self._cancel_timers(subentry_id)
        state["status"] = STATUS_IDLE
        state["expires_at"] = None
        await self._clear(subentry_id, state["targets"])
        self._async_save()
        self._notify(subentry_id)

    # ------------------------------------------------------------------
    # Event handling

    @callback
    def _subentry_from_action(self, action: str) -> tuple[str, int] | None:
        parts = action.split("|")
        if len(parts) != 3 or parts[0] != ACTION_PREFIX:
            return None
        subentry_id, index = parts[1], parts[2]
        if subentry_id not in self.states or not index.isdigit():
            return None
        return subentry_id, int(index)

    @callback
    def _on_action(self, event: Event) -> None:
        action = event.data.get("action")
        if not isinstance(action, str):
            return
        if (parsed := self._subentry_from_action(action)) is None:
            return
        self.hass.async_create_task(self._async_answer(*parsed, event))

    async def _async_answer(self, subentry_id: str, index: int, event: Event) -> None:
        state = self.states[subentry_id]
        if state["status"] != STATUS_OPEN:
            # Late press on a stale notification: just remove it there
            await self._clear(
                subentry_id, self._services_for_sender(event, state["targets"])
            )
            return
        config = self.config(subentry_id)
        event_types = event_types_for(config)
        if index >= len(event_types) - 1:
            return
        button = event_types[index]
        person_id, person_name = self._person_for_user(event.context.user_id)

        self._cancel_timers(subentry_id)
        state["status"] = STATUS_ANSWERED
        state["answer"] = {
            "button": button,
            "button_index": index,
            "confirmed": index == 0,
            "person": person_id,
            "person_name": person_name,
            "at": dt_util.utcnow().isoformat(),
        }
        state["expires_at"] = None
        await self._clear(subentry_id, state["targets"])
        self._async_save()
        self._fire(subentry_id, button, state["answer"])

    @callback
    def _on_cleared(self, event: Event) -> None:
        tag = event.data.get("tag")
        if not isinstance(tag, str) or not tag.startswith(TAG_PREFIX):
            return
        subentry_id = tag.removeprefix(TAG_PREFIX)
        state = self.states.get(subentry_id)
        if state is None or state["status"] != STATUS_OPEN:
            return
        if not self.config(subentry_id).get(CONF_RESEND, True):
            return
        if state["resends"] >= MAX_RESENDS:
            _LOGGER.warning(
                "%s was dismissed %s times, not showing it again",
                self.title(subentry_id),
                MAX_RESENDS,
            )
            return
        services = self._services_for_sender(event, state["targets"])

        @callback
        def _resend(_now: datetime) -> None:
            self.hass.async_create_task(self._async_resend(subentry_id, services))

        self._resend_unsub.setdefault(subentry_id, []).append(
            async_call_later(self.hass, RESEND_DELAY, _resend)
        )

    async def _async_resend(self, subentry_id: str, services: list[str]) -> None:
        state = self.states.get(subentry_id)
        if state is None or state["status"] != STATUS_OPEN:
            return
        state["resends"] += 1
        await self._push(subentry_id, state, services)
        self._async_save()

    async def _async_expire(self, subentry_id: str) -> None:
        state = self.states.get(subentry_id)
        if state is None or state["status"] != STATUS_OPEN:
            return
        self._cancel_timers(subentry_id)
        state["status"] = STATUS_EXPIRED
        state["expires_at"] = None
        await self._clear(subentry_id, state["targets"])
        self._async_save()
        self._fire(
            subentry_id,
            EVENT_TYPE_EXPIRED,
            {
                "button": None,
                "button_index": None,
                "confirmed": False,
                "person": None,
                "person_name": None,
                "at": dt_util.utcnow().isoformat(),
            },
        )

    @callback
    def _fire(self, subentry_id: str, event_type: str, answer: dict[str, Any]) -> None:
        self._notify(subentry_id, "event", {"event_type": event_type, **answer})
        self._notify(subentry_id)
        self.hass.bus.async_fire(
            EVENT_ANSWER,
            {
                "notification": self.title(subentry_id),
                "subentry_id": subentry_id,
                "event_type": event_type,
                **answer,
            },
        )
