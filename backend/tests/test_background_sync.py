"""Deterministic coordinator timers plus the unchanged production engine/transport."""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import LocalMutation, LocalSyncState
from app.sync.background import BackgroundSyncConfig, BackgroundSyncCoordinator
from app.sync.engine import SyncCycleCancelled, run_sync_cycle
from app.sync.remote import SyncRemoteClient
from test_sync_engine import create_transaction, network, queue, replica


def async_test(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(asyncio.wait_for(function(*args, **kwargs), timeout=10))
    return wrapped


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.origin = datetime(2026, 10, 2, tzinfo=timezone.utc)
        self.timers = []

    def monotonic(self):
        return self.now

    def utcnow(self):
        return self.origin + timedelta(seconds=self.now)

    async def wait(self, event, delay):
        alarm = asyncio.get_running_loop().create_future()
        timer = (None if delay is None else self.now + delay, alarm)
        self.timers.append(timer)
        signal = asyncio.create_task(event.wait())
        try:
            await asyncio.wait((signal, alarm), return_when=asyncio.FIRST_COMPLETED)
        finally:
            signal.cancel()
            alarm.cancel()
            await asyncio.gather(signal, return_exceptions=True)
            self.timers.remove(timer)

    def advance(self, seconds):
        self.now = round(self.now + seconds, 9)
        for deadline, alarm in tuple(self.timers):
            if deadline is not None and deadline <= self.now and not alarm.done():
                alarm.set_result(None)


async def settle(predicate=lambda: True):
    """Yield to worker completion and loop callbacks without advancing real time."""
    for _ in range(100):
        await asyncio.to_thread(lambda: None)
        await asyncio.sleep(0)
        if predicate():
            # Also let the timer register its next fake-clock wait.
            for _ in range(5):
                await asyncio.sleep(0)
            return
    raise AssertionError("Coordinator did not reach its expected state")


def result(code=None):
    return {"status": "error" if code else "ok", "lastError": code,
            "pending": 0, "inFlight": 0, "conflicts": 0, "rejected": 0,
            "cursor": 0, "pushed": 0, "pulled": 0, "workspaceRevision": 0}


class Runner:
    def __init__(self, outcomes=()):
        self.calls = []
        self.outcomes = list(outcomes)
        self.started = Event()
        self.release = Event()
        self.release.set()

    def __call__(self, _factory, user_id, workspace_id, _metadata, _credential, *, cancel_event):
        self.calls.append((user_id, workspace_id, cancel_event))
        self.started.set()
        assert self.release.wait(5), "Test runner was not released"
        if cancel_event.is_set():
            raise SyncCycleCancelled()
        return self.outcomes.pop(0) if self.outcomes else result()


@pytest.fixture
def local(tmp_path):
    value = replica(tmp_path, "background_local", 101)
    yield value
    value.engine.dispose()


def make_coordinator(local, clock, runner, *, saved=True, error=None, **kwargs):
    metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=str(uuid4()), clientId=str(uuid4()))
    return BackgroundSyncCoordinator(
        local.factory, runner=runner, clock=clock.monotonic, utc_now=clock.utcnow,
        wait=clock.wait, load_connection=lambda _user: metadata,
        load_credential=lambda _user: "nc_live_test_secret",
        discover=lambda: [(local.user_id, local.workspace_id, error)] if saved else [], **kwargs,
    )


async def restored(coordinator):
    coordinator.start()
    await settle(lambda: coordinator._discovery.done())


async def completed(coordinator, runner, count):
    await settle(lambda: len(runner.calls) == count and
                 all(state.active is None for state in coordinator._workspaces.values()))


@async_test
async def test_startup_initial_and_periodic_sync(local):
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        assert coordinator.snapshot(local.workspace_id)["enabled"]
        assert runner.calls == []
        clock.advance(0.99)
        await settle()
        assert runner.calls == []
        clock.advance(0.01)
        await completed(coordinator, runner, 1)
        assert coordinator.snapshot(local.workspace_id)["lastAttemptAt"] == clock.utcnow().isoformat()
        clock.advance(29.99)
        await settle()
        assert len(runner.calls) == 1
        clock.advance(0.01)
        await completed(coordinator, runner, 2)
    finally:
        await coordinator.stop()


