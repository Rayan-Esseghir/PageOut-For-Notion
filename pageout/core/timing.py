"""Timing instrumentation for export profiling (P1)."""

import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimingStats:
    """Statistics for a single timing category."""

    count: int = 0
    total_ms: float = 0.0
    bytes_downloaded: int = 0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


@dataclass
class TimingReport:
    """
    Collects timing data during export.

    Categories:
    - notion_api: Notion API calls (including rate limiter wait time / Retry-After)
    - images: image downloads (count, bytes)
    - pdf: Chromium printing (per format)
    - merge: PDF merging
    - other: everything else (tree building, rendering, etc.)
    """

    notion_api: TimingStats = field(default_factory=TimingStats)
    images: TimingStats = field(default_factory=TimingStats)
    pdf: TimingStats = field(default_factory=TimingStats)
    merge: TimingStats = field(default_factory=TimingStats)
    other: TimingStats = field(default_factory=TimingStats)

    # Track retry waits for rate limiter
    api_wait_ms: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "notion_api": {
                "count": self.notion_api.count,
                "total_ms": round(self.notion_api.total_ms, 2),
                "bytes_downloaded": self.notion_api.bytes_downloaded,
                "avg_ms": round(self.notion_api.avg_ms, 2),
            },
            "images": {
                "count": self.images.count,
                "total_ms": round(self.images.total_ms, 2),
                "bytes_downloaded": self.images.bytes_downloaded,
                "avg_ms": round(self.images.avg_ms, 2),
            },
            "pdf": {
                "count": self.pdf.count,
                "total_ms": round(self.pdf.total_ms, 2),
            },
            "merge": {
                "count": self.merge.count,
                "total_ms": round(self.merge.total_ms, 2),
            },
            "other": {
                "count": self.other.count,
                "total_ms": round(self.other.total_ms, 2),
            },
            "api_wait_ms": round(self.api_wait_ms, 2),
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def summary(self) -> str:
        """
        Return a formatted summary line like:
        "Notion 62% · images 20% · PDF 15% · other 3%"
        """
        total_ms = (
            self.notion_api.total_ms
            + self.images.total_ms
            + self.pdf.total_ms
            + self.merge.total_ms
            + self.other.total_ms
        )

        if total_ms == 0:
            return "No timing data collected"

        def pct(ms: float) -> int:
            return round(ms / total_ms * 100)

        parts = []
        if self.notion_api.total_ms:
            parts.append(f"Notion {pct(self.notion_api.total_ms)}%")
        if self.images.total_ms:
            parts.append(f"images {pct(self.images.total_ms)}%")
        if self.pdf.total_ms:
            parts.append(f"PDF {pct(self.pdf.total_ms)}%")
        if self.merge.total_ms:
            parts.append(f"merge {pct(self.merge.total_ms)}%")
        if self.other.total_ms:
            parts.append(f"other {pct(self.other.total_ms)}%")

        # Ensure percentages add up correctly
        return " · ".join(parts)


class Timer:
    """Context manager for timing code blocks."""

    def __init__(self, stats: TimingStats, category: str = "other", count_images: int = 0):
        self.stats = stats
        self.category = category
        self.count_images = count_images
        self.start: Optional[float] = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start) * 1000 if self.start else 0
        self.stats.total_ms += elapsed_ms
        self.stats.count += 1
        if self.category == "images":
            self.stats.bytes_downloaded += self.count_images


# Global registry for timing
_timing: Optional[TimingReport] = None


def reset_timer():
    """Reset the global timing registry (called at the start of each export)."""
    global _timing
    _timing = None


def start_timer(cfg: dict) -> "TimingReport":
    """Initialize timing for a new export run."""
    global _timing
    _timing = TimingReport()
    return _timing


def get_timer() -> TimingReport:
    """Get the current timing report, creating one if needed."""
    global _timing
    if _timing is None:
        _timing = TimingReport()
    return _timing


def timer(stats: TimingStats, category: str = "other", count_images: int = 0) -> Timer:
    """Create a timer for a specific category."""
    return Timer(stats, category, count_images)


def end_timer(elapsed_ms: float, stats: TimingStats):
    """Record timing after the fact (for async operations)."""
    stats.total_ms += elapsed_ms
    stats.count += 1


def record_api_wait(wait_ms: float):
    """Record rate limiter wait time."""
    global _timing
    if _timing:
        _timing.api_wait_ms += wait_ms


def record_image_bytes(n: int):
    """Record bytes downloaded for an image."""
    global _timing
    if _timing:
        _timing.images.bytes_downloaded += n


def set_api_timing(timing: TimingReport):
    """Set the global timing report for API call instrumentation."""
    global _timing
    _timing = timing
    # Also update the notion_api module's reference
    from pageout.sources import notion_api

    notion_api._api_timing = timing
