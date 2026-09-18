"""Tests for the ExecutionSettings dataclass (Phase 1 of the
ExecutionSettings Pattern refactoring)."""

import dataclasses

import pytest

from labeeb.execution import (
    ExecutionBackend,
    ExecutionSettings,
    FailurePolicy,
    HarvestFailurePolicy,
    LocalExecutionBackend,
)


def test_defaults():
    settings = ExecutionSettings()
    assert settings.timeout is None
    assert settings.shell is None
    assert settings.capture_output is False
    assert settings.log_file is None
    assert isinstance(settings.execution_backend, LocalExecutionBackend)
    assert settings.command_failure_policy == FailurePolicy.STOP
    assert settings.harvest_failure_policy == HarvestFailurePolicy.STOP
    assert settings.max_attempts == 1
    assert settings.parallel is False
    assert settings.n_workers is None
    assert settings.verbose is False


def test_each_instance_gets_its_own_backend():
    a = ExecutionSettings()
    b = ExecutionSettings()
    assert a.execution_backend is not b.execution_backend


def test_command_failure_policy_string_coercion():
    settings = ExecutionSettings(command_failure_policy="continue")
    assert settings.command_failure_policy == FailurePolicy.CONTINUE
    assert settings.command_failure_policy == "continue"  # str-enum compat


def test_harvest_failure_policy_string_coercion():
    settings = ExecutionSettings(harvest_failure_policy="continue")
    assert settings.harvest_failure_policy == HarvestFailurePolicy.CONTINUE
    assert settings.harvest_failure_policy == "continue"


def test_command_failure_policy_enum_passthrough():
    settings = ExecutionSettings(command_failure_policy=FailurePolicy.RETRY, max_attempts=3)
    assert settings.command_failure_policy is FailurePolicy.RETRY


def test_invalid_command_failure_policy_rejected():
    with pytest.raises(ValueError, match="command_failure_policy"):
        ExecutionSettings(command_failure_policy="explode")


def test_invalid_harvest_failure_policy_rejected():
    with pytest.raises(ValueError, match="harvest_failure_policy"):
        ExecutionSettings(harvest_failure_policy="explode")


def test_max_attempts_must_be_at_least_one():
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        ExecutionSettings(max_attempts=0)


def test_max_attempts_must_be_int():
    with pytest.raises(TypeError, match="max_attempts must be an int"):
        ExecutionSettings(max_attempts=1.5)


def test_retry_policy_requires_max_attempts_at_least_two():
    with pytest.raises(ValueError, match="max_attempts must be >= 2"):
        ExecutionSettings(command_failure_policy=FailurePolicy.RETRY, max_attempts=1)


def test_retry_policy_with_string_also_validated():
    with pytest.raises(ValueError, match="max_attempts must be >= 2"):
        ExecutionSettings(command_failure_policy="retry", max_attempts=1)


def test_retry_policy_accepts_two_or_more():
    settings = ExecutionSettings(command_failure_policy="retry", max_attempts=2)
    assert settings.max_attempts == 2


def test_timeout_must_be_positive():
    with pytest.raises(ValueError, match="timeout must be > 0"):
        ExecutionSettings(timeout=0)
    with pytest.raises(ValueError, match="timeout must be > 0"):
        ExecutionSettings(timeout=-5)


def test_timeout_must_be_numeric():
    with pytest.raises(TypeError, match="timeout must be a number"):
        ExecutionSettings(timeout="10")


def test_timeout_accepts_positive_number():
    settings = ExecutionSettings(timeout=30.5)
    assert settings.timeout == 30.5


def test_n_workers_must_be_at_least_one():
    with pytest.raises(ValueError, match="n_workers must be >= 1"):
        ExecutionSettings(n_workers=0)


def test_n_workers_must_be_int():
    with pytest.raises(TypeError, match="n_workers must be an int"):
        ExecutionSettings(n_workers=2.0)


def test_n_workers_accepts_positive_int():
    settings = ExecutionSettings(n_workers=4)
    assert settings.n_workers == 4


def test_execution_backend_must_be_execution_backend_instance():
    with pytest.raises(TypeError, match="execution_backend must be an instance"):
        ExecutionSettings(execution_backend="not-a-backend")


def test_execution_backend_accepts_subclass_instance():
    class DummyBackend(ExecutionBackend):
        pass

    settings = ExecutionSettings(execution_backend=DummyBackend())
    assert isinstance(settings.execution_backend, DummyBackend)


def test_frozen_prevents_mutation():
    settings = ExecutionSettings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.timeout = 10


def test_replace_creates_new_instance_with_overrides():
    settings = ExecutionSettings(verbose=True)
    updated = dataclasses.replace(settings, timeout=15)
    assert updated.timeout == 15
    assert updated.verbose is True
    assert settings.timeout is None