@async_test
async def test_local_write_wakeup_debounce_and_bounded_stream(local):
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        clock.advance(1)
        await completed(coordinator, runner, 1)
        coordinator.request_sync(local.workspace_id)
        await settle()
        clock.advance(0.25)
        coordinator.request_sync(local.workspace_id)
        await settle()
        clock.advance(0.49)
        await settle()
        assert len(runner.calls) == 1
        clock.advance(0.01)
        await completed(coordinator, runner, 2)
        # A continuous stream cannot postpone a cycle beyond max_debounce.
        for _ in range(8):
            coordinator.request_sync(local.workspace_id)
            await settle()
            clock.advance(0.25)
            await settle()
        await completed(coordinator, runner, 3)
    finally:
        await coordinator.stop()


@async_test
async def test_background_manual_and_write_share_one_cycle_without_lost_wakeup(local):
    clock, runner = FakeClock(), Runner()
    runner.release.clear()
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        clock.advance(1)
        await settle(lambda: runner.started.is_set())
        assert coordinator.snapshot(local.workspace_id)["running"]
        manual_a = asyncio.create_task(coordinator.manual(local.user_id, local.workspace_id))
        manual_b = asyncio.create_task(coordinator.manual(local.user_id, local.workspace_id))
        # Simulate writes arriving from FastAPI's worker threads during HTTP I/O.
        await asyncio.to_thread(coordinator.request_sync, local.workspace_id)
        await settle(lambda: coordinator._workspaces[local.workspace_id].request_due is not None)
        clock.advance(30)
        await settle()
        assert len(runner.calls) == 1
        runner.release.set()
        responses = await asyncio.gather(manual_a, manual_b)
        assert responses[0] is responses[1]
        await completed(coordinator, runner, 2)
        assert all(entry[0:2] == (local.user_id, local.workspace_id) for entry in runner.calls)
    finally:
        runner.release.set()
        await coordinator.stop()


@async_test
async def test_manual_callers_start_single_cycle_and_request_cancellation_does_not_stop_worker(local):
    clock, runner = FakeClock(), Runner()
    runner.release.clear()
    coordinator = make_coordinator(local, clock, runner, saved=False)
    await restored(coordinator)
    try:
        first = asyncio.create_task(coordinator.manual(local.user_id, local.workspace_id))
        second = asyncio.create_task(coordinator.manual(local.user_id, local.workspace_id))
        await settle(lambda: runner.started.is_set())
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        assert not runner.calls[0][2].is_set()
        assert len(runner.calls) == 1
        runner.release.set()
        assert (await second)["status"] == "ok"
    finally:
        runner.release.set()
        await coordinator.stop()


@async_test
async def test_backoff_is_bounded_writes_cannot_bypass_it_and_success_resets(local):
    clock = FakeClock()
    runner = Runner([result("unreachable") for _ in range(6)] + [result(), result("timeout")])
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        clock.advance(1)
        await completed(coordinator, runner, 1)
        for attempt, delay in enumerate((5, 10, 20, 30, 60, 60), start=1):
            state = coordinator.snapshot(local.workspace_id)
            assert state["nextRetryAt"] == (clock.utcnow() + timedelta(seconds=delay)).isoformat()
            assert not state["blocked"]
            coordinator.request_sync(local.workspace_id)
            await settle()
            clock.advance(delay - 0.01)
            await settle()
            assert len(runner.calls) == attempt
            clock.advance(0.01)
            await completed(coordinator, runner, attempt + 1)
        assert coordinator.snapshot(local.workspace_id)["nextRetryAt"] is None
        clock.advance(30)
        await completed(coordinator, runner, 8)
        assert coordinator.snapshot(local.workspace_id)["nextRetryAt"] == (
            clock.utcnow() + timedelta(seconds=5)).isoformat()
    finally:
        await coordinator.stop()


@pytest.mark.parametrize("code", ["unauthorized", "protocol_mismatch", "invalid_client",
                                  "workspace_binding_conflict", "invalid_connection"])
@async_test
async def test_nonretryable_failure_blocks_until_manual_or_reconnect(local, code):
    clock, runner = FakeClock(), Runner([result(code), result(code), result()])
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        clock.advance(1)
        await completed(coordinator, runner, 1)
        assert coordinator.snapshot(local.workspace_id)["blocked"]
        assert coordinator.snapshot(local.workspace_id)["nextRetryAt"] is None
        clock.advance(10000)
        coordinator.request_sync(local.workspace_id)
        await settle()
        assert len(runner.calls) == 1
        assert (await coordinator.manual(local.user_id, local.workspace_id))["lastError"] == code
        assert coordinator.snapshot(local.workspace_id)["blocked"]
        await asyncio.to_thread(coordinator.connection_changed, local.user_id, local.workspace_id, True)
        await settle()
        clock.advance(1)
        await completed(coordinator, runner, 3)
        assert not coordinator.snapshot(local.workspace_id)["blocked"]
    finally:
        await coordinator.stop()


