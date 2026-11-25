"""Source adapter interface: anything that can produce IR documents."""

from abc import ABC, abstractmethod


class BaseSource(ABC):
    """A source yields ready-made IR ``Document`` objects (the Notion API source is built into the
    pipeline because it also needs lazy block fetching, rate limiting and URL refresh)."""

    name = "source"

    @abstractmethod
    def documents(self):
        """Return a list of ``pageout.core.ir.Document``."""
