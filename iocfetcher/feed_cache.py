import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, replace
from collections.abc import Awaitable, Callable

from iocfetcher.common import LOGGER, ValidatedFeedData
from iocfetcher.config import FeedConfig
from iocfetcher.fetcher import fetch_source


@dataclass(frozen=True, slots=True)
class FeedCacheEntry:
    data: ValidatedFeedData
    fetched_at: float
    last_attempt_at: float
    last_error: str | None = None


class FeedCache:
    """In-memory cache of the last successfully validated feed snapshots."""

    def __init__(
        self,
        default_timeout: float = 30,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.default_timeout = default_timeout
        self._clock = clock
        self._sleep = sleep
        self._entries: dict[str, FeedCacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._refresh_tasks: dict[str, asyncio.Task[FeedCacheEntry | None]] = {}
        self._scheduler_tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, sources: list[FeedConfig]) -> None:
        """Start one proactive refresh loop for each distinct configured feed."""
        for source in sources:
            key = self._cache_key(source)
            existing = self._scheduler_tasks.get(key)
            if existing is not None and not existing.done():
                continue
            self._scheduler_tasks[key] = asyncio.create_task(
                self._refresh_loop(source, key),
                name=f"schedule-feed-{key[:12]}",
            )
        LOGGER.info(f"Started proactive refresh for {len(self._scheduler_tasks)} feeds")

    async def stop(self) -> None:
        """Cancel proactive and on-demand refresh work during application shutdown."""
        tasks = tuple(self._scheduler_tasks.values()) + tuple(
            self._refresh_tasks.values()
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._scheduler_tasks.clear()
        self._refresh_tasks.clear()
        LOGGER.info("Stopped proactive feed refresh")

    async def get_sources(
        self,
        sources: list[FeedConfig],
    ) -> list[tuple[FeedConfig, ValidatedFeedData]]:
        results = await asyncio.gather(
            *(self.get_source(source) for source in sources),
            return_exceptions=True,
        )

        feeds: list[tuple[FeedConfig, ValidatedFeedData]] = []
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                LOGGER.error(f"Failed to obtain feed {source.url}: {result!r}")
            elif result is not None:
                feeds.append((source, result))
        return feeds

    async def get_source(self, source: FeedConfig) -> ValidatedFeedData | None:
        key = self._cache_key(source)
        entry = self._entries.get(key)
        now = self._clock()

        if entry is None:
            LOGGER.debug(f"Feed cache miss: url={source.url}")
            refreshed = await self._refresh(source, key, expected_fetched_at=None)
            return refreshed.data if refreshed is not None else None

        age = now - entry.fetched_at
        if age < source.refresh_after:
            LOGGER.debug(f"Feed cache hit: url={source.url} age={age:.1f}s")
            return entry.data

        if source.max_stale is None or age <= source.max_stale:
            scheduler = self._scheduler_tasks.get(key)
            if scheduler is not None and not scheduler.done():
                LOGGER.debug(
                    f"Serving stale feed while proactive refresh is scheduled: "
                    f"url={source.url} age={age:.1f}s"
                )
            elif self._retry_is_due(source, entry, now):
                LOGGER.debug(
                    f"Serving stale feed and scheduling refresh: "
                    f"url={source.url} age={age:.1f}s"
                )
                self._schedule_refresh(source, key, entry.fetched_at)
            else:
                retry_in = source.retry_after - (now - entry.last_attempt_at)
                LOGGER.debug(
                    f"Serving stale feed; refresh retry delayed: "
                    f"url={source.url} age={age:.1f}s retry_in={retry_in:.1f}s"
                )
            return entry.data

        LOGGER.debug(
            f"Feed cache entry exceeds max_stale; refreshing synchronously: "
            f"url={source.url} age={age:.1f}s"
        )
        refreshed = await self._refresh(source, key, entry.fetched_at)
        if refreshed is None or refreshed.fetched_at == entry.fetched_at:
            return None
        return refreshed.data

    async def _refresh_loop(self, source: FeedConfig, key: str) -> None:
        delay = 0
        while True:
            if delay:
                LOGGER.debug(
                    f"Next feed refresh scheduled: url={source.url} in={delay}s"
                )
                await self._sleep(delay)

            current = self._entries.get(key)
            expected_fetched_at = current.fetched_at if current is not None else None
            entry = await self._refresh(source, key, expected_fetched_at)
            delay = (
                source.refresh_after
                if entry is not None and entry.last_error is None
                else source.retry_after
            )

    async def wait_for_refreshes(self) -> None:
        """Wait for currently scheduled refreshes, primarily for shutdown and tests."""
        tasks = tuple(self._refresh_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _schedule_refresh(
        self,
        source: FeedConfig,
        key: str,
        expected_fetched_at: float,
    ) -> None:
        existing = self._refresh_tasks.get(key)
        if existing is not None and not existing.done():
            LOGGER.debug(f"Feed refresh already running: url={source.url}")
            return

        task = asyncio.create_task(
            self._refresh(source, key, expected_fetched_at),
            name=f"refresh-feed-{key[:12]}",
        )
        self._refresh_tasks[key] = task
        task.add_done_callback(lambda completed: self._refresh_done(key, completed))

    def _refresh_done(
        self,
        key: str,
        task: asyncio.Task[FeedCacheEntry | None],
    ) -> None:
        if self._refresh_tasks.get(key) is task:
            self._refresh_tasks.pop(key, None)

    async def _refresh(
        self,
        source: FeedConfig,
        key: str,
        expected_fetched_at: float | None,
    ) -> FeedCacheEntry | None:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._entries.get(key)
            if current is not None:
                if expected_fetched_at is None:
                    if self._clock() - current.fetched_at < source.refresh_after:
                        return current
                elif current.fetched_at != expected_fetched_at:
                    return current

            attempted_at = self._clock()
            timeout = source.fetch_timeout or self.default_timeout
            LOGGER.debug(f"Refreshing feed: url={source.url} timeout={timeout}s")
            try:
                data = await fetch_source(source, timeout=timeout)
            except Exception as exc:
                LOGGER.error(f"Failed to refresh feed {source.url}: {exc!r}")
                if current is not None:
                    failed = replace(
                        current,
                        last_attempt_at=attempted_at,
                        last_error=str(exc),
                    )
                    self._entries[key] = failed
                    return failed
                return None

            refreshed_at = self._clock()
            entry = FeedCacheEntry(
                data=data,
                fetched_at=refreshed_at,
                last_attempt_at=refreshed_at,
            )
            self._entries[key] = entry
            LOGGER.info(f"Cached validated feed {source.url}")
            return entry

    @staticmethod
    def _retry_is_due(
        source: FeedConfig,
        entry: FeedCacheEntry,
        now: float,
    ) -> bool:
        return entry.last_error is None or now - entry.last_attempt_at >= source.retry_after

    @staticmethod
    def _cache_key(source: FeedConfig) -> str:
        identity = {
            "url": str(source.url),
            "format": source.format.value,
            "types": sorted(item.value for item in source.types),
            "headers": sorted((source.headers or {}).items()),
        }
        encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()