@async_test
async def test_disconnect_disables_and_reconnect_schedules_initial_sync(local):
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        coordinator.connection_changed(local.user_id, local.workspace_id, False)
        await settle()
        state = coordinator.snapshot(local.workspace_id)
        assert not state["enabled"] and not state["connected"]
        clock.advance(1000)
        coordinator.request_sync(local.workspace_id)
        await settle()
        assert not runner.calls
        coordinator.connection_changed(local.user_id, local.workspace_id, True)
        await settle()
        clock.advance(1)
        await completed(coordinator, runner, 1)
    finally:
        await coordinator.stop()


@async_test
async def test_shutdown_cancels_timer_and_joins_active_worker(local):
    clock, runner = FakeClock(), Runner()
    runner.release.clear()
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    clock.advance(1)
    await settle(lambda: runner.started.is_set())
    shutdown = asyncio.create_task(coordinator.stop())
    await settle()
    assert not shutdown.done()
    assert runner.calls[0][2].is_set()
    runner.release.set()
    await shutdown
    assert not coordinator.snapshot(local.workspace_id)["running"]
    assert not coordinator.snapshot(local.workspace_id)["enabled"]
    assert all(state.scheduler.done() and state.active is None for state in coordinator._workspaces.values())
    clock.advance(1000)
    coordinator.request_sync(local.workspace_id)
    await settle()
    assert len(runner.calls) == 1


@async_test
async def test_startup_discovery_does_not_block_and_stop_joins_it(local):
    started, release = Event(), Event()
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)

    def slow_discovery():
        started.set()
        assert release.wait(5)
        return [(local.user_id, local.workspace_id, None)]

    coordinator.discover = slow_discovery
    coordinator.start()
    await settle(lambda: started.is_set())
    assert not coordinator.snapshot(local.workspace_id)["enabled"]
    shutdown = asyncio.create_task(coordinator.stop())
    await settle()
    assert not shutdown.done()
    release.set()
    await shutdown
    assert not coordinator._workspaces


@async_test
async def test_cancelled_manual_preflight_is_joined_by_shutdown(local):
    started, release = Event(), Event()
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner, saved=False)

    def load(_user):
        started.set()
        assert release.wait(5)
        return None

    coordinator.load_connection = load
    await restored(coordinator)
    manual = asyncio.create_task(coordinator.manual(local.user_id, local.workspace_id))
    assert await asyncio.to_thread(started.wait, 5)
    manual.cancel()
    await asyncio.gather(manual, return_exceptions=True)
    shutdown = asyncio.create_task(coordinator.stop())
    await settle()
    assert not shutdown.done()
    release.set()
    await shutdown
    assert not coordinator._preflights
    assert not runner.calls


@async_test
async def test_persisted_blocked_error_survives_backend_restart(local):
    with local.factory() as db:
        db.add(LocalSyncState(workspace_id=local.workspace_id, last_error="unauthorized"))
        db.commit()
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)
    coordinator.discover = coordinator._discover
    await restored(coordinator)
    try:
        assert coordinator.snapshot(local.workspace_id)["blocked"]
        clock.advance(1000)
        await settle()
        assert not runner.calls
        assert (await coordinator.manual(local.user_id, local.workspace_id))["status"] == "ok"
    finally:
        await coordinator.stop()


@async_test
async def test_database_diagnostic_failure_preserves_scheduler_and_reconnect(local, monkeypatch):
    clock, runner = FakeClock(), Runner()
    coordinator = make_coordinator(local, clock, runner)

    def unavailable(*_args):
        raise RuntimeError("private database error nc_live_do_not_expose")

    coordinator.runner = unavailable
    monkeypatch.setattr(coordinator, "_persist_error", unavailable)
    await restored(coordinator)
    try:
        clock.advance(1)
        await settle(lambda: coordinator.snapshot(local.workspace_id)["blocked"])
        assert not coordinator._workspaces[local.workspace_id].scheduler.done()
        with pytest.raises(HTTPException) as error:
            await coordinator.manual(local.user_id, local.workspace_id)
        assert error.value.status_code == 503 and "private" not in str(error.value.detail)
        coordinator.runner = runner
        coordinator.connection_changed(local.user_id, local.workspace_id, True)
        await settle()
        clock.advance(1)
        await completed(coordinator, runner, 1)
        assert not coordinator.snapshot(local.workspace_id)["blocked"]
    finally:
        await coordinator.stop()


