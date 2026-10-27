"""Lambda entry for the New Mexico FIRMS GeoJSON feed.

Direct invokes and GET on the Function URL return a FeatureCollection.
EventBridge (source aws.events) rebuilds the S3 snapshot and does not use
the in-memory cache. FIRMS_MAP_KEY, when set, wins over SSM so local runs
do not need AWS. The value is never written to logs.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

import assess
import firms

PARAM_NAME = os.environ.get("FIRMS_MAP_KEY_PARAM", "/ember-hackathon/firms-map-key")
SNAPSHOT_KEY = os.environ.get("SNAPSHOT_KEY", "fires.geojson")
DOCS_URL = "https://firms.modaps.eosdis.nasa.gov/api/map_key/"

_map_key: str | None = None
_cache_until = 0.0
_cache_payload: dict[str, Any] | None = None
_ssm: Any = None
_s3: Any = None


def _ssm_client() -> Any:
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _s3_client() -> Any:
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _settings() -> tuple[str, int, list[str]]:
    bbox = os.environ.get("FIRMS_BBOX", firms.DEFAULT_BBOX).strip()
    day_range = int(os.environ.get("FIRMS_DAY_RANGE", str(firms.DEFAULT_DAY_RANGE)))
    raw_sources = os.environ.get("FIRMS_SOURCES", ",".join(firms.DEFAULT_SOURCES))
    sources = [part.strip() for part in raw_sources.split(",") if part.strip()]
    return bbox, day_range, sources


def _cache_seconds() -> int:
    raw = os.environ.get("CACHE_SECONDS", "600")
    try:
        seconds = int(raw)
    except ValueError:
        return 600
    return max(0, min(seconds, 3600))


def get_map_key() -> str:
    global _map_key
    env_key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if env_key:
        return firms.require_map_key(env_key)
    if _map_key:
        return _map_key
    try:
        response = _ssm_client().get_parameter(Name=PARAM_NAME, WithDecryption=True)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ParameterNotFound":
            raise firms.MissingMapKey(
                f"SSM parameter {PARAM_NAME} does not exist. Create a SecureString "
                f"there with your NASA FIRMS MAP_KEY ({DOCS_URL})."
            ) from None
        raise
    key = firms.require_map_key(response["Parameter"]["Value"])
    _map_key = key
    return key


def write_snapshot(payload: dict[str, Any]) -> None:
    bucket = os.environ.get("SNAPSHOT_BUCKET", "").strip()
    if not bucket:
        return
    _s3_client().put_object(
        Bucket=bucket,
        Key=SNAPSHOT_KEY,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/geo+json; charset=utf-8",
        CacheControl="public, max-age=60",
    )


def load_payload(*, force: bool) -> dict[str, Any]:
    global _cache_until, _cache_payload
    now = time.time()
    if not force and _cache_payload is not None and now < _cache_until:
        _cache_payload["ember"]["cache"] = "memory"
        return _cache_payload

    bbox, day_range, sources = _settings()
    payload = firms.build_collection(
        get_map_key(),
        bbox=bbox,
        day_range=day_range,
        sources=sources,
    )
    payload["ember"]["cache"] = "fresh"
    try:
        write_snapshot(payload)
    except Exception as exc:
        print(f"snapshot write failed: {type(exc).__name__}")
        if force:
            raise
    _cache_payload = payload
    _cache_until = now + _cache_seconds()
    return payload


def request_method(event: dict[str, Any]) -> str | None:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = http.get("method") or request_context.get("httpMethod")
    if not method:
        return None
    return str(method).upper()


def is_schedule(event: dict[str, Any]) -> bool:
    return event.get("source") == "aws.events"


def event_path(event: dict[str, Any]) -> str:
    path = event.get("rawPath") or event.get("path")
    if not path:
        http = (event.get("requestContext") or {}).get("http") or {}
        path = http.get("path") or "/"
    return str(path)


def handle_assess(event: dict[str, Any]) -> dict[str, Any]:
    params = event.get("queryStringParameters") or {}
    try:
        payload = assess.assess(params.get("lat"), params.get("lon"))
    except assess.BadRequest as exc:
        return http_response(400, {"error": "bad_request", "message": str(exc)})
    except Exception:
        print("assess failed")
        return http_response(
            502,
            {
                "error": "assess_failed",
                "message": "The property assessment failed. Try the point again.",
            },
        )
    print(
        "assess ok "
        f"engine={payload.get('engine')} "
        f"model={payload.get('model_id') or '-'} "
        f"imagery={payload.get('signals', {}).get('imagery')} "
        f"recs={len(payload.get('recommendations', []))}"
    )
    return http_response(200, payload)


def http_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    content_type = "application/geo+json" if payload.get("type") == "FeatureCollection" else "application/json"
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": f"{content_type}; charset=utf-8",
            "Cache-Control": "public, max-age=60" if status == 200 else "no-store",
        },
        "body": json.dumps(payload),
    }


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    incoming = event or {}
    scheduled = is_schedule(incoming)
    method = None if scheduled else request_method(incoming)
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": {}, "body": ""}
    if method not in (None, "GET", "HEAD"):
        return http_response(405, {"error": "method_not_allowed", "message": "Use GET."})
    if not scheduled and assess.is_assess_path(event_path(incoming)):
        return handle_assess(incoming)

    try:
        payload = load_payload(force=scheduled)
    except firms.MissingMapKey as exc:
        print(f"missing map key: {exc}")
        if scheduled:
            return {"ok": False, "error": "missing_map_key"}
        return http_response(
            503,
            {
                "error": "missing_map_key",
                "message": str(exc),
                "parameter": PARAM_NAME,
                "docs": DOCS_URL,
            },
        )
    except firms.CollectionError as exc:
        print(f"firms failed: {exc}")
        if scheduled:
            raise
        return http_response(502, {"error": "firms_unavailable", "message": str(exc)})
    except ValueError as exc:
        print(f"config error: {exc}")
        if scheduled:
            raise
        return http_response(400, {"error": "bad_config", "message": str(exc)})
    except Exception as exc:
        print(f"unhandled: {type(exc).__name__}")
        if scheduled:
            raise
        return http_response(
            500,
            {
                "error": "internal",
                "message": "The feed failed. Check CloudWatch logs for ember-hackathon-fires.",
            },
        )

    count = payload.get("ember", {}).get("count", 0)
    cache = payload.get("ember", {}).get("cache", "")
    print(f"ok count={count} cache={cache} scheduled={scheduled}")
    if scheduled:
        return {"ok": True, "count": count}
    return http_response(200, payload)
