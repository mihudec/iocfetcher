import asyncio
import time
import pathlib
import argparse

from fastapi import FastAPI, Query, Response, HTTPException

from iocfetcher.config import Config, IoCCategories, IoCTypes
from iocfetcher.fetcher import fetch_source_list
from iocfetcher.logger import update_logger_level
from iocfetcher.common import *

from typing import Literal

CONFIG = None

CACHE_LOCK = asyncio.Lock()
CACHE = {}

async def get_cached_response(cache_key):
    """Retrieve from cache if valid."""
    async with CACHE_LOCK:
        cached_entry = CACHE.get(cache_key)
        if cached_entry:
            if time.time() - cached_entry["timestamp"] < CONFIG.server.cache.expiration:
                return cached_entry["response_data"]
            else:
                del CACHE[cache_key]  # Remove expired cache
    return None

async def store_in_cache(cache_key, response_data):
    """Store response in cache."""
    async with CACHE_LOCK:
        CACHE[cache_key] = {"timestamp": time.time(), "response_data": response_data}

def serialize_list(data: list, typ: IoCTypes):
    if typ == IoCTypes.IP:
        for ip in data:
            if ip.prefixlen in [32, 128]:
                yield str(ip.network_address)
            else:
                yield str(ip)
    else:
        for x in data:
            yield x

app = FastAPI()


@app.get("/healthz")
def health_check():
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
        results = await fetch_source_list(sources)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config-file",
        dest="config_file",
        required=False,
        default="/app/config.yaml"
    )
    args = parser.parse_args()
    CONFIG = Config.from_config_file(args.config_file)
    update_logger_level(LOGGER, level=CONFIG.server.log_verbosity)
    print(f"Running with config: {args.config_file}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, server_header=False, proxy_headers=True, forwarded_allow_ips="*")