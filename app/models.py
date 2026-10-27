from pydantic import BaseModel, ConfigDict, Field


class Finding(BaseModel):
    """A single potential privacy or hidden-data finding."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    category: str
    source_layer: str
    reason: str | None = None
    location: str | None = None
    approved: bool = True


class Report(BaseModel):
    """Findings and post-redaction verification result."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    findings: list[Finding]
    verified_clean: bool
    leftovers: list[str]
    warnings: list[str] = Field(default_factory=list)
