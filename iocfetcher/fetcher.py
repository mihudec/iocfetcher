import httpx
import asyncio
from config import Config, FeedConfig, FeedFormat
from typing import List, Dict, Tuple

from iocfetcher.common import LOGGER


async def fetch_source(client: httpx.AsyncClient, source: FeedConfig) -> Tuple[FeedConfig, List[str]]:
    """Fetch IoCs from a given source asynchronously."""
    LOGGER.debug(f"Fetching source: '{source.url}'")
    try:
        response = await client.get(str(source.url), headers=source.headers, timeout=10, follow_redirects=True)
        response.raise_for_status()
        
        if source.format == FeedFormat.TEXT_LINES:
            return (source, response.text.splitlines())
        elif source.format == FeedFormat.TEXT:
            return (source, response.text.strip())
        elif source.format == FeedFormat.STIX_PATTER:
            return (source, response.text.splitlines())  # Further STIX parsing might be needed
        else:
            LOGGER.error(f"Unknown format for {source.url}: {source.format}")
    except httpx.HTTPError as e:
        LOGGER.error(f"Failed to fetch {source.url}: {e}")
    
    return (source, [])

async def fetch_source_list(sources: List[FeedConfig]) -> List[Tuple[FeedConfig, List[str]]]:
    """Fetch IoCs from all matching sources asynchronously."""
    results = []
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_source(client, source) for source in sources]
        fetched_data = await asyncio.gather(*tasks, return_exceptions=True)
        
        
        for item in fetched_data:
            if isinstance(item, tuple) and len(item) == 2:
                source, iocs = item
                results.append((source, iocs))  # Deduplicate IoCs per source
            else:
                LOGGER.error(f"Unexpected response format: {item}")  # Debugging output
    
    return results