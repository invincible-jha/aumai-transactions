"""Shared test fixtures for aumai-transactions tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from unittest.mock import MagicMock

import pytest

from aumai_transactions.core import SagaOrchestrator, TransactionManager
from aumai_transactions.models import (
    Transaction,
    TransactionResult,
    TransactionState,
    TransactionStep,
)


# ---------------------------------------------------------------------------
# Action handler helpers
# ---------------------------------------------------------------------------


def make_recording_handler() -> tuple[list[tuple[str, dict]], Callable]:
    """Return a (calls_log, handler) pair. The handler records each invocation."""
    calls: list[tuple[str, dict]] = []

    def handler(action: str, data: dict) -> None:
        calls.append((action, data))

    return calls, handler


def make_failing_handler(fail_on_action: str) -> Callable:
    """Return a handler that raises RuntimeError when called with fail_on_action."""
    def handler(action: str, data: dict) -> None:
        if action == fail_on_action:
            raise RuntimeError(f"Simulated failure for action: {fail_on_action}")

    return handler


# ---------------------------------------------------------------------------
# TransactionManager fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> TransactionManager:
    """Manager with no action handlers (dry-run mode)."""
    return TransactionManager()


@pytest.fixture()
def recording_manager() -> tuple[TransactionManager, list[tuple[str, dict]]]:
    """Manager with a recording handler for 'do_step' action."""
    calls: list[tuple[str, dict]] = []

    def handler(action: str, data: dict) -> None:
        calls.append((action, data))

    mgr = TransactionManager(action_handlers={"do_step": handler, "undo_step": handler})
    return mgr, calls


# ---------------------------------------------------------------------------
# Transaction fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def pending_tx(manager: TransactionManager) -> Transaction:
    return manager.begin(timeout_seconds=60)


@pytest.fixture()
def tx_with_one_step(manager: TransactionManager, pending_tx: Transaction) -> Transaction:
    manager.add_step(
        pending_tx,
        agent_id="agent-1",
        action="do_something",
        data={"key": "value"},
        compensating_action="undo_something",
    )
    return pending_tx


@pytest.fixture()
def tx_with_three_steps(manager: TransactionManager, pending_tx: Transaction) -> Transaction:
    for i in range(3):
        manager.add_step(
            pending_tx,
            agent_id=f"agent-{i}",
            action=f"step_{i}",
            data={"index": i},
            compensating_action=f"undo_step_{i}",
        )
    return pending_tx


@pytest.fixture()
def saga() -> SagaOrchestrator:
    return SagaOrchestrator()
