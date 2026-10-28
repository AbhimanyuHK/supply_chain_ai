"""Pure validation tests; no API calls or model downloads."""
from types import SimpleNamespace

from app.agents.llm_native_optimizer import ProposedLine, ProposedPlan, validate_proposal


def _fixtures():
    shortage = [SimpleNamespace(store_id=1, product_id=7, shortage_qty=8)]
    lane = [SimpleNamespace(terminal_id=2, store_id=1, product_id=7,
                            estimated_transport_cost=10.0, estimated_delivery_hours=2.0)]
    return shortage, lane, {(2, 7): 5}


def test_accepts_feasible_llm_plan():
    shortage, lane, stock = _fixtures()
    plan = ProposedPlan(lines=[ProposedLine(terminal_id=2, store_id=1, product_id=7, quantity=5)],
                        rationale="available stock")
    assert validate_proposal(plan, shortage, lane, stock)[0].quantity == 5


def test_rejects_inventory_overdraw():
    shortage, lane, stock = _fixtures()
    plan = ProposedPlan(lines=[ProposedLine(terminal_id=2, store_id=1, product_id=7, quantity=6)],
                        rationale="invalid")
    assert validate_proposal(plan, shortage, lane, stock) is None


def test_rejects_duplicate_lines_overdrawing_stock():
    shortage, lane, stock = _fixtures()
    plan = ProposedPlan(lines=[
        ProposedLine(terminal_id=2, store_id=1, product_id=7, quantity=3),
        ProposedLine(terminal_id=2, store_id=1, product_id=7, quantity=3),
    ], rationale="invalid")
    assert validate_proposal(plan, shortage, lane, stock) is None


def test_rejects_invented_lane():
    shortage, lane, stock = _fixtures()
    plan = ProposedPlan(lines=[ProposedLine(terminal_id=999, store_id=1, product_id=7, quantity=1)],
                        rationale="invalid")
    assert validate_proposal(plan, shortage, lane, stock) is None
