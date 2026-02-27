"""Quickstart examples for aumai-transactions.

Demonstrates ACID-like transaction semantics for multi-agent operations:
  1. Successful commit (all steps pass)
  2. Automatic rollback on step failure
  3. Manual rollback before commit
  4. SagaOrchestrator high-level API
  5. Dry-run mode (no action handlers)

Run directly:
    python examples/quickstart.py
"""

from __future__ import annotations

from aumai_transactions import (
    SagaOrchestrator,
    TransactionManager,
    TransactionState,
)
from aumai_transactions.models import TransactionResult

# ---------------------------------------------------------------------------
# Shared action handlers
# ---------------------------------------------------------------------------

_log: list[str] = []   # Execution trace, for assertions


def _make_handler(label: str, *, fail: bool = False):
    """Factory that returns an action handler which logs calls and optionally fails."""
    def handler(action: str, data: dict) -> None:
        entry = f"[{label}] action={action} data={data}"
        _log.append(entry)
        print(f"  {entry}")
        if fail:
            raise RuntimeError(f"Simulated failure in {label}")
    return handler


# Forward actions
handle_create_user = _make_handler("create_user")
handle_init_quota = _make_handler("init_quota")
handle_send_email = _make_handler("send_email")
handle_charge_card = _make_handler("charge_card")

# Compensating actions
handle_delete_user = _make_handler("delete_user [UNDO]")
handle_reset_quota = _make_handler("reset_quota [UNDO]")
handle_cancel_email = _make_handler("cancel_email [UNDO]")
handle_refund_card = _make_handler("refund_card [UNDO]")

# A handler that always fails (for rollback demos)
handle_send_email_broken = _make_handler("send_email_BROKEN", fail=True)


def _build_manager(broken_email: bool = False) -> TransactionManager:
    """Build a TransactionManager with all handlers registered."""
    return TransactionManager(action_handlers={
        "create_user":   handle_create_user,
        "delete_user":   handle_delete_user,
        "init_quota":    handle_init_quota,
        "reset_quota":   handle_reset_quota,
        "send_email":    handle_send_email_broken if broken_email else handle_send_email,
        "cancel_email":  handle_cancel_email,
        "charge_card":   handle_charge_card,
        "refund_card":   handle_refund_card,
    })


def _print_result(result: TransactionResult) -> None:
    """Print a transaction result summary."""
    print(f"  State          : {result.state.value}")
    print(f"  Completed steps: {len(result.completed_steps)}")
    if result.failed_step:
        print(f"  Failed step    : {result.failed_step}")
        print(f"  Error          : {result.error}")


# ---------------------------------------------------------------------------
# Demo 1: Successful commit
# ---------------------------------------------------------------------------


def demo_successful_commit() -> None:
    """Build a 3-step transaction and commit it successfully."""
    print("\n=== Demo 1: Successful Commit ===")
    _log.clear()

    manager = _build_manager(broken_email=False)
    tx = manager.begin(timeout_seconds=60)

    user_payload = {"user_id": "u-001", "email": "alice@example.com"}

    manager.add_step(tx, "user_service",  "create_user", user_payload, "delete_user")
    manager.add_step(tx, "quota_service", "init_quota",  user_payload, "reset_quota")
    manager.add_step(tx, "email_service", "send_email",  user_payload, "cancel_email")

    print(f"  Transaction ID : {tx.transaction_id}")
    print(f"  Steps added    : {len(tx.steps)}")
    print("\n  Executing...")
    result = manager.commit(tx)

    print("\n  Result:")
    _print_result(result)

    assert result.state == TransactionState.committed
    assert len(result.completed_steps) == 3
    assert result.failed_step is None
    print("\n  Assertions passed.")


# ---------------------------------------------------------------------------
# Demo 2: Automatic rollback on failure
# ---------------------------------------------------------------------------


