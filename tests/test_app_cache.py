import ipaddress
import unittest
from unittest.mock import patch

import iocfetcher.app as app_module
from iocfetcher.common import ValidatedFeedData
from iocfetcher.config import Config


class StubFeedCache:
    def __init__(self, data: ValidatedFeedData) -> None:
        self.data = data
        self.calls = 0
        self.started_with = None
        self.stopped = False

    async def get_sources(self, sources):
        self.calls += 1
        return [(source, self.data) for source in sources]

    def start(self, sources):
        self.started_with = sources

    async def stop(self):
        self.stopped = True


class ResponseCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_starts_and_stops_proactive_feed_refresh(self) -> None:
        config = Config.model_validate({"sources": []})
        feed_cache = StubFeedCache(ValidatedFeedData())

        with (
            patch.object(app_module, "CONFIG", config),
            patch.object(app_module, "FEED_CACHE", feed_cache),
        ):
            async with app_module.lifespan(app_module.app):
                self.assertIs(feed_cache.started_with, config.sources)

        self.assertTrue(feed_cache.stopped)

    async def test_response_cache_remains_in_front_of_feed_cache(self) -> None:
        config = Config.model_validate(
            {
                "server": {"cache": {"expiration": 60, "max_age": 300}},
                "sources": [
                    {
                        "url": "https://example.com/feed.txt",
                        "format": "lines",
                        "categories": ["block"],
                        "types": ["ip"],
                        "scopes": ["common"],
                    }
                ],
            }
        )
        feed_cache = StubFeedCache(
            ValidatedFeedData(
                ips=frozenset({ipaddress.ip_network("8.8.8.8")})
            )
        )
        app_module.CACHE.clear()

        with (
            patch.object(app_module, "CONFIG", config),
            patch.object(app_module, "FEED_CACHE", feed_cache),
        ):
            first = await app_module.get_list(
                typ="ip",
                cat="block",
                scope="common",
                org=None,
                exclude_common=False,
                output_format="plain",
            )
            second = await app_module.get_list(
                typ="ip",
                cat="block",
                scope="common",
                org=None,
                exclude_common=False,
                output_format="plain",
            )

        self.assertEqual(first.body, b"8.8.8.8")
        self.assertEqual(second.body, b"8.8.8.8")
        self.assertEqual(first.headers["x-fetcher-cachehit"], "False")
        self.assertEqual(second.headers["x-fetcher-cachehit"], "True")
        self.assertEqual(feed_cache.calls, 1)


if __name__ == "__main__":
    unittest.main()
