"""CLI entry point for aumai-transactions."""

from __future__ import annotations

import json
from pathlib import Path

import click

from aumai_transactions.core import TransactionManager
from aumai_transactions.models import Transaction

# Persistent store path for CLI use
_DEFAULT_STATE_DIR = Path.home() / ".aumai" / "transactions"
_DEFAULT_STATE_FILE = _DEFAULT_STATE_DIR / "transactions.json"


def _load_manager() -> TransactionManager:
    """Load a TransactionManager with persisted transaction state."""
    manager = TransactionManager()
    if _DEFAULT_STATE_FILE.exists():
        raw: list[dict[str, object]] = json.loads(
            _DEFAULT_STATE_FILE.read_text(encoding="utf-8")
        )
        for entry in raw:
            tx = Transaction.model_validate(entry)
            manager.register_transaction(tx)
    return manager


def _save_manager(manager: TransactionManager) -> None:
    """Persist transaction state to disk."""
    _DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = [tx.model_dump(mode="json") for tx in manager.get_all_transactions()]
    _DEFAULT_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


@click.group()
@click.version_option()
def main() -> None:
    """AumAI Transactions — ACID-like transactions for multi-agent operations."""


@main.command("create")
@click.option(
    "--timeout",
    "timeout_seconds",
    default=60,
    show_default=True,
    type=int,
    help="Transaction timeout in seconds.",
)
def create_cmd(timeout_seconds: int) -> None:
    """Create a new pending transaction and print its ID."""
    manager = _load_manager()
    tx = manager.begin(timeout_seconds=timeout_seconds)
    _save_manager(manager)

    click.echo(
        json.dumps(
            {
                "transaction_id": tx.transaction_id,
                "state": tx.state.value,
                "created_at": tx.created_at.isoformat(),
                "timeout_seconds": tx.timeout_seconds,
            },
            indent=2,
        )
    )


@main.command("status")
@click.option("--tx-id", required=True, help="The transaction ID to query.")
def status_cmd(tx_id: str) -> None:
    """Display the current status of a transaction."""
    manager = _load_manager()
    tx = manager.get_transaction(tx_id)
    if tx is None:
        raise click.ClickException(f"Transaction not found: {tx_id}")

    click.echo(
        json.dumps(
            {
                "transaction_id": tx.transaction_id,
                "state": tx.state.value,
                "steps": len(tx.steps),
                "created_at": tx.created_at.isoformat(),
                "timeout_seconds": tx.timeout_seconds,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