def demo_automatic_rollback() -> None:
    """Demonstrate that when the email step fails, prior steps are compensated."""
    print("\n=== Demo 2: Automatic Rollback on Step Failure ===")
    _log.clear()

    manager = _build_manager(broken_email=True)   # email handler will raise
    tx = manager.begin(timeout_seconds=60)

    user_payload = {"user_id": "u-002", "email": "bob@example.com"}

    manager.add_step(tx, "user_service",  "create_user", user_payload, "delete_user")
    manager.add_step(tx, "quota_service", "init_quota",  user_payload, "reset_quota")
    manager.add_step(tx, "email_service", "send_email",  user_payload, "cancel_email")

    print("  Executing (email step will fail)...")
    result = manager.commit(tx)

    print("\n  Result:")
    _print_result(result)

    # Forward steps that ran: create_user, init_quota
    # Compensation steps that ran: reset_quota, delete_user (reverse order)
    # Email's cancel_email should NOT run (it never completed)
    forward_calls = [e for e in _log if "[UNDO]" not in e]
    undo_calls = [e for e in _log if "[UNDO]" in e]

    print(f"\n  Forward steps executed : {len(forward_calls)}")
    print(f"  Compensations executed  : {len(undo_calls)}")

    assert result.state == TransactionState.rolled_back
    assert result.error == "Simulated failure in send_email_BROKEN"
    assert len(undo_calls) == 2   # reset_quota + delete_user
    print("\n  Assertions passed.")


# ---------------------------------------------------------------------------
# Demo 3: Manual rollback before commit
# ---------------------------------------------------------------------------


def demo_manual_rollback() -> None:
    """Abort a transaction explicitly before committing."""
    print("\n=== Demo 3: Manual Rollback Before Commit ===")
    _log.clear()

    manager = _build_manager()
    tx = manager.begin(timeout_seconds=60)

    manager.add_step(tx, "user_service", "create_user", {"user_id": "u-003"}, "delete_user")
    manager.add_step(tx, "quota_service", "init_quota", {"user_id": "u-003"}, "reset_quota")

    print(f"  Transaction state before rollback: {tx.state.value}")
    result = manager.rollback(tx)
    print(f"  Transaction state after rollback : {tx.state.value}")

    print("\n  Result:")
    _print_result(result)

    # Manual rollback runs compensations for ALL steps even though none executed
    # (treat all as completed during a manual abort)
    assert result.state == TransactionState.rolled_back
    print("\n  Assertions passed.")


# ---------------------------------------------------------------------------
# Demo 4: SagaOrchestrator — high-level choreography
# ---------------------------------------------------------------------------


def demo_saga_orchestrator() -> None:
    """Use SagaOrchestrator for a cleaner multi-participant saga."""
    print("\n=== Demo 4: SagaOrchestrator ===")
    _log.clear()

    manager = _build_manager(broken_email=False)
    saga = SagaOrchestrator(manager)

    trip_data = {"booking_ref": "BK-9999", "user_id": "u-004"}

    saga.register("flight_agent",  "charge_card",  {"amount": 500, **trip_data}, "refund_card")
    saga.register("hotel_agent",   "charge_card",  {"amount": 350, **trip_data}, "refund_card")
    saga.register("email_service", "send_email",   trip_data,                    "cancel_email")

    print("  Executing saga...")
    result = saga.execute(timeout_seconds=30)

    print("\n  Result:")
    _print_result(result)

    assert result.state == TransactionState.committed
    assert len(result.completed_steps) == 3
    print("\n  Assertions passed.")


# ---------------------------------------------------------------------------
# Demo 5: Dry-run / no handlers
# ---------------------------------------------------------------------------


def demo_dry_run() -> None:
    """Create and commit a transaction without any action handlers (dry run)."""
    print("\n=== Demo 5: Dry-Run Mode (no action handlers) ===")

    # No handlers: steps are recorded and sequenced but nothing executes
    manager = TransactionManager()

    tx = manager.begin(timeout_seconds=60)
    manager.add_step(tx, "agent_a", "action_a", {"payload": 1}, "undo_a")
    manager.add_step(tx, "agent_b", "action_b", {"payload": 2}, "undo_b")
    manager.add_step(tx, "agent_c", "action_c", {"payload": 3})   # no compensation

    result = manager.commit(tx)

    print(f"  State          : {result.state.value}")
    print(f"  Completed steps: {len(result.completed_steps)}")

    assert result.state == TransactionState.committed
    assert len(result.completed_steps) == 3
    print("  Dry-run assertions passed — no side effects executed.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all quickstart demos in sequence."""
    print("aumai-transactions quickstart")
    print("=" * 50)

    demo_successful_commit()
    demo_automatic_rollback()
    demo_manual_rollback()
    demo_saga_orchestrator()
    demo_dry_run()

    print("\n" + "=" * 50)
    print("All demos completed successfully.")


if __name__ == "__main__":
    main()
