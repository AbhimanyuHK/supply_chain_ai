"""Security checks for separated privileged API credentials."""
import pytest
from fastapi import HTTPException

from app.api.routers.decisions import require_approver, require_fulfillment


def test_approval_requires_separate_credential(monkeypatch):
    monkeypatch.setenv("SUPPLY_CHAIN_APPROVER_TOKEN", "approver-secret")
    monkeypatch.setenv("SUPPLY_CHAIN_OPERATOR_TOKEN", "operator-secret")
    with pytest.raises(HTTPException) as exc:
        require_approver(x_approver_token="operator-secret")
    assert exc.value.status_code == 403
    assert require_approver(x_approver_token="approver-secret") is None


def test_fulfillment_requires_separate_credential(monkeypatch):
    monkeypatch.setenv("SUPPLY_CHAIN_FULFILLMENT_TOKEN", "fulfillment-secret")
    with pytest.raises(HTTPException) as exc:
        require_fulfillment(x_fulfillment_token="other-secret")
    assert exc.value.status_code == 403
    assert require_fulfillment(x_fulfillment_token="fulfillment-secret") is None


def test_missing_privileged_secrets_fail_closed(monkeypatch):
    monkeypatch.delenv("SUPPLY_CHAIN_APPROVER_TOKEN", raising=False)
    monkeypatch.delenv("SUPPLY_CHAIN_FULFILLMENT_TOKEN", raising=False)
    with pytest.raises(HTTPException):
        require_approver(x_approver_token="anything")
    with pytest.raises(HTTPException):
        require_fulfillment(x_fulfillment_token="anything")
