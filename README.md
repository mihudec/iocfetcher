# iocfetcher

## Feed caching

Responses retain the existing short-lived response cache. Each source also has
an independent in-memory cache containing its last successfully validated IoCs.
Feed values are normalized and deduplicated when downloaded, rather than on
every incoming API request.

```yaml
server:
  cache:
    expiration: 60
    max_age: 300
  log_verbosity: info
  fetch_timeout: 30

sources:
  - url: https://example.com/feed.txt
    format: lines
    categories: [block]
    types: [ip]
    scopes: [common]
    refresh_after: 300
    max_stale: 86400
    retry_after: 60
    fetch_timeout: 10
```

- `refresh_after` is the number of seconds a validated feed remains fresh.
- `max_stale` is the maximum total age that can be served while a refresh runs
  or fails. Omit it to allow the last successful snapshot indefinitely.
- `retry_after` prevents a failing stale feed from being retried on every
  request.
- `fetch_timeout` optionally overrides `server.fetch_timeout` for one feed.
- `server.log_verbosity` accepts `debug`, `info`, `warning`, `error`, or
  `critical` (case-insensitive).

All configured feeds are populated in the background when the application
starts. Each successful feed is refreshed again after `refresh_after`; a failed
refresh is retried after `retry_after`. API requests consume the latest validated
snapshot without initiating the normal refresh cycle. A request arriving before
the initial population waits for that feed's in-progress fetch. Snapshots older
than `max_stale` are not served if their refresh fails.

To ensure a periodic consumer sees a completed refresh, configure
`refresh_after` slightly shorter than the consumer's polling interval. For
example, for a consumer polling every 300 seconds, `refresh_after: 240` leaves
time for the source download and validation to finish before the next poll.
