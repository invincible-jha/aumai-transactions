# API Reference — aumai-transactions

Complete reference for all public classes, functions, and Pydantic models in `aumai_transactions`.

---

## Module: `aumai_transactions`

Top-level public exports:

```python
from aumai_transactions import (
    SagaOrchestrator,
    TransactionManager,
    Transaction,
    TransactionResult,
    TransactionState,
    TransactionStep,
)
```

Package version: `aumai_transactions.__version__` (currently `"0.1.0"`).

---

## Type alias

```python
ActionHandler = Callable[[str, dict[str, object]], None]
```

Type alias for action handler callables. A handler receives the action name (str) and the step data payload (dict). Return value is ignored. Raising any exception causes the transaction to roll back.

---

## Classes

### `TransactionManager`

```
aumai_transactions.core.TransactionManager
```

Create, manage, and execute ACID-like multi-agent transactions. Steps are executed synchronously in declaration order. On any failure, all completed steps are compensated in reverse order (saga-style rollback).

**Constructor**

```python
TransactionManager(
    action_handlers: dict[str, ActionHandler] | None = None
)
```

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `action_handlers` | `dict[str, ActionHandler] \| None` | `None` | Mapping of action name string to callable. When `None` or when an action name is not in the dict, the step is recorded but no code runs. |

**Example**

```python
from aumai_transactions import TransactionManager

def reserve(action: str, data: dict) -> None:
    print(f"Reserving: {data}")

def cancel(action: str, data: dict) -> None:
    print(f"Cancelling: {data}")

manager = TransactionManager(action_handlers={
    "reserve_seat": reserve,
    "cancel_seat": cancel,
})
```

---

#### `TransactionManager.begin`

```python
def begin(self, timeout_seconds: int = 60) -> Transaction
```

Create a new `Transaction` in `pending` state.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeout_seconds` | `int` | `60` | Maximum seconds the transaction may live before being considered timed out. Evaluated once at `commit()` time. |

**Returns**

`Transaction` — a freshly created transaction with a UUID `transaction_id`, `state=pending`, and `created_at=now(UTC)`.

**Side effects**

The new transaction is added to the internal registry (accessible via `get_transaction()`).

**Example**

```python
tx = manager.begin(timeout_seconds=120)
print(tx.transaction_id)  # UUID string
print(tx.state.value)     # "pending"
```

---

#### `TransactionManager.add_step`

```python
def add_step(
    self,
    tx: Transaction,
    agent_id: str,
    action: str,
    data: dict[str, object],
    compensating_action: str | None = None,
) -> TransactionStep
```

Append a step to an existing pending transaction.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tx` | `Transaction` | required | The transaction to extend. Must be in `pending` state. |
| `agent_id` | `str` | required | Identifier of the agent responsible for this step. Informational only — does not affect routing. |
| `action` | `str` | required | Action descriptor. Must match a key in `action_handlers` for the handler to be invoked. |
| `data` | `dict[str, object]` | required | Payload passed to the action handler and to the compensating action handler. |
| `compensating_action` | `str \| None` | `None` | Action name to execute during rollback if this step has already completed. |

**Returns**

`TransactionStep` — the newly created step with a UUID `step_id`.

**Raises**

`ValueError` — if `tx.state` is not `pending`.

**Example**

```python
step = manager.add_step(
    tx,
    agent_id="billing_agent",
    action="charge_card",
    data={"user_id": "u123", "amount": 99.00, "currency": "USD"},
    compensating_action="refund_card",
)
print(step.step_id)  # UUID string
```

---

#### `TransactionManager.commit`

```python
def commit(self, tx: Transaction) -> TransactionResult
```

Execute all steps in declaration order, rolling back on any failure.

Execution flow:
1. Validate `tx.state == pending`; raise `ValueError` otherwise.
2. Transition `tx` to `active`.
3. Check for timeout; return `failed` result if timed out.
4. Execute each step's action handler in order.
5. If all steps succeed: transition to `committed`, return `TransactionResult(state=committed)`.
6. If any step raises: run `_execute_rollback()` for completed steps in reverse, transition to `rolled_back`, return `TransactionResult(state=rolled_back, failed_step=..., error=...)`.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `tx` | `Transaction` | The pending transaction to commit. |

**Returns**

