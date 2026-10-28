"""Tests for fail-closed planning API authentication."""
import pytest
from fastapi import HTTPException
from app.api.routers.decisions import require_operator


def test_operator_auth_fails_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SUPPLY_CHAIN_OPERATOR_TOKEN", raising=False)
    with pytest.raises(HTTPException) as error:
        require_operator("anything")
    assert error.value.status_code == 403


def test_operator_auth_fails_on_bad_token(monkeypatch):
    monkeypatch.setenv("SUPPLY_CHAIN_OPERATOR_TOKEN", "strong-test-token")
    with pytest.raises(HTTPException) as error:
        require_operator("wrong")
    assert error.value.status_code == 403


def test_operator_auth_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("SUPPLY_CHAIN_OPERATOR_TOKEN", "strong-test-token")
    assert require_operator("strong-test-token") is None
