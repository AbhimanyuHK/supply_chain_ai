"""Read-only AI Control Tower for planning run audits.

Run: streamlit run control_tower.py
Requires the FastAPI server at CONTROL_TOWER_API_URL (default localhost:8000).
"""
import os
import requests
import streamlit as st

API = os.getenv("CONTROL_TOWER_API_URL", "http://localhost:8000").rstrip("/")
st.set_page_config(page_title="Supply Chain AI Control Tower", layout="wide")
st.title("Supply Chain AI Control Tower")
st.caption("Read-only planning oversight. No automatic shipment dispatch.")

@st.cache_data(ttl=30)
def get_json(path):
    response = requests.get(API + path, timeout=20)
    response.raise_for_status()
    return response.json()

try:
    runs = get_json("/api/v1/planning-runs?limit=50")
except requests.RequestException as exc:
    st.error(f"Planning API unavailable: {exc}")
    st.stop()

if not runs:
    st.info("No planning runs recorded.")
    st.stop()

st.subheader("Recent planning runs")
st.dataframe(runs, use_container_width=True, hide_index=True)
run_ids = [int(r["id"]) for r in runs]
selected = st.selectbox("Inspect planning run", run_ids)
try:
    record = get_json(f"/api/v1/planning-runs/{selected}")
except requests.RequestException as exc:
    st.error(str(exc))
    st.stop()

cols = st.columns(3)
cols[0].metric("Run", selected)
cols[1].metric("Status", str(record.get("status", "unknown")))
cols[2].metric("Replanning attempts", record.get("replanning_attempts", 0))

validation = record.get("constraint_validation") or {}
allocation = record.get("allocation") or {}
costs = record.get("cost_optimization") or {}
scenarios = allocation.get("scenarios") or []
valid = {v.get("strategy") for v in validation.get("scenario_validations", []) if v.get("is_valid")}
st.subheader("Scenario comparison")
if scenarios:
    rows = []
    by_cost = {c["strategy"]: c for c in costs.get("scenarios", [])}
    for scenario in scenarios:
        name = scenario["strategy"]
        rows.append({
            "strategy": name,
            "origin": "LLM" if name.startswith("llm_native_") else "baseline",
            "feasible": name in valid,
            "fulfillment_rate": scenario.get("fulfillment_rate"),
            "high_priority_fulfilled": scenario.get("high_priority_shortages_fulfilled"),
            "cost": by_cost.get(name, {}).get("total_cost"),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No allocation scenarios in this run.")

st.subheader("Selected plan and risk")
st.write("Selected strategy:", validation.get("final_strategy") or "No validated plan")
if validation.get("unresolved_violations"):
    st.error("Unresolved constraint violations — manual review required.")
    st.json(validation["unresolved_violations"])
with st.expander("Agent trace and audit"):
    st.json(record.get("trace") or [])
with st.expander("Full run details"):
    st.json(record)
