"""Repository placeholders for future persistence logic."""


class ResearchRepository:
    """Placeholder repository interface for future storage backends."""

    def __init__(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        """Return whether a real storage backend has been configured."""
        return self._ready
