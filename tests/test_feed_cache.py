import asyncio
import ipaddress
import unittest
from unittest.mock import AsyncMock, patch

from iocfetcher.common import ValidatedFeedData
from iocfetcher.config import FeedConfig
from iocfetcher.feed_cache import FeedCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_source(**overrides) -> FeedConfig:
    values = {
        "url": "https://example.com/feed.txt",
        "format": "lines",
        "categories": ["block"],
        "types": ["ip"],
        "refresh_after": 300,
        "max_stale": 3600,
        "retry_after": 60,
    }
    values.update(overrides)
    return FeedConfig.model_validate(values)


def snapshot(address: str) -> ValidatedFeedData:
    return ValidatedFeedData(ips=frozenset({ipaddress.ip_network(address)}))


class FeedCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_proactive_scheduler_refreshes_after_refresh_interval(self) -> None:
        clock = FakeClock()
        sleep_delays: asyncio.Queue[float] = asyncio.Queue()
        sleep_releases: asyncio.Queue[None] = asyncio.Queue()

        async def controlled_sleep(seconds: float) -> None:
            await sleep_delays.put(seconds)
            await sleep_releases.get()

        cache = FeedCache(clock=clock, sleep=controlled_sleep)
        source = make_source()
        old = snapshot("8.8.8.8")
        new = snapshot("1.1.1.1")
        fetch_count: asyncio.Queue[int] = asyncio.Queue()
        fetch_number = 0

        async def scheduled_fetch(*args, **kwargs) -> ValidatedFeedData:
            nonlocal fetch_number
            fetch_number += 1
            await fetch_count.put(fetch_number)
            return old if fetch_number == 1 else new

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=scheduled_fetch),
        ) as fetch:
            cache.start([source])
            try:
                self.assertEqual(await fetch_count.get(), 1)
                self.assertEqual(await sleep_delays.get(), 300)

                clock.advance(300)
                await sleep_releases.put(None)

                self.assertEqual(await fetch_count.get(), 2)
                self.assertEqual(await sleep_delays.get(), 300)
                self.assertIs(await cache.get_source(source), new)
            finally:
                await cache.stop()

        self.assertEqual(fetch.await_count, 2)

    async def test_proactive_scheduler_uses_retry_interval_after_failure(self) -> None:
        clock = FakeClock()
        sleep_delays: asyncio.Queue[float] = asyncio.Queue()
        sleep_releases: asyncio.Queue[None] = asyncio.Queue()

        async def controlled_sleep(seconds: float) -> None:
            await sleep_delays.put(seconds)
            await sleep_releases.get()

        cache = FeedCache(clock=clock, sleep=controlled_sleep)
        source = make_source()
        old = snapshot("8.8.8.8")
        attempts: asyncio.Queue[int] = asyncio.Queue()
        attempt_number = 0

        async def scheduled_fetch(*args, **kwargs) -> ValidatedFeedData:
            nonlocal attempt_number
            attempt_number += 1
            await attempts.put(attempt_number)
            if attempt_number == 2:
                raise TimeoutError("slow feed")
            return old

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=scheduled_fetch),
        ):
            cache.start([source])
            try:
                self.assertEqual(await attempts.get(), 1)
                self.assertEqual(await sleep_delays.get(), 300)

                clock.advance(300)
                await sleep_releases.put(None)

                self.assertEqual(await attempts.get(), 2)
                self.assertEqual(await sleep_delays.get(), 60)
                self.assertIs(await cache.get_source(source), old)
            finally:
                await cache.stop()

    async def test_fresh_snapshot_does_not_refetch(self) -> None:
        clock = FakeClock()
        cache = FeedCache(clock=clock)
        source = make_source()
        data = snapshot("8.8.8.8")

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(return_value=data),
        ) as fetch:
            self.assertIs(await cache.get_source(source), data)
            clock.advance(299)
            self.assertIs(await cache.get_source(source), data)

        fetch.assert_awaited_once_with(source, timeout=30)

    async def test_stale_snapshot_is_returned_while_refresh_runs(self) -> None:
        clock = FakeClock()
        cache = FeedCache(clock=clock)
        source = make_source()
        old = snapshot("8.8.8.8")
        new = snapshot("1.1.1.1")

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=[old, new]),
        ) as fetch:
            await cache.get_source(source)
            clock.advance(301)

            self.assertIs(await cache.get_source(source), old)
            await cache.wait_for_refreshes()
            self.assertIs(await cache.get_source(source), new)

        self.assertEqual(fetch.await_count, 2)

    async def test_failed_refresh_keeps_stale_snapshot_and_honors_retry_delay(self) -> None:
        clock = FakeClock()
        cache = FeedCache(clock=clock)
        source = make_source()
        old = snapshot("8.8.8.8")

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=[old, TimeoutError("slow feed")]),
        ) as fetch:
            await cache.get_source(source)
            clock.advance(301)

            self.assertIs(await cache.get_source(source), old)
            await cache.wait_for_refreshes()
            self.assertIs(await cache.get_source(source), old)

        self.assertEqual(fetch.await_count, 2)

    async def test_snapshot_older_than_max_stale_is_not_served_after_failure(self) -> None:
        clock = FakeClock()
        cache = FeedCache(clock=clock)
        source = make_source(max_stale=600)
        old = snapshot("8.8.8.8")

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=[old, TimeoutError("slow feed")]),
        ):
            await cache.get_source(source)
            clock.advance(601)
            self.assertIsNone(await cache.get_source(source))

    async def test_concurrent_cold_requests_share_one_fetch(self) -> None:
        clock = FakeClock()
        cache = FeedCache(clock=clock)
        source = make_source()
        data = snapshot("8.8.8.8")
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_fetch(*args, **kwargs) -> ValidatedFeedData:
            started.set()
            await release.wait()
            return data

        with patch(
            "iocfetcher.feed_cache.fetch_source",
            new=AsyncMock(side_effect=delayed_fetch),
        ) as fetch:
            first = asyncio.create_task(cache.get_source(source))
            second = asyncio.create_task(cache.get_source(source))
            await started.wait()
            release.set()
            results = await asyncio.gather(first, second)

        self.assertEqual(results, [data, data])
        self.assertEqual(fetch.await_count, 1)


if __name__ == "__main__":
    unittest.main()
