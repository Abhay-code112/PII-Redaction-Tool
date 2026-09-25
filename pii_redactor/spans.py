from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Half-open character range [start, end) tagged with a PII label."""
    start: int
    end: int
    label: str
    priority: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Greedy pick: higher priority first, then longer, then leftmost.

    A URL containing a brand name should stay one URL, an address swallows the
    place names inside it, and so on.
    """
    chosen: list[Span] = []
    for s in sorted(spans, key=lambda s: (-s.priority, -s.length, s.start)):
        if not any(s.overlaps(c) for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda s: s.start)
