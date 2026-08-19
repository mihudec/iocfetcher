import ipaddress
import unittest

from iocfetcher.common import ValidatedFeedData, process_feed_data, validate_feed_data
from iocfetcher.config import FeedConfig


def make_source(**overrides) -> FeedConfig:
    values = {
        "url": "https://example.com/feed.txt",
        "format": "lines",
        "categories": ["block"],
        "types": ["ip", "domain", "hash"],
    }
    values.update(overrides)
    return FeedConfig.model_validate(values)


class FeedValidationTests(unittest.TestCase):
    def test_feed_is_validated_normalized_and_deduplicated(self) -> None:
        source = make_source()
        digest = "ABCDEF0123456789ABCDEF0123456789"
        data = validate_feed_data(
            source,
            f"8.8.8.8\n8.8.8.8\n192.168.1.1\nExample.COM\n{digest}\n",
        )

        self.assertEqual(data.ips, frozenset({ipaddress.ip_network("8.8.8.8")}))
        self.assertEqual(data.domains, frozenset({"example.com"}))
        self.assertEqual(data.hashes, frozenset({digest.lower()}))

    def test_merge_applies_exclusions_after_combining_typed_snapshots(self) -> None:
        block_source = make_source(types=["ip"], categories=["block"])
        exclude_source = make_source(
            url="https://example.com/exclude.txt",
            types=["ip"],
            categories=["exclude"],
        )
        block_data = ValidatedFeedData(
            ips=frozenset(
                {
                    ipaddress.ip_network("8.8.8.8"),
                    ipaddress.ip_network("1.1.1.1"),
                }
            )
        )
        exclude_data = ValidatedFeedData(
            ips=frozenset({ipaddress.ip_network("8.8.8.0/24")})
        )

        result = process_feed_data(
            [(block_source, block_data), (exclude_source, exclude_data)]
        )

        self.assertEqual(
            result["ip"]["block"],
            [ipaddress.ip_network("1.1.1.1")],
        )


if __name__ == "__main__":
    unittest.main()
