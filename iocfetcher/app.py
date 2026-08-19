import asyncio
import time
import pathlib
from contextlib import asynccontextmanager

import typer
from fastapi import FastAPI, Query, Response, HTTPException

from iocfetcher.config import Config, IoCCategories, IoCTypes
from iocfetcher.feed_cache import FeedCache
from iocfetcher.logger import update_logger_level
from iocfetcher.common import *

from typing import Annotated, Literal

CONFIG: Config = None
FEED_CACHE = FeedCache()

CACHE_LOCK = asyncio.Lock()
CACHE = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if CONFIG is not None:
        FEED_CACHE.start(CONFIG.sources)
    try:
        yield
    finally:
        await FEED_CACHE.stop()

async def get_cached_response(cache_key):
    """Retrieve from cache if valid."""
    async with CACHE_LOCK:
        cached_entry = CACHE.get(cache_key)
        if cached_entry:
            age = time.time() - cached_entry["timestamp"]
            if age < CONFIG.server.cache.expiration:
                LOGGER.debug(f"Response cache hit: key={cache_key} age={age:.1f}s")
                return cached_entry["response_data"]
            else:
                LOGGER.debug(f"Response cache expired: key={cache_key} age={age:.1f}s")
                del CACHE[cache_key]  # Remove expired cache
        else:
            LOGGER.debug(f"Response cache miss: key={cache_key}")
    return None

async def store_in_cache(cache_key, response_data):
    """Store response in cache."""
    async with CACHE_LOCK:
        CACHE[cache_key] = {"timestamp": time.time(), "response_data": response_data}
    LOGGER.debug(f"Stored response cache entry: key={cache_key}")

def serialize_list(data: list, typ: IoCTypes):
    if typ == IoCTypes.IP:
        ipv4, ipv6, _ = summarize_subnets(data)
        for ip in ipv4 + ipv6:
            if ip.prefixlen in [32, 128]:
                yield str(ip.network_address)
            else:
                yield str(ip)
    else:
        for x in data:
            yield x

app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
def health_check():
    LOGGER.debug("Health check requested")
    return Response(jdump({"ready": True}), media_type="application/json", status_code=200)

@app.get("/v1/list")
async def get_list(
    typ: Literal["ip", "domain", "file", "hash"] = Query("ip", alias="type"),
    cat: Literal["ioc", "block", "blocklist", "exclude"] = Query("block", alias="category"),
    scope: str = Query("COMMON"),
    org: str = Query(None),
    exclude_common: bool = Query(False),
    output_format: Literal["plain", "json"] = Query("plain", alias="format")
):
    # Backwards compatibility
    if typ in ["file"]:
        typ = "hash"
    if cat in ["blocklist"]:
        cat = "block"
    if scope == "COMMON" and org is not None:
        scope = org
    scope = scope.lower()

    scopes = set()
    scopes.add(scope)
    if not exclude_common:
        scopes.add("common")
    
    cache_key = ";".join(
        [
            "/v1/list",
            f"{typ=}",
            f"{cat=}",
            f"{scope=}",
            f"{exclude_common=}",
            f"{output_format=}"
        ]
    )

    try:
        response_data = await get_cached_response(cache_key)
        if response_data is not None:
            headers = {
                "Content-Disposition": "inline",
                "Cache-Control": f"public, max-age={CONFIG.server.cache.max_age}",
                "X-Fetcher-Query": cache_key,
                "X-Fetcher-Cachehit": "True"
            }
            media_type = "text/plain" if output_format == "plain" else "application/json"
            return Response(response_data, headers=headers, media_type=media_type)
        
        sources = CONFIG.get_sources(typ, cat, list(scopes))
        results = await FEED_CACHE.get_sources(sources)
        iocs = process_feed_data(results)

        ioc_list = []

        try:
            ioc_list = iocs[typ][cat]
        except Exception as e:
            pass
        
        headers = {
            "Content-Disposition": "inline",
            "Cache-Control": f"public, max-age={CONFIG.server.cache.max_age}",
            "X-Fetcher-Query": cache_key,
            "X-Fetcher-Cachehit": "False"
        }

        if output_format == "plain":
            response_data = "\n".join(serialize_list(ioc_list, typ))
        else:
            response_data = jdump([x for x in serialize_list(ioc_list, typ)])
        await store_in_cache(cache_key, response_data)
        media_type = "text/plain" if output_format == "plain" else "application/json"
        return Response(
            response_data,
            headers=headers,
            media_type=media_type
        )
    except Exception as e:
        LOGGER.critical(msg=f"Unhandled Exception: {repr(e)}")
        return HTTPException(status_code=500)


def main(
    config_file: Annotated[
        pathlib.Path,
        typer.Option(
            "--config-file",
            "-c",
            help="Path to the YAML configuration file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = pathlib.Path("/app/config.yaml"),
) -> None:
    global CONFIG, FEED_CACHE

    CONFIG = Config.from_config_file(config_file)
    FEED_CACHE = FeedCache(default_timeout=CONFIG.server.fetch_timeout)
    update_logger_level(LOGGER, level=CONFIG.server.log_verbosity)
    LOGGER.info(
        f"Application configured: log_verbosity={CONFIG.server.log_verbosity.value} "
        f"sources={len(CONFIG.sources)}"
    )
    typer.echo(f"Running with config: {config_file}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, server_header=False, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    typer.run(main)
