"""DARI Smart Homecare Digital Twin.

Sub-packages:
  activity_engine  — infers what the patient is doing, writes the activity timeline
  rule_engine      — threshold/event rules, fires alerts
  api_server       — FastAPI app; the single REST contract every client reads
  admin_streamlit  — legacy Streamlit rule builder
"""
__all__ = ["activity_engine", "rule_engine", "api_server", "paths"]
