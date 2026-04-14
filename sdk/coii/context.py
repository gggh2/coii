"""CoiiContext — returned by coii.start()."""
from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class VariantInfo:
    name: str
    provider: str
    model: str
    prompt_version: Optional[str] = None
    config: dict = field(default_factory=dict)
    is_current: bool = False


class CoiiContext:
    """Context for a single user interaction."""

    def __init__(self, coii, user_id: str, trace_id: str, assignments: dict):
        self._coii = coii
        self.user_id = user_id
        self.trace_id = trace_id
        self._assignments = assignments  # {exp_name: {variant: {...}, ...}}

        # Build primary variant (first running experiment)
        primary_variant = None
        if assignments:
            first = next(iter(assignments.values()), None)
            if first and first.get("variant"):
                primary_variant = first["variant"]

        if primary_variant:
            self.model: str = primary_variant.get("model", coii._default_model or "")
            self.provider: str = primary_variant.get("provider", "")
            self.prompt_version: Optional[str] = primary_variant.get("prompt_version")
            self.config: dict = primary_variant.get("config", {})
        else:
            self.model: str = coii._default_model or ""
            self.provider: str = ""
            self.prompt_version: Optional[str] = None
            self.config: dict = {}

        # Build variants dict for multi-experiment access
        self.variants: dict[str, VariantInfo] = {}
        for exp_name, asgn in assignments.items():
            v = asgn.get("variant")
            if v:
                self.variants[exp_name] = VariantInfo(
                    name=v.get("name", ""),
                    provider=v.get("provider", ""),
                    model=v.get("model", ""),
                    prompt_version=v.get("prompt_version"),
                    config=v.get("config", {}),
                    is_current=v.get("is_current", False),
                )

    def outcome(self, event: str, properties: Optional[dict] = None):
        """Record a business outcome for this user."""
        self._coii.outcome(self.user_id, event, properties)

    def end(self):
        """Mark the trace as ended."""
        self._coii._end_trace(self.trace_id)

    def __repr__(self) -> str:
        return (
            f"CoiiContext(user_id={self.user_id!r}, trace_id={self.trace_id!r}, "
            f"model={self.model!r}, provider={self.provider!r})"
        )
