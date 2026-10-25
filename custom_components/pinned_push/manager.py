"""Runtime core of Pinned Push.

Keeps the state of every configured notification in storage, so an open
notification is still tracked (answers, re-sends after dismissal, expiry)
after Home Assistant restarts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
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
    AUTOMATION_DOMAIN,
    CONF_ALARM_STREAM,
    CONF_BUTTONS,
    CONF_CHANNEL,
    CONF_CONFIRM_TEXT,
    CONF_DEVICES,
    CONF_EXPIRE,
    CONF_ICON,
    CONF_IMPORTANCE,
    CONF_MESSAGE,
    CONF_PERSONS,
    CONF_RESEND,
    CONF_TITLE,
    CONF_URGENT,
    DEFAULT_CONFIRM_TEXT,
    DEFAULT_ICON,
    DEFAULT_IMPORTANCE,
    DOMAIN,
    EVENT_ANSWER,
    EVENT_AUTOMATION_RELOADED,
    EVENT_MOBILE_APP_ACTION,
    EVENT_MOBILE_APP_CLEARED,
    EVENT_TYPE_EXPIRED,
    ISSUE_MISSING_RECIPIENTS,
    ISSUE_RENAMED_BUTTONS,
    ISSUE_RESEND_LIMIT,
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


def button_labels_for(config: dict[str, Any]) -> list[str]:
    """Return the button labels of a notification, confirm button first."""
    return [
        config.get(CONF_CONFIRM_TEXT) or DEFAULT_CONFIRM_TEXT,
        *config.get(CONF_BUTTONS, []),
    ]


def event_types_for(config: dict[str, Any]) -> list[str]:
    """Return the event types of a notification: its button labels plus expired."""
    return [*button_labels_for(config), EVENT_TYPE_EXPIRED]


def tag_for(subentry_id: str) -> str:
    """Return the Companion App tag of a notification."""
    return f"{TAG_PREFIX}{subentry_id}"


def action_id_for(subentry_id: str, send_id: int, index: int) -> str:
    """Return the action id of a button of one particular send."""
    return f"{ACTION_PREFIX}|{subentry_id}|{send_id}|{index}"


def _empty_state() -> dict[str, Any]:
    return {
        "status": STATUS_IDLE,
        "send_id": 0,
        "sent_at": None,
        "expires_at": None,
        "targets": [],
        "title": None,
        "message": None,
        "actions": [],
        "icon": None,
        "answer": None,
        "resends": 0,
        # Button labels last seen, and labels removed by a rename that
        # automations may still use
        "labels": None,
        "stale_labels": [],
    }


@dataclass
class Resolution:
    """Result of resolving recipients to notify services."""

    services: list[str]
    problems: list[str]


@dataclass
class Sender:
    """The phone and person behind a Companion App event."""

    service: str | None
    device_name: str | None
    person_id: str | None
    person_name: str | None


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
        stored = (await self._store.async_load() or {}).get("notifications", {})
        notifications = self._notification_subentries()
        for subentry_id in notifications:
            state = _empty_state()
            state.update(stored.get(subentry_id, {}))
            self.states[subentry_id] = state
            self._track_labels(subentry_id)

        # Notifications deleted since the last run: take them off the phones
        for subentry_id, old in stored.items():
            if subentry_id in notifications:
                continue
            for issue in (
                ISSUE_MISSING_RECIPIENTS,
                ISSUE_RENAMED_BUTTONS,
                ISSUE_RESEND_LIMIT,
            ):
                ir.async_delete_issue(self.hass, DOMAIN, f"{issue}_{subentry_id}")
            if old.get("status") == STATUS_OPEN:
                self.entry.async_create_background_task(
                    self.hass,
                    self._clear(subentry_id, old.get("targets", [])),
                    f"{DOMAIN} clear removed {subentry_id}",
                )

        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, self._on_action)
        )
        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_MOBILE_APP_CLEARED, self._on_cleared)
        )
        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                EVENT_AUTOMATION_RELOADED, self._on_automations_changed
            )
        )
        if self.hass.state is CoreState.running:
            self._check_stale_labels()
        else:
            self.entry.async_on_unload(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._on_automations_changed
                )
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
    # Renamed buttons

    @callback
    def _track_labels(self, subentry_id: str) -> None:
        """Remember labels that disappeared from a notification."""
        state = self.states[subentry_id]
        current = button_labels_for(self.config(subentry_id))
        previous = state.get("labels")
        if previous is not None:
            removed = [label for label in previous if label not in current]
            stale = [s for s in state.get("stale_labels", []) if s not in current]
            state["stale_labels"] = list(dict.fromkeys([*stale, *removed]))
        state["labels"] = current

    def _automations_using(
        self, subentry_id: str, labels: list[str]
    ) -> dict[str, list[str]]:
        """Return {automation name: [labels]} for automations still using labels."""
        # Imported here: the automation integration is optional
        from homeassistant.components.automation import (  # noqa: PLC0415
            DATA_COMPONENT,
            automations_with_entity,
        )

        component = self.hass.data.get(DATA_COMPONENT)
        if component is None:
            return {}
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "event", DOMAIN, f"{subentry_id}_answer"
        )
        if entity_id is None:
            return {}
        found: dict[str, list[str]] = {}
        for automation_id in automations_with_entity(self.hass, entity_id):
            automation = component.get_entity(automation_id)
            raw = getattr(automation, "raw_config", None)
            if automation is None or raw is None:
                continue
            text = json.dumps(raw, ensure_ascii=False, default=str)
            used = [
                label
                for label in labels
                if json.dumps(label, ensure_ascii=False) in text
            ]
            if used:
                name = (
                    automation.name
                    if isinstance(automation.name, str)
                    else automation_id
                )
                found[name or automation_id] = used
        return found

    @callback
    def _check_stale_labels(self) -> None:
        if AUTOMATION_DOMAIN not in self.hass.config.components:
            return
        changed = False
        for subentry_id, state in self.states.items():
            issue_id = f"{ISSUE_RENAMED_BUTTONS}_{subentry_id}"
            stale = state.get("stale_labels") or []
            using = self._automations_using(subentry_id, stale) if stale else {}
            still_used = sorted(
                {label for labels in using.values() for label in labels}
            )
            if still_used != stale:
                state["stale_labels"] = still_used
                changed = True
            if using:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_RENAMED_BUTTONS,
                    translation_placeholders={
                        "notification": self.title(subentry_id),
                        "labels": ", ".join(still_used),
                        "current": ", ".join(
                            button_labels_for(self.config(subentry_id))
                        ),
                        "automations": ", ".join(sorted(using)),
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        if changed:
            self._async_save()

    @callback
    def _on_automations_changed(self, _event: Event | None = None) -> None:
        self._check_stale_labels()

    # ------------------------------------------------------------------
    # Recipients

    def _mobile_entry(self, entry_id: str | None) -> ConfigEntry | None:
        if entry_id is None:
            return None
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != MOBILE_APP_DOMAIN:
            return None
        return entry

    def _service_for_mobile_entry(self, entry_id: str | None) -> str | None:
        entry = self._mobile_entry(entry_id)
        if entry is None:
            return None
        device_name = entry.data.get("device_name")
        if not device_name:
            return None
        service = f"mobile_app_{slugify(device_name)}"
        if not self.hass.services.has_service(NOTIFY_DOMAIN, service):
            return None
        return service

    def _mobile_entries_of_person(self, person_id: str) -> list[str]:
        """Return the Companion App config entries a person tracks."""
        state = self.hass.states.get(person_id)
        if state is None:
            return []
        ent_reg = er.async_get(self.hass)
        entries: list[str] = []
        for tracker in state.attributes.get("device_trackers") or []:
            entity = ent_reg.async_get(tracker)
            if (
                entity is not None
                and entity.platform == MOBILE_APP_DOMAIN
                and entity.config_entry_id is not None
            ):
                entries.append(entity.config_entry_id)
        return entries

    def _services_for_person(self, person_id: str) -> list[str]:
        services = [
            service
            for entry_id in self._mobile_entries_of_person(person_id)
            if (service := self._service_for_mobile_entry(entry_id))
        ]
        if services:
            return services
        # Fallback: every Companion App registered by this person's user
        state = self.hass.states.get(person_id)
        user_id = state.attributes.get("user_id") if state else None
        if not user_id:
            return []
        return [
            service
            for entry in self.hass.config_entries.async_entries(MOBILE_APP_DOMAIN)
            if entry.data.get("user_id") == user_id
            and (service := self._service_for_mobile_entry(entry.entry_id))
        ]

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

    def _sender(self, event: Event) -> Sender:
        """Identify the phone and person behind a Companion App event.

        The phone is found by its webhook. The person is the one tracking
        that phone; only if nobody does, the person of the app's user.
        """
        entry: ConfigEntry | None = None
        webhook_id = event.data.get("webhook_id")
        if webhook_id:
            entry = next(
                (
                    e
                    for e in self.hass.config_entries.async_entries(MOBILE_APP_DOMAIN)
                    if e.data.get("webhook_id") == webhook_id
                ),
                None,
            )
        persons = self.hass.states.async_all(PERSON_DOMAIN)
        person = None
        if entry is not None:
            person = next(
                (
                    p
                    for p in persons
                    if entry.entry_id in self._mobile_entries_of_person(p.entity_id)
                ),
                None,
            )
        if person is None and event.context.user_id:
            person = next(
                (
                    p
                    for p in persons
                    if p.attributes.get("user_id") == event.context.user_id
                ),
                None,
            )
        return Sender(
            service=self._service_for_mobile_entry(entry.entry_id) if entry else None,
            device_name=entry.data.get("device_name") if entry else None,
            person_id=person.entity_id if person else None,
            person_name=person.name if person else None,
        )

    def _services_for_sender(self, sender: Sender, targets: list[str]) -> list[str]:
        """Limit an action to the phone that sent an event, if known."""
        if sender.service in targets:
            return [sender.service]
        if sender.person_id:
            found = [
                s for s in self._services_for_person(sender.person_id) if s in targets
            ]
            if found:
                return found
        return list(targets)

    @callback
    def _set_issue(
        self,
        kind: str,
        subentry_id: str,
        placeholders: dict[str, str] | None,
    ) -> None:
        issue_id = f"{kind}_{subentry_id}"
        if placeholders is None:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=kind,
            translation_placeholders={
                "notification": self.title(subentry_id),
                **placeholders,
            },
        )

    # ------------------------------------------------------------------
    # Talking to the Companion App

    def _payload(self, subentry_id: str, state: dict[str, Any]) -> dict[str, Any]:
        config = self.config(subentry_id)
        data: dict[str, Any] = {
            "tag": tag_for(subentry_id),
            "persistent": True,
            "sticky": "true",
            "alert_once": True,
            "notification_icon": state["icon"] or DEFAULT_ICON,
            "actions": state["actions"],
        }
        if config.get(CONF_URGENT, True):
            # Deliver at once, even while the phone is dozing
            data["ttl"] = 0
            data["priority"] = "high"
        if config.get(CONF_ALARM_STREAM):
            # Sound on the alarm stream, audible with Do Not Disturb
            data["channel"] = "alarm_stream"
        elif channel := (config.get(CONF_CHANNEL) or "").strip():
            data["channel"] = channel
            data["importance"] = config.get(CONF_IMPORTANCE) or DEFAULT_IMPORTANCE
        return {"title": state["title"], "message": state["message"], "data": data}

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
        self._set_issue(
            ISSUE_MISSING_RECIPIENTS,
            subentry_id,
            {"recipients": ", ".join(resolution.problems)}
            if resolution.problems
            else None,
        )
        if not resolution.services:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_recipients",
                translation_placeholders={"notification": self.title(subentry_id)},
            )

        old = self.states.get(subentry_id, _empty_state())
        self._cancel_timers(subentry_id)
        self._set_issue(ISSUE_RESEND_LIMIT, subentry_id, None)
        if old["status"] == STATUS_OPEN:
            # Remove it from phones that are no longer addressed
            stale = [s for s in old["targets"] if s not in resolution.services]
            await self._clear(subentry_id, stale)

        send_id = int(old.get("send_id") or 0) + 1
        now = dt_util.utcnow()
        expire = int(config.get(CONF_EXPIRE) or 0)
        expires_at = now + timedelta(minutes=expire) if expire > 0 else None

        state = _empty_state()
        state.update(
            {
                "status": STATUS_OPEN,
                "send_id": send_id,
                "sent_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "targets": resolution.services,
                "title": title if title is not None else config.get(CONF_TITLE),
                "message": message if message is not None else config.get(CONF_MESSAGE),
                "icon": config.get(CONF_ICON) or DEFAULT_ICON,
                "actions": [
                    {"action": action_id_for(subentry_id, send_id, i), "title": label}
                    for i, label in enumerate(button_labels_for(config))
                ],
                "labels": old.get("labels"),
                "stale_labels": old.get("stale_labels", []),
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
            "send_id": send_id,
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
    def _parse_action(self, action: str) -> tuple[str, int | None, int] | None:
        """Return (subentry_id, send_id, button index) of one of our actions."""
        parts = action.split("|")
        if parts[0] != ACTION_PREFIX:
            return None
        if len(parts) == 4:
            _, subentry_id, send_id, index = parts
            if not send_id.isdigit():
                return None
            parsed_send: int | None = int(send_id)
        elif len(parts) == 3:
            # Format of version 0.1, which had no send id
            _, subentry_id, index = parts
            parsed_send = None
        else:
            return None
        if subentry_id not in self.states or not index.isdigit():
            return None
        return subentry_id, parsed_send, int(index)

    @callback
    def _on_action(self, event: Event) -> None:
        action = event.data.get("action")
        if not isinstance(action, str):
            return
        if (parsed := self._parse_action(action)) is None:
            return
        self.hass.async_create_task(self._async_answer(*parsed, event))

    async def _async_answer(
        self, subentry_id: str, send_id: int | None, index: int, event: Event
    ) -> None:
        state = self.states[subentry_id]
        sender = self._sender(event)
        if state["status"] != STATUS_OPEN or (
            send_id is not None and send_id != state["send_id"]
        ):
            # A press on an expired, answered or replaced notification does
            # not count; just make sure it disappears from that phone
            _LOGGER.debug(
                "Ignoring stale answer to %s (send %s, current %s)",
                self.title(subentry_id),
                send_id,
                state["send_id"],
            )
            await self._clear(
                subentry_id, self._services_for_sender(sender, state["targets"])
            )
            return
        labels = button_labels_for(self.config(subentry_id))
        if index >= len(labels):
            return
        button = labels[index]

        self._cancel_timers(subentry_id)
        state["status"] = STATUS_ANSWERED
        state["answer"] = {
            "button": button,
            "button_index": index,
            "confirmed": index == 0,
            "person": sender.person_id,
            "person_name": sender.person_name,
            "device": sender.device_name,
            "send_id": state["send_id"],
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
            self._set_issue(
                ISSUE_RESEND_LIMIT, subentry_id, {"count": str(MAX_RESENDS)}
            )
            return
        services = self._services_for_sender(self._sender(event), state["targets"])

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
        self._notify(subentry_id)

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
                "device": None,
                "send_id": state["send_id"],
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
