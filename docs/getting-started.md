# Getting Started with aumai-transactions

ACID-like transactions for multi-agent operations: build, commit, and automatically roll back multi-step agent workflows.

---

## Prerequisites

- Python 3.11 or later
- `pip` (comes with Python)
- Basic familiarity with the concept of multi-step workflows

No external services, databases, or message brokers are required.

---

## Installation

### From PyPI (recommended)

```bash
pip install aumai-transactions
```

Verify:

```bash
aumai-transactions --version
```

### From source

```bash
git clone https://github.com/aumai/aumai-transactions
cd aumai-transactions
pip install -e .
```

### Development mode (with test dependencies)

```bash
pip install -e ".[dev]"
pytest
```

---

## Your First Transaction

This tutorial walks through the complete lifecycle of a multi-agent transaction: begin, add steps, commit, and observe rollback on failure.

### Scenario

You are building a user onboarding workflow with three steps:

1. **Create user record** (agent: `user_service`)
2. **Initialize quota** (agent: `quota_service`)
3. **Send welcome email** (agent: `email_service`)

If any step fails, all previously completed steps should be undone.

### Step 1 — Define action handlers

Action handlers are plain Python callables. Each receives the action name and a data dict:

```python
# handlers.py

def create_user(action: str, data: dict) -> None:
    print(f"[user_service] Creating user: {data['user_id']}")
    # In a real system: POST to user service API

def delete_user(action: str, data: dict) -> None:
    print(f"[user_service] Deleting user: {data['user_id']} (compensation)")

def init_quota(action: str, data: dict) -> None:
    print(f"[quota_service] Initializing quota for: {data['user_id']}")

def reset_quota(action: str, data: dict) -> None:
    print(f"[quota_service] Resetting quota for: {data['user_id']} (compensation)")

def send_welcome(action: str, data: dict) -> None:
    print(f"[email_service] Sending welcome email to: {data['email']}")
    # Simulate a failure:
    raise RuntimeError("SMTP server unavailable")

def cancel_welcome(action: str, data: dict) -> None:
    print(f"[email_service] Cancelling welcome email for: {data['email']} (compensation)")
```

### Step 2 — Build and commit the transaction

```python
from aumai_transactions import TransactionManager
from handlers import (
    create_user, delete_user,
    init_quota, reset_quota,
    send_welcome, cancel_welcome,
)

manager = TransactionManager(action_handlers={
    "create_user": create_user,
    "delete_user": delete_user,
    "init_quota": init_quota,
    "reset_quota": reset_quota,
    "send_welcome": send_welcome,
    "cancel_welcome": cancel_welcome,
})

# Step 1: begin a new transaction
tx = manager.begin(timeout_seconds=60)
print(f"Transaction ID: {tx.transaction_id}, State: {tx.state.value}")

# Step 2: add steps with compensating actions
user_data = {"user_id": "u-001", "email": "alice@example.com"}

manager.add_step(
    tx,
    agent_id="user_service",
    action="create_user",
    data=user_data,
    compensating_action="delete_user",
)

manager.add_step(
    tx,
    agent_id="quota_service",
    action="init_quota",
    data=user_data,
    compensating_action="reset_quota",
)

manager.add_step(
    tx,
    agent_id="email_service",
    action="send_welcome",
    data=user_data,
    compensating_action="cancel_welcome",
)

# Step 3: commit
result = manager.commit(tx)
```

### Step 3 — Observe the output

Because `send_welcome` raises a `RuntimeError`, the output will be:

```
Transaction ID: ..., State: pending
[user_service] Creating user: u-001
[quota_service] Initializing quota for: u-001
[email_service] Sending welcome email to: alice@example.com
[quota_service] Resetting quota for: u-001 (compensation)
[user_service] Deleting user: u-001 (compensation)
```

And `result`:

```python
result.state.value        # "rolled_back"
result.failed_step        # step_id of the send_welcome step
result.error              # "SMTP server unavailable"
result.completed_steps    # [step_id of init_quota, step_id of create_user]
                           # (the two steps that were compensated)
```

The welcome email step's compensation (`cancel_welcome`) is NOT executed because it was the step that failed — only *completed* steps are compensated.

---

## Common Patterns

### Pattern 1 — Saga orchestrator for clean ergonomics

`SagaOrchestrator` removes the need to manage the `Transaction` object directly:

```python
from aumai_transactions import SagaOrchestrator, TransactionManager

manager = TransactionManager(action_handlers=my_handlers)
saga = SagaOrchestrator(manager)

saga.register("flight_agent",  "reserve_flight",  {"flight_id": "F123"}, "cancel_flight")
saga.register("hotel_agent",   "book_hotel",      {"hotel_id": "H456"},  "cancel_hotel")
saga.register("billing_agent", "charge_card",     {"amount": 850.00},    "refund_card")

result = saga.execute(timeout_seconds=90)

match result.state.value:
    case "committed":
        print("All booked!")
    case "rolled_back":
        print(f"Failed at step {result.failed_step}: {result.error}")
    case "failed":
        print("Transaction timed out.")
```

### Pattern 2 — Steps without compensating actions

Not every step needs a compensating action. If a step has no `compensating_action`, it is simply skipped during rollback:

```python
manager.add_step(
    tx,
    agent_id="analytics_agent",
    action="log_event",
    data={"event": "user_created"},
    compensating_action=None,   # logging is idempotent; no undo needed
)
```

### Pattern 3 — Dry-run mode (no handlers)

Create a `TransactionManager` without handlers to test transaction structure without executing any side effects:

```python
manager = TransactionManager()   # no handlers

tx = manager.begin()
manager.add_step(tx, "agent_a", "step_a", {"x": 1}, "undo_a")
manager.add_step(tx, "agent_b", "step_b", {"y": 2}, "undo_b")
result = manager.commit(tx)

print(result.state.value)          # "committed"
print(len(result.completed_steps)) # 2
# No handlers ran; steps were recorded and sequenced only
```

This is useful in unit tests to verify that step registration, ordering, and rollback logic work correctly without needing live services.

### Pattern 4 — Explicit manual rollback

Abort a transaction before committing:

```python
tx = manager.begin()
manager.add_step(tx, "agent_a", "action_a", {}, "undo_a")

# Decide to abort (e.g., validation failed)
result = manager.rollback(tx)
print(result.state.value)  # "rolled_back"
```

`rollback()` treats all steps as if they completed and runs compensating actions for all of them in reverse order.

### Pattern 5 — Restoring transactions from persistent storage

The CLI persists state automatically. For library usage, use Pydantic serialization:

```python
import json
from aumai_transactions import TransactionManager
from aumai_transactions.models import Transaction

# Save all transactions
manager = TransactionManager()
# ... populate manager ...

data = [tx.model_dump(mode="json") for tx in manager.get_all_transactions()]
with open("transactions.json", "w") as f:
    json.dump(data, f, indent=2)

# Restore in a new process
new_manager = TransactionManager(action_handlers=my_handlers)
with open("transactions.json") as f:
    for entry in json.load(f):
        tx = Transaction.model_validate(entry)
        new_manager.register_transaction(tx)
```

---

## Troubleshooting FAQ

**Q: `aumai-transactions: command not found`**

Ensure `~/.local/bin` is on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

**Q: `ValueError: Cannot add steps to transaction ... in state 'active'`**

Steps can only be added to transactions in `pending` state. Once `commit()` is called, the transaction moves to `active` and no further steps can be added. Design your workflow to add all steps before calling `commit()`.

---

**Q: `ValueError: Transaction ... is in state 'committed'; only 'pending' transactions can be committed.`**

Each transaction can only be committed once. If you need to retry a failed workflow, create a new transaction with `manager.begin()`.

---

**Q: My compensating actions are not being called**

Check these:
1. The compensating action name in `add_step(..., compensating_action="my_undo")` must match an exact key in the `action_handlers` dict passed to `TransactionManager`.
2. Only *completed* steps get compensated. The step that failed does not.
3. Compensation errors are silently swallowed (best-effort). Add logging inside your compensating handlers to confirm they are being called.

---

**Q: The transaction times out before my steps run**

The timeout is checked once when `commit()` is called, comparing the current UTC time to `tx.created_at + timedelta(seconds=tx.timeout_seconds)`. If you build the transaction (add steps) in a tight loop this won't trigger. If you add steps across multiple async tasks or over time, increase `timeout_seconds` when calling `begin()`.

---

**Q: Can I run steps in parallel?**

`TransactionManager` executes steps sequentially and synchronously. Parallel execution is not supported by the current implementation. For parallel step execution, run steps outside the transaction manager and use `add_step` only for coordination and compensation tracking.

---

**Q: How do I handle idempotent actions?**

If an action is idempotent (safe to re-run), you do not need a compensating action. Pass `compensating_action=None` to `add_step`. The rollback logic will skip that step.

---

**Q: Where is persistent state stored for the CLI?**

`~/.aumai/transactions/transactions.json`. This file is read on every CLI command and written after every state-changing command. Delete it to reset all CLI state.
