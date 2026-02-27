"""Comprehensive CLI tests for aumai-transactions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from aumai_transactions.cli import main
from aumai_transactions.models import TransactionState


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ===========================================================================
# --version
# ===========================================================================


class TestVersion:
    def test_version_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0

    def test_version_shows_version_string(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert "0.1.0" in result.output


# ===========================================================================
# --help
# ===========================================================================


class TestHelp:
    def test_main_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("subcommand", ["create", "status"])
    def test_subcommands_in_help(self, runner: CliRunner, subcommand: str) -> None:
        result = runner.invoke(main, ["--help"])
        assert subcommand in result.output

    def test_create_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["create", "--help"])
        assert result.exit_code == 0

    def test_status_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0


# ===========================================================================
# create command
# ===========================================================================


class TestCreateCommand:
    def test_create_exits_zero(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            assert result.exit_code == 0

    def test_create_output_is_json(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert isinstance(data, dict)

    def test_create_output_has_transaction_id(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert "transaction_id" in data

    def test_create_output_state_is_pending(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert data["state"] == "pending"

    def test_create_output_has_created_at(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert "created_at" in data

    def test_create_output_has_timeout_seconds(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert "timeout_seconds" in data

    def test_create_default_timeout_is_60(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create"])
            data = json.loads(result.output)
            assert data["timeout_seconds"] == 60

    def test_create_with_custom_timeout(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["create", "--timeout", "120"])
            data = json.loads(result.output)
            assert data["timeout_seconds"] == 120

    def test_create_generates_unique_ids(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result1 = runner.invoke(main, ["create"])
            result2 = runner.invoke(main, ["create"])
            id1 = json.loads(result1.output)["transaction_id"]
            id2 = json.loads(result2.output)["transaction_id"]
            assert id1 != id2


# ===========================================================================
# status command
# ===========================================================================


class TestStatusCommand:
    def test_status_of_created_transaction(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            assert result.exit_code == 0

    def test_status_output_is_json(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            data = json.loads(result.output)
            assert isinstance(data, dict)

    def test_status_shows_correct_id(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            data = json.loads(result.output)
            assert data["transaction_id"] == tx_id

    def test_status_shows_state(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            data = json.loads(result.output)
            assert "state" in data

    def test_status_shows_step_count(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            data = json.loads(result.output)
            assert "steps" in data
            assert data["steps"] == 0

    def test_status_nonexistent_tx_exits_nonzero(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["status", "--tx-id", "nonexistent-uuid"])
            assert result.exit_code != 0

    def test_status_requires_tx_id(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["status"])
            assert result.exit_code != 0

    def test_status_state_is_pending_after_create(self, runner: CliRunner, tmp_path: Path) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            result = runner.invoke(main, ["status", "--tx-id", tx_id])
            data = json.loads(result.output)
            assert data["state"] == "pending"


# ===========================================================================
# Persistence: data survives across CLI invocations
# ===========================================================================


class TestPersistence:
    def test_transaction_persisted_across_invocations(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # First invocation: create
            create_result = runner.invoke(main, ["create"])
            tx_id = json.loads(create_result.output)["transaction_id"]

            # Second invocation: status (should find the tx from the first)
            status_result = runner.invoke(main, ["status", "--tx-id", tx_id])
            assert status_result.exit_code == 0
            data = json.loads(status_result.output)
            assert data["transaction_id"] == tx_id
