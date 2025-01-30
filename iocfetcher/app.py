import asyncio
import pathlib
import argparse

from fastapi import FastAPI, Query, Response

from iocfetcher.config import Config, IoCCategories, IoCTypes
from iocfetcher.fetcher import fetch_source_list
from iocfetcher.logger import update_logger_level
from iocfetcher.common import *

from typing import Literal

CONFIG = None

app = FastAPI()

def serialize_list(data: list, typ: IoCTypes):
    if typ == IoCTypes.IP:
        for ip in data:
            yield str(ip).rstrip("/32")
    else:
        for x in data:
            yield x

@app.get("/healthz")
def health_check():
    return Response(jdump({"ready": True}), media_type="application/json")

@app.get("/v1/list")
async def get_list(
    typ: Literal["ip", "domain", "file", "hash"] = Query(..., alias="type"),
    cat: Literal["ioc", "block", "blocklist", "exclude"] = Query(..., alias="category"),
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

    scopes = set()
    scopes.add(scope)
    if not exclude_common:
        scopes.add("COMMON")
    sources = CONFIG.get_sources(typ, cat, list(scopes))
    results = await fetch_source_list(sources)
    iocs = process_feed_data(results)

    headers = {
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=600",
    }

    ioc_list = []
    try:
        ioc_list = iocs[typ][cat]
    except Exception as e:
        pass

    if output_format == "plain":
        return Response("\n".join(serialize_list(ioc_list, typ)), headers=headers, media_type="text/plain")
    if output_format == "json":
        return Response([x for x in serialize_list(ioc_list, typ)], headers=headers, media_type="application/json")



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
    update_logger_level(LOGGER, level=CONFIG.log_verbosity)
    print(f"Running with config: {args.config_file}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, server_header=False)