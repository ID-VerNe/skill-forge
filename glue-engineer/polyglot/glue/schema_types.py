"""
polyglot/glue/schema_types.py — Foundational data types for the glue schema.

Parameter, FunctionSignature, TransformRule, ParamMapping, FunctionMapping
(the interface-mapping primitives) plus StatusMachine (failure-aware state
machine for multi-step pipelines).

Every field carries a known confidence level — nothing is silently assumed.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Parameter:
    """A single function parameter."""
    name: str
    type_hint: str = ""
    default_value: str = ""
    required: bool = True


@dataclass
class FunctionSignature:
    """A single function or method signature from any language.

    Populated by Phase 2 (auditor/analyst). The `probed` flag means
    this was verified at runtime, not just extracted from source.
    """
    name: str
    kind: str = "function"          # "function" | "method" | "class" | "async_function"
    params: list = field(default_factory=list)   # list[dict] or list[Parameter]
    return_type: str = ""
    doc: str = ""
    probed: bool = False
    source_location: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "params": [p if isinstance(p, dict) else {"name": p.name, "type_hint": p.type_hint, "default_value": p.default_value, "required": p.required} for p in self.params],
            "return_type": self.return_type,
            "doc": self.doc,
            "probed": self.probed,
            "source_location": self.source_location,
        }

    @staticmethod
    def from_dict(d: dict) -> "FunctionSignature":
        return FunctionSignature(**d)


@dataclass
class TransformRule:
    """Describes how to transform a value from source to destination format."""
    kind: str = "identity"          # "identity" | "rename" | "type_cast" | "unwrap" | "composite"
    expr: str = ""                   # code expression for the transform
    params: dict = field(default_factory=dict)


@dataclass
class ParamMapping:
    """Maps one source parameter to one destination parameter."""
    src_name: str
    dst_name: str
    transform: Optional[TransformRule] = None
    src_default: str = ""
    dst_default: str = ""


@dataclass
class FunctionMapping:
    """One logical mapping: how to convert src.func -> dst.func call.

    CRITICAL: confidence is per-mapping, not per-package.
    High-confidence get() and low-confidence save() coexist in the
    same GlueSchema — the user only reviews low-confidence ones.
    """
    mapping_id: str
    src_function: str
    dst_function: str
    confidence: float = 0.0          # 0.0-1.0 — honest score
    confidence_label: str = ""       # "identical" | "similar" | "cross_lang_guess"

    param_mappings: list = field(default_factory=list)  # list[ParamMapping] or list[dict]
    return_transform: Optional[TransformRule] = None

    error_map: dict = field(default_factory=dict)        # {"src.exception": "dst.exception"}
    code_snippet: str = ""                               # generated glue function body

    review_status: str = "unreviewed"                    # "unreviewed" | "reviewed" | "rejected"
    review_note: str = ""

    def to_dict(self) -> dict:
        return {
            "mapping_id": self.mapping_id,
            "src_function": self.src_function,
            "dst_function": self.dst_function,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "param_mappings": [p if isinstance(p, dict) else {
                "src_name": p.src_name, "dst_name": p.dst_name,
                "transform": {"kind": p.transform.kind, "expr": p.transform.expr} if p.transform else None,
                "src_default": p.src_default, "dst_default": p.dst_default,
            } for p in self.param_mappings],
            "return_transform": {"kind": self.return_transform.kind, "expr": self.return_transform.expr} if self.return_transform else None,
            "error_map": self.error_map,
            "code_snippet": self.code_snippet,
            "review_status": self.review_status,
            "review_note": self.review_note,
        }


@dataclass
class StatusMachine:
    """Failure-aware state machine for multi-step pipelines.

    Tracks the status of each step in a multi-phase pipeline (e.g. PDF import,
    LLM extraction, code generation). Supports 8+ states for granular error
    tracking.

    States:
      pending              -> initial, not started
      queued               -> waiting in queue
      in_progress          -> actively processing
      retrying             -> automatic retry after transient failure
      succeeded            -> completed successfully
      failed               -> permanent failure
      failed_partial       -> partial success with some errors
      cancelled            -> user-/system-cancelled
      needs_review         -> completed but requires human review
      skipped              -> dependency failed, step skipped

    Transitions (directed graph):
      pending -> queued -> in_progress -> succeeded (normal happy path)
      in_progress -> failed (permanent error)
      in_progress -> retrying -> in_progress (transient error, retry)
      in_progress -> failed_partial (partial success)
      in_progress -> cancelled (user interrupt)
      pending -> skipped (upstream failure)
      succeeded -> needs_review (low confidence threshold)
      any -> cancelled (user/system override)
    """
    step_name: str = ""
    status: str = "pending"
    attempts: int = 0
    max_retries: int = 3
    error_message: str = ""
    error_code: str = ""          # e.g. "CONVERSION_FAILED", "LLM_TIMEOUT"
    error_detail: str = ""        # JSON string for structured error data
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0

    VALID_TRANSITIONS = {
        "pending":     ["queued", "skipped", "cancelled"],
        "queued":      ["in_progress", "cancelled"],
        "in_progress": ["succeeded", "failed", "failed_partial", "retrying", "cancelled"],
        "retrying":    ["in_progress", "failed", "cancelled"],
        "succeeded":   ["needs_review"],
        "failed":      ["retrying"],    # manual retry
        "failed_partial": ["retrying", "needs_review"],
        "cancelled":   [],
        "needs_review":["succeeded", "failed"],
        "skipped":     [],
    }

    def can_transition_to(self, new_status: str) -> bool:
        """Check if a transition to new_status is valid."""
        if self.status == new_status:
            return True  # idempotent
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def transition(self, new_status: str, error: str = "", error_code: str = "") -> bool:
        """Attempt a state transition. Returns True if successful."""
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Invalid transition: {self.status} -> {new_status} "
                f"(step: {self.step_name})"
            )
        self.status = new_status
        if error:
            self.error_message = error
        if error_code:
            self.error_code = error_code
        if new_status == "retrying":
            self.attempts += 1
        return True

    @property
    def is_terminal(self) -> bool:
        """Check if the step has reached a terminal state."""
        return self.status in ("succeeded", "failed", "cancelled", "skipped")

    @property
    def is_error(self) -> bool:
        """Check if the step is in an error state."""
        return self.status in ("failed", "failed_partial")

    @property
    def can_retry(self) -> bool:
        """Check if retry is possible (attempts < max_retries)."""
        return self.attempts < self.max_retries and self.is_error

    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "status": self.status,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
        }
