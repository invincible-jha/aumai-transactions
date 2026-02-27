"""Core logic for aumai-transactions."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from aumai_transactions.models import (
    Transaction,
    TransactionResult,
    TransactionState,
    TransactionStep,
)

__all__ = ["TransactionManager", "SagaOrchestrator"]

# Type alias for action handlers: action name -> handler function
ActionHandler = Callable[[str, dict[str, object]], None]


class TransactionManager:
    """Create, manage, and execute ACID-like multi-agent transactions.

    Steps are executed synchronously in order.  On failure, all previously
    completed steps are compensated in reverse order (saga-style rollback).

    Args:
        action_handlers: Optional mapping of action name to callable.  When
            provided, :meth:`commit` calls the handler for each step.  When
            not provided (the default), actions are recorded but not executed —
            useful for dry-run or testing scenarios.
    """

    def __init__(
        self, action_handlers: dict[str, ActionHandler] | None = None
    ) -> None:
        self._handlers: dict[str, ActionHandler] = action_handlers or {}
        self._transactions: dict[str, Transaction] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def begin(self, timeout_seconds: int = 60) -> Transaction:
        """Create a new transaction in the *pending* state.

        Args:
            timeout_seconds: Maximum lifetime before the transaction is
                considered timed out.

        Returns:
            The newly created :class:`~aumai_transactions.models.Transaction`.
        """
        transaction_id = str(uuid.uuid4())
        tx = Transaction(
            transaction_id=transaction_id,
            state=TransactionState.pending,
            created_at=datetime.now(tz=timezone.utc),
            timeout_seconds=timeout_seconds,
        )
        self._transactions[transaction_id] = tx
        return tx

    def add_step(
        self,
        tx: Transaction,
        agent_id: str,
        action: str,
        data: dict[str, object],
        compensating_action: str | None = None,
    ) -> TransactionStep:
        """Append a step to *tx*.

        Args:
            tx: The transaction to extend.
            agent_id: Agent responsible for this step.
            action: Action descriptor string.
            data: Payload for the action.
            compensating_action: Optional undo action for rollback.

        Returns:
            The newly created :class:`~aumai_transactions.models.TransactionStep`.

        Raises:
            ValueError: When *tx* is not in the *pending* state.
        """
        if tx.state != TransactionState.pending:
            raise ValueError(
                f"Cannot add steps to transaction {tx.transaction_id!r} "
                f"in state {tx.state.value!r}; only 'pending' transactions accept new steps."
            )

        step = TransactionStep(
            step_id=str(uuid.uuid4()),
            agent_id=agent_id,
            action=action,
            data=data,
            compensating_action=compensating_action,
        )
        tx.steps.append(step)
        self._transactions[tx.transaction_id] = tx
        return step

    def commit(self, tx: Transaction) -> TransactionResult:
        """Execute all steps in order, rolling back on any failure.

        The transaction transitions to *active* before execution begins, and
        then to either *committed* or *rolled_back* when finished.

        Args:
            tx: The transaction to commit.

        Returns:
            A :class:`~aumai_transactions.models.TransactionResult` describing the outcome.

        Raises:
            ValueError: When *tx* is not in *pending* state.
        """
        if tx.state != TransactionState.pending:
            raise ValueError(
                f"Transaction {tx.transaction_id!r} is in state {tx.state.value!r}; "
                "only 'pending' transactions can be committed."
            )

        self._set_state(tx, TransactionState.active)

        # Check timeout
        if self._is_timed_out(tx):
            self._set_state(tx, TransactionState.failed)
            return TransactionResult(
                transaction_id=tx.transaction_id,
                state=TransactionState.failed,
                error="Transaction timed out before commit",
            )

        completed_steps: list[str] = []

        for step in tx.steps:
            try:
                self._execute_step(step)
                completed_steps.append(step.step_id)
            except Exception as exc:  # noqa: BLE001
                # Roll back all previously completed steps in reverse order
                rollback_result = self._execute_rollback(tx, completed_steps)
                self._set_state(tx, TransactionState.rolled_back)
                return TransactionResult(
                    transaction_id=tx.transaction_id,
                    state=TransactionState.rolled_back,
                    completed_steps=rollback_result,
                    failed_step=step.step_id,
                    error=str(exc),
                )

        self._set_state(tx, TransactionState.committed)
        return TransactionResult(
            transaction_id=tx.transaction_id,
            state=TransactionState.committed,
            completed_steps=completed_steps,
        )

    def rollback(self, tx: Transaction) -> TransactionResult:
        """Execute compensating actions for all steps in reverse order.

        This can be called on a *pending* or *active* transaction.

        Args:
            tx: The transaction to roll back.

        Returns:
            A :class:`~aumai_transactions.models.TransactionResult` in *rolled_back* state.
        """
        all_step_ids = [step.step_id for step in tx.steps]
        compensated = self._execute_rollback(tx, all_step_ids)
        self._set_state(tx, TransactionState.rolled_back)
        return TransactionResult(
            transaction_id=tx.transaction_id,
            state=TransactionState.rolled_back,
            completed_steps=compensated,
        )

    def get_transaction(self, transaction_id: str) -> Transaction | None:
        """Return the transaction with *transaction_id*, or *None*.

        Args:
            transaction_id: The transaction identifier.

        Returns:
            The :class:`~aumai_transactions.models.Transaction`, or *None*.
        """
        return self._transactions.get(transaction_id)

    def get_all_transactions(self) -> list[Transaction]:
        """Return all transactions held by this manager.

        Returns:
            A list of all :class:`~aumai_transactions.models.Transaction` objects.
        """
        return list(self._transactions.values())

    def register_transaction(self, tx: Transaction) -> None:
        """Insert an existing transaction into the manager registry.

        This is primarily used to restore state from persistent storage.

        Args:
            tx: The transaction to register.
        """
        self._transactions[tx.transaction_id] = tx

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _execute_step(self, step: TransactionStep) -> None:
        """Call the registered handler for *step.action* if one exists."""
        handler = self._handlers.get(step.action)
        if handler is not None:
            handler(step.action, step.data)

    def _execute_rollback(
        self, tx: Transaction, completed_step_ids: list[str]
    ) -> list[str]:
        """Execute compensating actions for completed steps in reverse order."""
        completed_set = set(completed_step_ids)
        compensated: list[str] = []

        for step in reversed(tx.steps):
            if step.step_id not in completed_set:
                continue
            if step.compensating_action is not None:
                handler = self._handlers.get(step.compensating_action)
                if handler is not None:
                    try:
                        handler(step.compensating_action, step.data)
                    except Exception:  # noqa: BLE001
                        pass  # Best-effort compensation
            compensated.append(step.step_id)

        return compensated

    def _set_state(self, tx: Transaction, state: TransactionState) -> None:
        """Update the transaction state in-place and persist the change in the registry.

        Pydantic v2 models are mutable by default, so we assign directly to
        ``tx.state``.  All callers hold a reference to the same ``tx`` object
        and therefore observe the updated state immediately.  The registry is
        updated to point at that same object so that lookups via
        :meth:`get_transaction` are also consistent.

        Choosing in-place mutation as the single pattern avoids the footgun of
        returning a stale copy to the caller while storing a different copy in
        the registry.
        """
        tx.state = state  # type: ignore[assignment]
        self._transactions[tx.transaction_id] = tx

    def _is_timed_out(self, tx: Transaction) -> bool:
        """Return True if the transaction has exceeded its timeout."""
        deadline = tx.created_at + timedelta(seconds=tx.timeout_seconds)
        return datetime.now(tz=timezone.utc) > deadline


class SagaOrchestrator:
    """Choreography-based saga pattern for distributed multi-agent operations.

    Each participant registers its forward action and compensating action.
    The orchestrator sequences them and rolls back on failure.

    Args:
        manager: The underlying :class:`TransactionManager` to use.
    """

    def __init__(self, manager: TransactionManager | None = None) -> None:
        self._manager: TransactionManager = manager or TransactionManager()
        self._steps: list[tuple[str, str, dict[str, object], str | None]] = []

    def register(
        self,
        agent_id: str,
        action: str,
        data: dict[str, object],
        compensating_action: str | None = None,
    ) -> None:
        """Register a saga participant step.

        Args:
            agent_id: Participant agent identifier.
            action: Action to execute.
            data: Action payload.
            compensating_action: Undo action for rollback.
        """
        self._steps.append((agent_id, action, data, compensating_action))

    def execute(self, timeout_seconds: int = 60) -> TransactionResult:
        """Execute all registered steps as a single saga transaction.

        Args:
            timeout_seconds: Transaction timeout.

        Returns:
            The :class:`~aumai_transactions.models.TransactionResult`.
        """
        tx = self._manager.begin(timeout_seconds=timeout_seconds)
        for agent_id, action, data, compensating_action in self._steps:
            self._manager.add_step(
                tx,
                agent_id=agent_id,
                action=action,
                data=data,
                compensating_action=compensating_action,
            )
        return self._manager.commit(tx)
