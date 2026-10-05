"""App-owned scheduling for the existing Local sync engine.

One Local backend process owns one coordinator. Blocking engine/credential work
runs in the event loop's worker pool; no thread or task starts at import time.
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Event

from fastapi import HTTPException
from sqlalchemy import select

from .. import core_connection
from ..models import LocalSyncState, User, Workspace, utcnow
from ..utils.time import iso_utc
from .engine import SyncCycleCancelled, _counts, run_sync_cycle
from .local import get_local_sync_state
from .remote import SyncRemoteError


logger = logging.getLogger(__name__)
RETRYABLE_ERRORS = frozenset({"unreachable", "timeout"})
SAFE_SYNC_ERRORS = RETRYABLE_ERRORS | frozenset({
    "unauthorized", "protocol_mismatch", "workspace_binding_conflict",
    "invalid_connection", "invalid_response", "invalid_local_state",
    "ownership_conflict", "missing_category", "collection_not_found",
    "category_not_found", "unknown_entity_type", "missing_collection",
    "collection_id_immutable", "invalid_client", "internal_error",
})


@dataclass(frozen=True)
class BackgroundSyncConfig:
    initial_delay: float = 1.0
    debounce: float = 0.5
    max_debounce: float = 2.0
    periodic_interval: float = 30.0
    retry_delays: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0, 60.0)

    def __post_init__(self):
        values = (self.debounce, self.max_debounce, self.periodic_interval, *self.retry_delays)
        if (not math.isfinite(self.initial_delay) or self.initial_delay < 0 or
                not self.retry_delays or any(not math.isfinite(value) or value <= 0 for value in values) or
                self.max_debounce < self.debounce or
                tuple(sorted(self.retry_delays)) != self.retry_delays):
            raise ValueError("Invalid background sync intervals")

    @classmethod
    def from_env(cls):
        """Central timing overrides; production uses the conservative defaults."""
        defaults = cls()
        try:
            debounce = float(os.getenv("NEXA_SYNC_DEBOUNCE_SECONDS", defaults.debounce))
            retry = os.getenv("NEXA_SYNC_RETRY_SECONDS")
            return cls(
                initial_delay=float(os.getenv("NEXA_SYNC_INITIAL_DELAY_SECONDS", defaults.initial_delay)),
                debounce=debounce, max_debounce=max(defaults.max_debounce, debounce),
                periodic_interval=float(os.getenv("NEXA_SYNC_PERIOD_SECONDS", defaults.periodic_interval)),
                retry_delays=tuple(float(value.strip()) for value in retry.split(",")) if retry else defaults.retry_delays,
            )
        except (TypeError, ValueError):
            raise ValueError("Invalid background sync intervals") from None


@dataclass
class _WorkspaceSchedule:
    user_id: int
    workspace_id: str
    connected: bool = False
    blocked: bool = False
    generation: int = 0
    failures: int = 0
    due: float | None = None
    retry_due: float | None = None
    requested_at: float | None = None
    request_due: float | None = None
    last_attempt: object = None
    next_retry: object = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    cancel: Event = field(default_factory=Event)
    scheduler: asyncio.Task | None = None
    active: asyncio.Task | None = None


async def _wait_event(event: asyncio.Event, delay: float | None):
    if delay is None:
        await event.wait()
    else:
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, delay))
        except TimeoutError:
            pass


class BackgroundSyncCoordinator:
    def __init__(self, factory, *, config=None, load_connection=None, load_credential=None,
                 runner=None, clock: Callable = time.monotonic, utc_now: Callable = utcnow,
                 wait=None, discover=None):
        self.factory = factory
        self.config = config or BackgroundSyncConfig()
        self.load_connection = load_connection or core_connection.load_connection
        self.load_credential = load_credential or (lambda user_id: core_connection.credential_store.load(user_id))
        self.runner = runner or run_sync_cycle
        self.clock = clock
        self.utc_now = utc_now
        self.wait = wait or _wait_event
        self.discover = discover or self._discover
        self._loop = None
        self._discovery = None
        self._stopping = False
        self._workspaces: dict[str, _WorkspaceSchedule] = {}
        self._preflights: set[asyncio.Task] = set()
        # Replaced immutable public dictionaries make snapshots safe in request threads.
        self._snapshots: dict[str, dict] = {}

    def start(self):
        """Return immediately; discovering saved connections never delays readiness."""
        if self._loop is not None:
            return
        self._workspaces.clear()
        self._snapshots.clear()
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._discovery = self._loop.create_task(self._restore(), name="background-sync-discovery")

    async def stop(self):
        """Cancel timers, cooperatively stop HTTP cycles, and join every worker."""
        if self._loop is None:
            return
        self._stopping = True
        for state in self._workspaces.values():
            state.cancel.set()
            state.wake.set()
            if state.scheduler is not None:
                state.scheduler.cancel()
            self._publish(state)
        # Shielded to_thread work is awaited rather than orphaned by task cancellation.
        tasks = [state.scheduler for state in self._workspaces.values() if state.scheduler is not None]
        tasks += [state.active for state in self._workspaces.values() if state.active is not None]
        tasks += list(self._preflights)
        if self._discovery is not None:
            tasks.append(self._discovery)
        await asyncio.gather(*tasks, return_exceptions=True)
        for state in self._workspaces.values():
            self._publish(state)
        self._loop = None

    def request_sync(self, workspace_id: str):
        """A committed Local outbox write may call this from any request thread."""
        self._dispatch(self._request, workspace_id)

    def connection_changed(self, user_id: int, workspace_id: str, connected: bool):
        self._dispatch(self._connection_changed, user_id, workspace_id, connected)

    def _dispatch(self, callback, *args):
        loop = self._loop
        if loop is not None and not self._stopping and not loop.is_closed():
            loop.call_soon_threadsafe(callback, *args)

    def snapshot(self, workspace_id: str) -> dict:
        return dict(self._snapshots.get(workspace_id, {
            "enabled": False, "running": False, "connected": False, "blocked": False,
            "lastAttemptAt": None, "nextRetryAt": None,
        }))

    async def manual(self, user_id: int, workspace_id: str) -> dict:
        """Join an active cycle or run this same engine immediately, even if blocked."""
        if self._loop is None or self._stopping:
            raise HTTPException(409, "Background sync is stopped")
        state = self._workspaces.get(workspace_id)
        if state is not None and state.user_id != user_id:
            raise HTTPException(403, "Workspace is unavailable")
        if state is not None and state.active is not None:
            result = await asyncio.shield(state.active)
        else:
            # Keep the existing manual API's configuration/credential HTTP errors.
            preflight = self._loop.create_task(asyncio.to_thread(self._load, user_id))
            self._preflights.add(preflight)
            preflight.add_done_callback(self._preflight_done)
            metadata, credential = await asyncio.shield(preflight)
            if metadata is None:
                raise HTTPException(409, "Core connection is not configured")
            if not credential or not credential.startswith("nc_live_"):
                raise HTTPException(401, "Client credential is unavailable")
            if self._stopping:
                raise HTTPException(409, "Background sync is stopped")
            state = self._ensure(user_id, workspace_id)
            # Another manual caller may have launched while credential I/O yielded.
            if state.active is None:
                state.connected = True
                state.blocked = False
                self._launch(state)
            result = await asyncio.shield(state.active)
        if result is None:
            raise HTTPException(409, "Sync was stopped")
        if result.get("status") == "busy":
            raise HTTPException(409, "Sync is already running for this workspace")
        if result.get("_diagnosticsUnavailable"):
            raise HTTPException(503, "Sync diagnostics are unavailable")
        return result

    def _preflight_done(self, task):
        self._preflights.discard(task)
        if not task.cancelled():
            # A disconnected HTTP caller may no longer await the shielded load.
            # Retrieve its exception without logging private credential details.
            task.exception()

    def _load(self, user_id):
        metadata = self.load_connection(user_id)
        if metadata is None:
            return None, None
        try:
            credential = self.load_credential(user_id)
        except OSError:
            credential = None
        return metadata, credential

    def _discover(self):
        with self.factory() as db:
            rows = db.execute(select(User.id, Workspace.id, LocalSyncState.last_error)
                .join(Workspace, Workspace.owner_user_id == User.id)
                .outerjoin(LocalSyncState, LocalSyncState.workspace_id == Workspace.id)
                .where(Workspace.kind == "personal")
                .order_by(Workspace.created_at, Workspace.id)).all()
        connected = []
        seen_users = set()
        for user_id, workspace_id, last_error in rows:
            if user_id in seen_users:
                continue
            seen_users.add(user_id)
            try:
                metadata, credential = self._load(user_id)
                if metadata is not None:
                    error = last_error
                    if not credential or not credential.startswith("nc_live_"):
                        error = "unauthorized"
                    connected.append((user_id, workspace_id, error))
            except (HTTPException, OSError):
                # Invalid saved metadata must not fail Backend startup.
                continue
        return connected

    async def _restore(self):
        try:
            entries = await asyncio.to_thread(self.discover)
        except Exception:
            logger.warning("Background sync discovery failed")
            return
        if self._stopping:
            return
        for user_id, workspace_id, error in entries:
            if self._stopping:
                return
            if workspace_id in self._workspaces:
                continue
            state = self._ensure(user_id, workspace_id)
            state.connected = True
            state.blocked = bool(error and error not in RETRYABLE_ERRORS)
            state.due = self.clock() + self.config.initial_delay
            if error == "unauthorized":
                try:
                    await asyncio.to_thread(self._persist_error, workspace_id, error)
                except Exception:
                    logger.warning("Background sync diagnostic persistence failed")
            self._publish(state)
            state.wake.set()

    def _ensure(self, user_id, workspace_id):
        state = self._workspaces.get(workspace_id)
        if state is None:
            state = _WorkspaceSchedule(user_id, workspace_id)
            self._workspaces[workspace_id] = state
            state.scheduler = self._loop.create_task(self._schedule(state), name="background-sync-workspace")
        elif state.user_id != user_id:
            raise HTTPException(403, "Workspace is unavailable")
        return state

    def _connection_changed(self, user_id, workspace_id, connected):
        if self._stopping:
            return
        state = self._ensure(user_id, workspace_id)
        state.generation += 1
        state.cancel.set()
        state.connected = connected
        state.blocked = False
        state.failures = 0
        state.retry_due = state.next_retry = None
        state.requested_at = state.request_due = None
        state.due = self.clock() + self.config.initial_delay if connected else None
        self._publish(state)
        state.wake.set()

    def _request(self, workspace_id):
        state = self._workspaces.get(workspace_id)
        if state is None or not state.connected or self._stopping:
            return
        now = self.clock()
        if state.requested_at is None:
            state.requested_at = now
        state.request_due = min(now + self.config.debounce,
                                state.requested_at + self.config.max_debounce)
        state.wake.set()

    def _deadline(self, state):
        if not state.connected or state.blocked:
            return None
        # Writes wake the timer but cannot bypass an offline retry floor.
        if state.retry_due is not None:
            return max(state.retry_due, state.request_due or state.retry_due)
        candidates = [value for value in (state.due, state.request_due) if value is not None]
        return min(candidates) if candidates else None

    async def _schedule(self, state):
        try:
            while not self._stopping:
                if state.active is not None:
                    await asyncio.shield(state.active)
                    continue
                state.wake.clear()
                deadline = self._deadline(state)
                if deadline is not None and deadline <= self.clock():
                    self._launch(state)
                    continue
                await self.wait(state.wake, None if deadline is None else deadline - self.clock())
        except asyncio.CancelledError:
            # stop() separately joins active cycles, including their to_thread worker.
            pass

    def _launch(self, state):
        state.cancel = Event()
        state.requested_at = state.request_due = None
        state.retry_due = state.next_retry = None
        state.last_attempt = self.utc_now()
        state.active = self._loop.create_task(self._cycle(state, state.generation, state.cancel),
                                               name="background-sync-cycle")
        self._publish(state)

    def _persist_error(self, workspace_id, code):
        with self.factory() as db:
            state = get_local_sync_state(db, workspace_id)
            state.last_error = code
            db.commit()

    def _invoke(self, state, cancel):
        try:
            if cancel.is_set():
                raise SyncCycleCancelled()
            metadata, credential = self._load(state.user_id)
            if cancel.is_set():
                raise SyncCycleCancelled()
            if metadata is None:
                return None
            if not credential or not credential.startswith("nc_live_"):
                raise SyncRemoteError("unauthorized")
            return self.runner(self.factory, state.user_id, state.workspace_id, metadata,
                               credential, cancel_event=cancel)
        except SyncCycleCancelled:
            raise
        except HTTPException as error:
            if error.status_code == 409 and error.detail == "Sync is already running for this workspace":
                # External/manual legacy callers still share the engine's lock.
                return {"status": "busy"}
            code = "workspace_binding_conflict" if error.status_code == 409 else "invalid_connection"
        except SyncRemoteError as error:
            code = error.code if error.code in SAFE_SYNC_ERRORS else "invalid_response"
        except Exception:
            code = "internal_error"
        if cancel.is_set():
            raise SyncCycleCancelled()
        self._persist_error(state.workspace_id, code)
        return {"status": "error", "pushed": 0, "pulled": 0,
                **_counts(self.factory, state.workspace_id), "workspaceRevision": None}

    async def _cycle(self, state, generation, cancel):
        result = None
        try:
            result = await asyncio.to_thread(self._invoke, state, cancel)
            if not self._stopping and generation == state.generation:
                if result is None:
                    state.connected = False
                    state.due = None
                elif result.get("status") == "ok":
                    state.failures = 0
                    state.blocked = False
                    state.due = self.clock() + self.config.periodic_interval
                elif result.get("status") == "busy" or result.get("lastError") in RETRYABLE_ERRORS:
                    index = min(state.failures, len(self.config.retry_delays) - 1)
                    delay = self.config.retry_delays[index]
                    state.failures += 1
                    state.retry_due = self.clock() + delay
                    state.next_retry = self.utc_now() + timedelta(seconds=delay)
                    logger.info("Sync cycle failed: %s; retry in %ss",
                                "busy" if result.get("status") == "busy" else result.get("lastError"), delay)
                else:
                    state.blocked = True
                    state.due = None
                    state.retry_due = state.next_retry = None
                    logger.info("Sync cycle blocked")
        except SyncCycleCancelled:
            pass
        except Exception:
            # A database/diagnostic failure must not kill this workspace's timer
            # or leak an exception through a manual API waiter.
            logger.warning("Sync cycle blocked: internal_error")
            if not self._stopping and generation == state.generation:
                state.blocked = True
                state.due = None
                state.retry_due = state.next_retry = None
                try:
                    await asyncio.to_thread(self._persist_error, state.workspace_id, "internal_error")
                except Exception:
                    logger.warning("Background sync diagnostic persistence failed")
            result = {"status": "error", "lastError": "internal_error", "_diagnosticsUnavailable": True}
        finally:
            state.active = None
            self._publish(state)
            state.wake.set()
        return result

    def _publish(self, state):
        self._snapshots[state.workspace_id] = {
            "enabled": state.connected and not self._stopping,
            "running": state.active is not None,
            "connected": state.connected,
            "blocked": state.blocked,
            "lastAttemptAt": iso_utc(state.last_attempt),
            "nextRetryAt": iso_utc(state.next_retry) if not self._stopping else None,
        }