`TransactionResult` — the outcome. `state` will be one of `committed`, `rolled_back`, or `failed`.

**Raises**

`ValueError` — if `tx.state` is not `pending`.

**Example**

```python
result = manager.commit(tx)

if result.state.value == "committed":
    print(f"All {len(result.completed_steps)} steps completed.")
elif result.state.value == "rolled_back":
    print(f"Failed at: {result.failed_step}")
    print(f"Error: {result.error}")
```

---

#### `TransactionManager.rollback`

```python
def rollback(self, tx: Transaction) -> TransactionResult
```

Manually trigger rollback for all steps in the transaction. Safe to call on `pending` or `active` transactions.

Unlike automatic rollback during `commit()` (which only compensates completed steps), `rollback()` attempts to compensate all steps regardless of their execution status.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `tx` | `Transaction` | The transaction to roll back. |

**Returns**

`TransactionResult` — with `state=rolled_back` and `completed_steps` listing which step IDs had their compensation invoked.

**Example**

```python
# Abort before committing
result = manager.rollback(tx)
print(result.state.value)  # "rolled_back"
```

---

#### `TransactionManager.get_transaction`

```python
def get_transaction(self, transaction_id: str) -> Transaction | None
```

Retrieve a transaction from the registry by ID.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `transaction_id` | `str` | The UUID string identifying the transaction. |

**Returns**

`Transaction | None` — the transaction object, or `None` if not found.

---

#### `TransactionManager.get_all_transactions`

```python
def get_all_transactions(self) -> list[Transaction]
```

Return all transactions currently held in the registry.

**Returns**

`list[Transaction]` — a snapshot copy. Order is not guaranteed.

---

#### `TransactionManager.register_transaction`

```python
def register_transaction(self, tx: Transaction) -> None
```

Insert an existing `Transaction` object into the manager registry. Used primarily to restore persisted state from disk.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `tx` | `Transaction` | The transaction to register. |

**Example**

```python
# Restore from JSON
import json
from aumai_transactions.models import Transaction

with open("state.json") as f:
    for entry in json.load(f):
        tx = Transaction.model_validate(entry)
        manager.register_transaction(tx)
```

---

### `SagaOrchestrator`

```
aumai_transactions.core.SagaOrchestrator
```

Choreography-based saga orchestrator. Provides a fluent registration API: register participant steps with `register()`, then execute the entire saga with `execute()`. Internally creates and commits a `Transaction` via the underlying `TransactionManager`.

**Constructor**

```python
SagaOrchestrator(manager: TransactionManager | None = None)
```

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `manager` | `TransactionManager \| None` | `None` | The `TransactionManager` to use. When `None`, a new `TransactionManager()` is created (no handlers — dry-run mode). |

---

#### `SagaOrchestrator.register`

```python
def register(
    self,
    agent_id: str,
    action: str,
    data: dict[str, object],
    compensating_action: str | None = None,
) -> None
```

Register a participant step. Steps are executed in registration order.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `agent_id` | `str` | required | Participant agent identifier. |
| `action` | `str` | required | Action to execute. |
| `data` | `dict[str, object]` | required | Action payload. |
| `compensating_action` | `str \| None` | `None` | Undo action for rollback. |

---

#### `SagaOrchestrator.execute`

```python
def execute(self, timeout_seconds: int = 60) -> TransactionResult
```

Execute all registered steps as a single transaction.

Internally calls `manager.begin()`, then `manager.add_step()` for each registered step, then `manager.commit()`.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeout_seconds` | `int` | `60` | Transaction timeout. |

**Returns**

`TransactionResult` — the outcome of the saga execution.

**Example**

```python
from aumai_transactions import SagaOrchestrator, TransactionManager

manager = TransactionManager(action_handlers=handlers)
saga = SagaOrchestrator(manager)

saga.register("agent_a", "action_a", {"key": "val"}, "undo_a")
saga.register("agent_b", "action_b", {"key": "val"}, "undo_b")

result = saga.execute(timeout_seconds=30)
print(result.state.value)
```

---

## Models

### `TransactionState`

```
aumai_transactions.models.TransactionState
```

String enum. Lifecycle states for a multi-agent transaction.

| Value | Meaning |
|---|---|
| `pending` | Transaction created; steps can be added; not yet executing. |
| `active` | `commit()` called; execution in progress. |
| `committed` | All steps completed successfully. |
| `rolled_back` | A step failed; compensating actions were executed. |
| `failed` | Transaction exceeded its timeout before execution. |

**Example**

```python
from aumai_transactions.models import TransactionState

