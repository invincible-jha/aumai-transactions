"""Comprehensive tests for aumai_transactions core module."""

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


# ===========================================================================
# TransactionManager.begin
# ===========================================================================


class TestTransactionManagerBegin:
    def test_begin_returns_transaction(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert isinstance(tx, Transaction)

    def test_begin_state_is_pending(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert tx.state == TransactionState.pending

    def test_begin_has_transaction_id(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert tx.transaction_id != ""

    def test_begin_unique_ids(self, manager: TransactionManager) -> None:
        tx1 = manager.begin()
        tx2 = manager.begin()
        assert tx1.transaction_id != tx2.transaction_id

    def test_begin_empty_steps(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert tx.steps == []

    def test_begin_default_timeout(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert tx.timeout_seconds == 60

    def test_begin_custom_timeout(self, manager: TransactionManager) -> None:
        tx = manager.begin(timeout_seconds=120)
        assert tx.timeout_seconds == 120

    def test_begin_created_at_is_datetime(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert isinstance(tx.created_at, datetime)

    def test_begin_created_at_recent(self, manager: TransactionManager) -> None:
        before = datetime.now(tz=timezone.utc)
        tx = manager.begin()
        after = datetime.now(tz=timezone.utc)
        assert before <= tx.created_at <= after

    def test_begin_stores_in_registry(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        assert manager.get_transaction(tx.transaction_id) is not None

    def test_begin_multiple_stored_separately(self, manager: TransactionManager) -> None:
        tx1 = manager.begin()
        tx2 = manager.begin()
        all_txs = manager.get_all_transactions()
        assert len(all_txs) == 2


# ===========================================================================
# TransactionManager.add_step
# ===========================================================================


class TestTransactionManagerAddStep:
    def test_add_step_returns_transaction_step(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step = manager.add_step(pending_tx, "agent-1", "do_action", {})
        assert isinstance(step, TransactionStep)

    def test_add_step_appended_to_transaction(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        manager.add_step(pending_tx, "agent-1", "do_action", {})
        assert len(pending_tx.steps) == 1

    def test_add_step_agent_id_preserved(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step = manager.add_step(pending_tx, "my-agent", "action", {})
        assert step.agent_id == "my-agent"

    def test_add_step_action_preserved(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step = manager.add_step(pending_tx, "agent", "send_email", {})
        assert step.action == "send_email"

    def test_add_step_data_preserved(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        data = {"to": "user@example.com", "subject": "Test"}
        step = manager.add_step(pending_tx, "agent", "send_email", data)
        assert step.data == data

    def test_add_step_compensating_action_preserved(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step = manager.add_step(
            pending_tx, "agent", "do_action", {}, compensating_action="undo_action"
        )
        assert step.compensating_action == "undo_action"

    def test_add_step_no_compensating_action_is_none(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step = manager.add_step(pending_tx, "agent", "action", {})
        assert step.compensating_action is None

    def test_add_step_has_unique_step_id(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        step1 = manager.add_step(pending_tx, "agent", "a1", {})
        step2 = manager.add_step(pending_tx, "agent", "a2", {})
        assert step1.step_id != step2.step_id

    def test_add_step_to_non_pending_raises_value_error(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        manager.commit(pending_tx)  # moves to committed
        with pytest.raises(ValueError, match="pending"):
            manager.add_step(pending_tx, "agent", "action", {})

    def test_add_multiple_steps_preserves_order(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        actions = ["step_a", "step_b", "step_c"]
        for action in actions:
            manager.add_step(pending_tx, "agent", action, {})
        assert [s.action for s in pending_tx.steps] == actions


# ===========================================================================
# TransactionManager.commit
# ===========================================================================


class TestTransactionManagerCommit:
    def test_commit_empty_tx_returns_committed(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        result = manager.commit(tx)
        assert result.state == TransactionState.committed

    def test_commit_returns_transaction_result(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        result = manager.commit(tx)
        assert isinstance(result, TransactionResult)

    def test_commit_result_has_transaction_id(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        result = manager.commit(tx)
        assert result.transaction_id == tx.transaction_id

    def test_commit_with_steps_no_handlers_succeeds(
        self, manager: TransactionManager, tx_with_three_steps: Transaction
    ) -> None:
        result = manager.commit(tx_with_three_steps)
        assert result.state == TransactionState.committed

    def test_commit_completed_steps_count(
        self, manager: TransactionManager, tx_with_three_steps: Transaction
    ) -> None:
        result = manager.commit(tx_with_three_steps)
        assert len(result.completed_steps) == 3

    def test_commit_calls_action_handlers(self) -> None:
        calls: list[str] = []
        mgr = TransactionManager(action_handlers={
            "step_a": lambda action, data: calls.append(action),
            "step_b": lambda action, data: calls.append(action),
        })
        tx = mgr.begin()
        mgr.add_step(tx, "agent", "step_a", {})
        mgr.add_step(tx, "agent", "step_b", {})
        mgr.commit(tx)
        assert calls == ["step_a", "step_b"]

    def test_commit_non_pending_raises_value_error(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        manager.commit(tx)
        with pytest.raises(ValueError, match="pending"):
            manager.commit(tx)

    def test_commit_updates_tx_state_to_committed(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        manager.commit(tx)
        stored_tx = manager.get_transaction(tx.transaction_id)
        assert stored_tx is not None
        assert stored_tx.state == TransactionState.committed

    def test_commit_no_error_on_success(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        result = manager.commit(tx)
        assert result.error is None

    def test_commit_no_failed_step_on_success(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        result = manager.commit(tx)
        assert result.failed_step is None

    def test_commit_failure_triggers_rollback(self) -> None:
        calls: list[str] = []
        failing_action = "step_b"

        def handler(action: str, data: dict) -> None:
            if action == failing_action:
                raise RuntimeError("Simulated failure")
            calls.append(action)

        mgr = TransactionManager(action_handlers={"step_a": handler, "step_b": handler})
        tx = mgr.begin()
        mgr.add_step(tx, "agent", "step_a", {})
        mgr.add_step(tx, "agent", "step_b", {})
        result = mgr.commit(tx)
        assert result.state == TransactionState.rolled_back

    def test_commit_failure_sets_error_message(self) -> None:
        def failing_handler(action: str, data: dict) -> None:
            raise RuntimeError("boom")

        mgr = TransactionManager(action_handlers={"fail_action": failing_handler})
        tx = mgr.begin()
        mgr.add_step(tx, "agent", "fail_action", {})
        result = mgr.commit(tx)
        assert result.error is not None
        assert "boom" in result.error

    def test_commit_failure_sets_failed_step(self) -> None:
        def failing_handler(action: str, data: dict) -> None:
            raise RuntimeError("boom")

        mgr = TransactionManager(action_handlers={"fail_action": failing_handler})
        tx = mgr.begin()
        step = mgr.add_step(tx, "agent", "fail_action", {})
        result = mgr.commit(tx)
        assert result.failed_step == step.step_id

    def test_commit_failure_runs_compensating_actions_in_reverse(self) -> None:
        calls: list[str] = []

        def handler(action: str, data: dict) -> None:
            if action == "step_c":
                raise RuntimeError("fail at step_c")
            calls.append(action)

        mgr = TransactionManager(action_handlers={
            "step_a": handler,
            "step_b": handler,
            "step_c": handler,
            "undo_a": handler,
            "undo_b": handler,
        })
        tx = mgr.begin()
        mgr.add_step(tx, "agent", "step_a", {}, compensating_action="undo_a")
        mgr.add_step(tx, "agent", "step_b", {}, compensating_action="undo_b")
        mgr.add_step(tx, "agent", "step_c", {})
        mgr.commit(tx)
        # Compensating actions should be undo_b then undo_a (reverse order)
        assert calls.index("undo_b") < calls.index("undo_a")

    def test_commit_timed_out_tx_returns_failed(self) -> None:
        mgr = TransactionManager()
        tx = mgr.begin(timeout_seconds=1)
        # Create a backdated copy with created_at set 10 seconds in the past
        backdated = tx.model_copy(
            update={"created_at": datetime.now(tz=timezone.utc) - timedelta(seconds=10)}
        )
        # backdated.state is already pending (copied from tx)
        # Register the backdated transaction so commit can store state updates
        mgr._transactions[backdated.transaction_id] = backdated
        result = mgr.commit(backdated)
        assert result.state == TransactionState.failed
        assert "timed out" in (result.error or "").lower()


# ===========================================================================
# TransactionManager.rollback
# ===========================================================================


class TestTransactionManagerRollback:
    def test_rollback_returns_rolled_back_state(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        result = manager.rollback(pending_tx)
        assert result.state == TransactionState.rolled_back

    def test_rollback_returns_transaction_result(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        result = manager.rollback(pending_tx)
        assert isinstance(result, TransactionResult)

    def test_rollback_calls_compensating_actions(self) -> None:
        calls: list[str] = []
        mgr = TransactionManager(action_handlers={
            "undo_step": lambda action, data: calls.append(action),
        })
        tx = mgr.begin()
        mgr.add_step(tx, "agent", "step", {}, compensating_action="undo_step")
        mgr.rollback(tx)
        assert "undo_step" in calls

    def test_rollback_stores_rolled_back_state(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        manager.rollback(pending_tx)
        stored = manager.get_transaction(pending_tx.transaction_id)
        assert stored is not None
        assert stored.state == TransactionState.rolled_back

    def test_rollback_no_compensating_action_does_not_crash(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        manager.add_step(pending_tx, "agent", "step_without_undo", {})
        result = manager.rollback(pending_tx)
        assert result.state == TransactionState.rolled_back

    def test_rollback_empty_tx_succeeds(
        self, manager: TransactionManager, pending_tx: Transaction
    ) -> None:
        result = manager.rollback(pending_tx)
        assert result.state == TransactionState.rolled_back


# ===========================================================================
# TransactionManager.get_transaction / get_all_transactions
# ===========================================================================


class TestTransactionManagerRegistry:
    def test_get_transaction_returns_correct_tx(self, manager: TransactionManager) -> None:
        tx = manager.begin()
        retrieved = manager.get_transaction(tx.transaction_id)
        assert retrieved is not None
        assert retrieved.transaction_id == tx.transaction_id

    def test_get_transaction_nonexistent_returns_none(self, manager: TransactionManager) -> None:
        assert manager.get_transaction("nonexistent") is None

    def test_get_all_transactions_empty(self) -> None:
        manager = TransactionManager()
        assert manager.get_all_transactions() == []

    def test_get_all_transactions_returns_all(self, manager: TransactionManager) -> None:
        tx1 = manager.begin()
        tx2 = manager.begin()
        all_txs = manager.get_all_transactions()
        ids = [t.transaction_id for t in all_txs]
        assert tx1.transaction_id in ids
        assert tx2.transaction_id in ids

    def test_register_transaction(self) -> None:
        manager = TransactionManager()
        tx = Transaction(
            transaction_id="external-tx-id",
            state=TransactionState.committed,
            created_at=datetime.now(tz=timezone.utc),
        )
        manager.register_transaction(tx)
        retrieved = manager.get_transaction("external-tx-id")
        assert retrieved is not None
        assert retrieved.state == TransactionState.committed


# ===========================================================================
# SagaOrchestrator
# ===========================================================================


class TestSagaOrchestrator:
    def test_register_adds_step(self) -> None:
        saga = SagaOrchestrator()
        saga.register("agent-1", "do_a", {"k": "v"})
        assert len(saga._steps) == 1

    def test_execute_empty_returns_committed(self) -> None:
        saga = SagaOrchestrator()
        result = saga.execute()
        assert result.state == TransactionState.committed

    def test_execute_calls_all_registered_steps(self) -> None:
        calls: list[str] = []
        mgr = TransactionManager(action_handlers={
            "step_a": lambda a, d: calls.append(a),
            "step_b": lambda a, d: calls.append(a),
        })
        saga = SagaOrchestrator(manager=mgr)
        saga.register("agent-1", "step_a", {})
        saga.register("agent-2", "step_b", {})
        result = saga.execute()
        assert result.state == TransactionState.committed
        assert "step_a" in calls
        assert "step_b" in calls

    def test_execute_failure_triggers_rollback(self) -> None:
        def failing_handler(action: str, data: dict) -> None:
            raise RuntimeError("saga step failed")

        mgr = TransactionManager(action_handlers={"bad_step": failing_handler})
        saga = SagaOrchestrator(manager=mgr)
        saga.register("agent", "bad_step", {})
        result = saga.execute()
        assert result.state == TransactionState.rolled_back

    def test_execute_multiple_steps_in_order(self) -> None:
        order: list[str] = []
        mgr = TransactionManager(action_handlers={
            "first": lambda a, d: order.append("first"),
            "second": lambda a, d: order.append("second"),
            "third": lambda a, d: order.append("third"),
        })
        saga = SagaOrchestrator(manager=mgr)
        saga.register("a", "first", {})
        saga.register("b", "second", {})
        saga.register("c", "third", {})
        saga.execute()
        assert order == ["first", "second", "third"]

    def test_execute_with_compensating_actions(self) -> None:
        undo_calls: list[str] = []

        def do_b(action: str, data: dict) -> None:
            raise RuntimeError("step_b always fails")

        mgr = TransactionManager(action_handlers={
            "do_a": lambda a, d: None,
            "do_b": do_b,
            "undo_a": lambda a, d: undo_calls.append(a),
        })
        saga = SagaOrchestrator(manager=mgr)
        saga.register("agent-1", "do_a", {}, compensating_action="undo_a")
        saga.register("agent-2", "do_b", {})
        saga.execute()
        assert "undo_a" in undo_calls

    def test_execute_uses_provided_manager(self) -> None:
        mgr = TransactionManager()
        saga = SagaOrchestrator(manager=mgr)
        saga.register("agent", "action", {})
        saga.execute()
        # Manager should have one transaction
        assert len(mgr.get_all_transactions()) == 1

    def test_saga_default_creates_new_manager(self) -> None:
        saga = SagaOrchestrator()
        assert saga._manager is not None

    def test_execute_result_type(self) -> None:
        saga = SagaOrchestrator()
        result = saga.execute()
        assert isinstance(result, TransactionResult)


# ===========================================================================
# Models
# ===========================================================================


class TestTransactionStateEnum:
    @pytest.mark.parametrize("state, value", [
        (TransactionState.pending, "pending"),
        (TransactionState.active, "active"),
        (TransactionState.committed, "committed"),
        (TransactionState.rolled_back, "rolled_back"),
        (TransactionState.failed, "failed"),
    ])
    def test_enum_values(self, state: TransactionState, value: str) -> None:
        assert state.value == value


class TestTransactionModel:
    def test_default_state_pending(self) -> None:
        tx = Transaction(
            transaction_id="t1",
            created_at=datetime.now(tz=timezone.utc),
        )
        assert tx.state == TransactionState.pending

    def test_default_steps_empty(self) -> None:
        tx = Transaction(
            transaction_id="t1",
            created_at=datetime.now(tz=timezone.utc),
        )
        assert tx.steps == []

    def test_default_timeout_sixty(self) -> None:
        tx = Transaction(
            transaction_id="t1",
            created_at=datetime.now(tz=timezone.utc),
        )
        assert tx.timeout_seconds == 60


class TestTransactionStepModel:
    def test_compensating_action_defaults_none(self) -> None:
        step = TransactionStep(
            step_id="s1",
            agent_id="a",
            action="do",
            data={},
        )
        assert step.compensating_action is None

    def test_data_defaults_empty(self) -> None:
        step = TransactionStep(step_id="s1", agent_id="a", action="do")
        assert step.data == {}


class TestTransactionResultModel:
    def test_defaults_no_error(self) -> None:
        result = TransactionResult(
            transaction_id="t1",
            state=TransactionState.committed,
        )
        assert result.error is None

    def test_defaults_no_failed_step(self) -> None:
        result = TransactionResult(
            transaction_id="t1",
            state=TransactionState.committed,
        )
        assert result.failed_step is None

    def test_defaults_empty_completed_steps(self) -> None:
        result = TransactionResult(
            transaction_id="t1",
            state=TransactionState.committed,
        )
        assert result.completed_steps == []


# ===========================================================================
# Integration tests
# ===========================================================================


class TestIntegrationScenarios:
    def test_full_happy_path(self) -> None:
        events: list[str] = []

        mgr = TransactionManager(action_handlers={
            "create_order": lambda a, d: events.append("create_order"),
            "charge_payment": lambda a, d: events.append("charge_payment"),
            "send_confirmation": lambda a, d: events.append("send_confirmation"),
        })

        tx = mgr.begin(timeout_seconds=120)
        mgr.add_step(tx, "order-service", "create_order", {"item": "widget"})
        mgr.add_step(tx, "payment-service", "charge_payment", {"amount": 9.99})
        mgr.add_step(tx, "email-service", "send_confirmation", {"to": "user@example.com"})

        result = mgr.commit(tx)
        assert result.state == TransactionState.committed
        assert events == ["create_order", "charge_payment", "send_confirmation"]

    def test_partial_failure_compensates_completed_steps(self) -> None:
        compensated: list[str] = []

        def fail_on_third(action: str, data: dict) -> None:
            if action == "step_3":
                raise RuntimeError("third step failed")

        mgr = TransactionManager(action_handlers={
            "step_1": lambda a, d: None,
            "step_2": lambda a, d: None,
            "step_3": fail_on_third,
            "undo_step_1": lambda a, d: compensated.append("undo_1"),
            "undo_step_2": lambda a, d: compensated.append("undo_2"),
        })

        tx = mgr.begin()
        mgr.add_step(tx, "a", "step_1", {}, compensating_action="undo_step_1")
        mgr.add_step(tx, "b", "step_2", {}, compensating_action="undo_step_2")
        mgr.add_step(tx, "c", "step_3", {})

        result = mgr.commit(tx)
        assert result.state == TransactionState.rolled_back
        assert "undo_2" in compensated
        assert "undo_1" in compensated

    def test_multiple_transactions_isolated(self) -> None:
        mgr = TransactionManager()
        tx1 = mgr.begin()
        tx2 = mgr.begin()
        mgr.add_step(tx1, "agent", "action_for_tx1", {})
        result1 = mgr.commit(tx1)
        result2 = mgr.commit(tx2)
        assert result1.state == TransactionState.committed
        assert result2.state == TransactionState.committed
        assert len(result1.completed_steps) == 1
        assert len(result2.completed_steps) == 0

    def test_saga_as_distributed_workflow(self) -> None:
        workflow_log: list[str] = []
        mgr = TransactionManager(action_handlers={
            "reserve_inventory": lambda a, d: workflow_log.append("reserved"),
            "process_payment": lambda a, d: workflow_log.append("paid"),
            "ship_order": lambda a, d: workflow_log.append("shipped"),
            "cancel_reservation": lambda a, d: workflow_log.append("cancelled"),
            "refund_payment": lambda a, d: workflow_log.append("refunded"),
        })
        saga = SagaOrchestrator(manager=mgr)
        saga.register("inventory", "reserve_inventory", {}, compensating_action="cancel_reservation")
        saga.register("payments", "process_payment", {}, compensating_action="refund_payment")
        saga.register("shipping", "ship_order", {})
        result = saga.execute()
        assert result.state == TransactionState.committed
        assert workflow_log == ["reserved", "paid", "shipped"]
