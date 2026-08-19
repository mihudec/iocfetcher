import httpx

from iocfetcher.common import LOGGER, ValidatedFeedData, validate_feed_data
from iocfetcher.config import FeedConfig


async def fetch_source(
    source: FeedConfig,
    timeout: float,
) -> ValidatedFeedData:
    """Download and validate one feed, raising if the HTTP request fails."""
    LOGGER.debug(f"Fetching source: '{source.url}'")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            str(source.url),
            headers=source.headers,
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
    data = validate_feed_data(source, response.text)
    LOGGER.debug(
        f"Validated feed: url={source.url} ips={len(data.ips)} "
        f"domains={len(data.domains)} hashes={len(data.hashes)}"
    )
    return data
