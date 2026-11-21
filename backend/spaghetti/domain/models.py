"""Plain data objects. They know nothing about HTTP, files or model runtimes."""
from dataclasses import dataclass, field


@dataclass
class Document:
    id: str
    name: str
    text: str
    chunks: list[str] = field(default_factory=list)


@dataclass
class Hit:
    doc_id: str
    doc_name: str
    text: str
    score: float
    source_ids: tuple[str, ...] = ()


@dataclass
class Plan:
    mode: str  # chat | lookup | summary | compare
    k: int


@dataclass
class Verdict:
    score: float  # 0..10
    grounded: float  # 0..1 word overlap with the pantry
    issues: str
    method: str  # "taster-llm" or "overlap-only"


@dataclass
class AskRequest:
    question: str
    history: list[dict] = field(default_factory=list)
