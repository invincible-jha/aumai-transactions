"""Pydantic models for aumai-transactions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "TransactionState",
    "TransactionStep",
    "Transaction",
    "TransactionResult",
]


class TransactionState(str, Enum):
    """Lifecycle states for a multi-agent transaction."""

    pending = "pending"
    active = "active"
    committed = "committed"
    rolled_back = "rolled_back"
    failed = "failed"


class TransactionStep(BaseModel):
    """A single unit of work within a transaction, with its compensating action."""

    step_id: str = Field(..., description="Unique identifier for this step")
    agent_id: str = Field(..., description="ID of the agent responsible for executing this step")
    action: str = Field(..., description="Opaque action descriptor (e.g. 'send_email')")
    data: dict[str, object] = Field(
        default_factory=dict, description="Payload passed to the action handler"
    )
    compensating_action: str | None = Field(
        default=None,
        description="Action to execute if the transaction is rolled back after this step succeeds",
    )


class Transaction(BaseModel):
    """An ordered sequence of steps that should execute atomically."""

    transaction_id: str = Field(..., description="Unique identifier for this transaction")
    steps: list[TransactionStep] = Field(
        default_factory=list, description="Ordered list of steps to execute"
    )
    state: TransactionState = Field(
        default=TransactionState.pending, description="Current lifecycle state"
    )
    created_at: datetime = Field(..., description="UTC timestamp when the transaction was created")
    timeout_seconds: int = Field(
        default=60, description="Maximum seconds the transaction may remain in the active state"
    )


class TransactionResult(BaseModel):
    """Final outcome of a transaction commit or rollback."""

    transaction_id: str = Field(..., description="ID of the transaction")
    state: TransactionState = Field(..., description="Final state of the transaction")
    completed_steps: list[str] = Field(
        default_factory=list, description="Step IDs that completed successfully"
    )
    failed_step: str | None = Field(
        default=None, description="ID of the step that caused a failure, if any"
    )
    error: str | None = Field(
        default=None, description="Error message from the failing step, if any"
    )