@pytest.mark.parametrize("failure,code,retryable", [
    ("refused", "unreachable", True), ("timeout", "timeout", True),
    (502, "unreachable", True), (503, "unreachable", True), (504, "unreachable", True),
    (401, "unauthorized", False), (409, "protocol_mismatch", False),
    (403, "invalid_response", False),
])
@async_test
async def test_real_engine_transport_failure_retry_classification_and_queue_safety(local, monkeypatch,
                                                                                  failure, code, retryable):
    item_id = create_transaction(local)
    original_client = httpx.Client

    def response(request):
        if failure == "refused":
            raise httpx.ConnectError("secret transport detail", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret transport detail", request=request)
        return httpx.Response(failure, json={"detail": "nc_live_secret_response"})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(response), **kwargs))
    clock = FakeClock()
    coordinator = make_coordinator(local, clock, run_sync_cycle)
    await restored(coordinator)
    try:
        clock.advance(1)
        await settle(lambda: coordinator.snapshot(local.workspace_id)["lastAttemptAt"] is not None and
                     not coordinator.snapshot(local.workspace_id)["running"])
        state = coordinator.snapshot(local.workspace_id)
        assert state["blocked"] is not retryable
        assert bool(state["nextRetryAt"]) is retryable
        with local.factory() as db:
            assert db.get(LocalSyncState, local.workspace_id).last_error == code
            assert db.get(LocalSyncState, local.workspace_id).cursor == 0
        assert queue(local, item_id)[0][1] == "pending"
        assert "secret" not in str(state)
    finally:
        await coordinator.stop()


@async_test
async def test_shutdown_mid_network_preserves_frozen_outbox_and_does_not_persist_error(network):
    n = network
    item_id = create_transaction(n.a)
    started, release = Event(), Event()
    original_push = n.ta.push_mutation

    def held_push(mutation):
        started.set()
        assert release.wait(5)
        # Core committed, but the response is lost during Local shutdown.
        original_push(mutation)
        from app.sync.remote import SyncRemoteError
        raise SyncRemoteError("timeout")

    n.ta.push_mutation = held_push

    def runner(factory, user_id, workspace_id, metadata, credential, *, cancel_event):
        metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=n.core.workspace_id,
                                   clientId=n.ta.client_id)
        return run_sync_cycle(factory, user_id, workspace_id, metadata, credential,
                              n.ta, cancel_event=cancel_event)

    clock = FakeClock()
    coordinator = make_coordinator(n.a, clock, runner)
    await restored(coordinator)
    clock.advance(1)
    assert await asyncio.to_thread(started.wait, 5)
    frozen = queue(n.a, item_id)
    assert frozen[0][1] == "in_flight"
    shutdown = asyncio.create_task(coordinator.stop())
    await settle()
    assert not shutdown.done()
    release.set()
    await shutdown
    assert queue(n.a, item_id) == frozen
    with n.a.factory() as db:
        assert db.get(LocalSyncState, n.a.workspace_id).last_error is None
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.last_error is None
    n.ta.push_mutation = original_push
    # Exact idempotent replay remains possible on restart.
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert queue(n.a, item_id) == []


@async_test
async def test_external_engine_lock_returns_existing_manual_409(local):
    clock, runner = FakeClock(), Runner([{"status": "busy"}])
    coordinator = make_coordinator(local, clock, runner, saved=False)
    await restored(coordinator)
    try:
        with pytest.raises(HTTPException) as error:
            await coordinator.manual(local.user_id, local.workspace_id)
        assert error.value.status_code == 409
        assert coordinator.snapshot(local.workspace_id)["nextRetryAt"] is not None
    finally:
        await coordinator.stop()


def test_central_config_validation(monkeypatch):
    defaults = BackgroundSyncConfig()
    assert defaults.periodic_interval == 30 and defaults.retry_delays[-1] == 60
    monkeypatch.setenv("NEXA_SYNC_PERIOD_SECONDS", "0.25")
    monkeypatch.setenv("NEXA_SYNC_RETRY_SECONDS", "0.1,0.2,0.5")
    configured = BackgroundSyncConfig.from_env()
    assert configured.periodic_interval == 0.25 and configured.retry_delays == (0.1, 0.2, 0.5)
    for value in ("0", "-1", "nan", "inf", "private_invalid_value"):
        monkeypatch.setenv("NEXA_SYNC_PERIOD_SECONDS", value)
        with pytest.raises(ValueError, match="Invalid background sync intervals"):
            BackgroundSyncConfig.from_env()