state = TransactionState.pending
print(state.value)   # "pending"
print(state == "pending")  # True (str enum)
```

---

### `TransactionStep`

```
aumai_transactions.models.TransactionStep
```

Pydantic model. A single unit of work within a transaction.

| Field | Type | Required | Description |
|---|---|---|---|
| `step_id` | `str` | Yes | UUID string. Auto-assigned by `TransactionManager.add_step()`. |
| `agent_id` | `str` | Yes | ID of the agent responsible for this step. |
| `action` | `str` | Yes | Action descriptor. Looked up in `action_handlers`. |
| `data` | `dict[str, object]` | Yes | Payload passed to the action and compensating action handlers. Default: `{}`. |
| `compensating_action` | `str \| None` | No | Action name to execute during rollback. `None` means no compensation for this step. |

---

### `Transaction`

```
aumai_transactions.models.Transaction
```

Pydantic model. An ordered sequence of steps that execute atomically.

| Field | Type | Required | Description |
|---|---|---|---|
| `transaction_id` | `str` | Yes | UUID string. Auto-assigned by `TransactionManager.begin()`. |
| `steps` | `list[TransactionStep]` | Yes | Ordered list of steps. Grows as `add_step()` is called. |
| `state` | `TransactionState` | Yes | Current lifecycle state. Default: `pending`. |
| `created_at` | `datetime` | Yes | UTC timestamp of creation. |
| `timeout_seconds` | `int` | Yes | Maximum allowed lifetime. Default: `60`. |

**Example**

```python
# Serialize for storage
data = tx.model_dump(mode="json")

# Restore
from aumai_transactions.models import Transaction
restored_tx = Transaction.model_validate(data)
```

---

### `TransactionResult`

```
aumai_transactions.models.TransactionResult
```

Pydantic model. Final outcome of a `commit()` or `rollback()` operation.

| Field | Type | Required | Description |
|---|---|---|---|
| `transaction_id` | `str` | Yes | ID of the transaction. |
| `state` | `TransactionState` | Yes | Final state: `committed`, `rolled_back`, or `failed`. |
| `completed_steps` | `list[str]` | Yes | Step IDs that completed successfully (or were compensated during rollback). Default: `[]`. |
| `failed_step` | `str \| None` | No | Step ID that caused the failure, if any. `None` for committed transactions. |
| `error` | `str \| None` | No | Error message from the failing step handler, if any. |

**Example**

```python
result = manager.commit(tx)

# Check outcome
match result.state:
    case TransactionState.committed:
        print(f"Success: {len(result.completed_steps)} steps")
    case TransactionState.rolled_back:
        print(f"Rolled back. Failed: {result.failed_step}. Error: {result.error}")
    case TransactionState.failed:
        print(f"Timed out: {result.error}")
```

---

## CLI Commands

### `aumai-transactions create`

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--timeout` | `int` | No | `60` | Transaction timeout in seconds |

Creates a new `pending` transaction, saves it to `~/.aumai/transactions/transactions.json`, and prints a JSON summary.

### `aumai-transactions status`

| Option | Type | Required | Description |
|---|---|---|---|
| `--tx-id` | `str` | Yes | Transaction UUID to query |

Reads the transaction from `~/.aumai/transactions/transactions.json` and prints a JSON summary with `transaction_id`, `state`, `steps` (count), `created_at`, and `timeout_seconds`.

Raises a `ClickException` when the transaction ID is not found.

---

## Rollback behavior reference

| Situation | What happens |
|---|---|
| Step N raises | Steps 0..N-1 are compensated in reverse order (N-1, N-2, ..., 0). Step N is NOT compensated. |
| Compensation handler raises | Error is silently swallowed. Remaining compensations continue. |
| Step has no compensating action | Step is skipped during rollback — no compensation executed. |
| `rollback()` called manually | All steps (in reverse) are attempted for compensation, regardless of execution status. |
| Transaction timed out | No steps are executed; result state is `failed`, not `rolled_back`. |
