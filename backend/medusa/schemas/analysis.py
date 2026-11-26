"""API models for analysis runs, claims and LLM configuration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .domain import Claim

RunStatus = Literal["running", "completed", "failed"]
LlmRunStatus = Literal["disabled", "misconfigured", "ok", "partial", "failed"]


class AnalysisRun(BaseModel):
    run_id: str
    patient_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    extractor: str          # 'rules' or 'rules+llm:<provider>/<model>': what actually produced the stored claims
    llm_status: LlmRunStatus
    llm_error: str | None = None
    document_fingerprint: str
    stats: dict[str, Any]
    error: str | None = None


class AnalysisStatus(BaseModel):
    patient_id: str
    latest_run: AnalysisRun | None    # most recent attempt, whatever its outcome
    results_run: AnalysisRun | None   # the completed run whose claims are currently stored
    is_current: bool                  # results_run covers exactly the documents processed now
    stale_reason: str | None = None


class LlmConfig(BaseModel):
    """What the server will do with the LLM. Never contains the key."""
    provider: Literal["none", "anthropic", "openai_compatible"]
    model: str | None
    status: Literal["disabled", "misconfigured", "configured"]
    reason: str | None = None
    api_key_set: bool
    custom_base_url: bool


class ClaimRecord(Claim):
    """A stored claim plus the outcome of deterministic verification for the run that produced it."""
    verified: bool | None = None          # None: produced before verification existed (re-run the analysis)
    failed_checks: list[str] = Field(default_factory=list)  # hard checks that failed
