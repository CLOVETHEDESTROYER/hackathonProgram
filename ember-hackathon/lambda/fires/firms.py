"""NASA FIRMS Area API client and GeoJSON conversion.

The Area API is CSV only:
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}

DAY_RANGE is 1 to 5. Omitting a date returns the most recent window.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_BBOX = "-109.05,31.33,-103.00,37.00"
DEFAULT_DAY_RANGE = 2
DEFAULT_SOURCES = (
    "VIIRS_NOAA21_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
)
SOURCE_LABELS = {
    "VIIRS_NOAA21_NRT": "VIIRS NOAA-21",
    "VIIRS_NOAA20_NRT": "VIIRS NOAA-20",
    "VIIRS_SNPP_NRT": "VIIRS S-NPP",
    "MODIS_NRT": "MODIS Terra/Aqua",
}
NUMERIC_FIELDS = {
    "bright_ti4",
    "bright_ti5",
    "bright_t31",
    "brightness",
    "scan",
    "track",
    "frp",
    "latitude",
    "longitude",
}
CONFIDENCE_LABELS = {
    "l": "low",
    "n": "nominal",
    "h": "high",
    "low": "low",
    "nominal": "nominal",
    "high": "high",
}
DAYNIGHT_LABELS = {"D": "day", "N": "night"}
USER_AGENT = "ember-hackathon/1.0 (Santa Fe hackathon demo)"
REQUEST_TIMEOUT_SECONDS = 12
AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{day_range}"

Fetch = Callable[[str, str, str, int], list[dict[str, Any]]]


class MissingMapKey(Exception):
    """The FIRMS MAP_KEY is absent or still a placeholder."""


class FirmsRequestError(Exception):
    """One FIRMS source failed. The message must not contain the MAP_KEY."""


class CollectionError(Exception):
    """Every requested source failed."""


def is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {
        "",
        "replace_me",
        "placeholder",
        "changeme",
        "your_map_key",
        "paste_map_key_here",
        "paste_key_here",
        "todo",
        "xxx",
    }:
        return True
    return lowered.startswith("replace") or lowered.startswith("paste_")


def require_map_key(map_key: str) -> str:
    cleaned = (map_key or "").strip()
    if is_placeholder(cleaned):
        raise MissingMapKey(
            "NASA FIRMS MAP_KEY is not set. Put a SecureString at "
            "/ember-hackathon/firms-map-key or export FIRMS_MAP_KEY. "
            "Request a key at https://firms.modaps.eosdis.nasa.gov/api/map_key/"
        )
    return cleaned


def redact(text: str, map_key: str) -> str:
    cleaned = text.replace("\n", " ").strip()
    if map_key:
        cleaned = cleaned.replace(map_key, "[MAP_KEY]")
    if len(cleaned) > 300:
        return cleaned[:300] + "…"
    return cleaned


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = [part.strip() for part in bbox.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    west, south, east, north = (float(part) for part in parts)
    if not (west < east and south < north):
        raise ValueError("bbox order must be west < east and south < north")
    if not (
        -180 <= west <= 180
        and -180 <= east <= 180
        and -90 <= south <= 90
        and -90 <= north <= 90
    ):
        raise ValueError("bbox is outside latitude/longitude range")
    return west, south, east, north


def clamp_day_range(day_range: int) -> int:
    if day_range < 1 or day_range > 5:
        raise ValueError("FIRMS area day range must be from 1 to 5")
    return day_range


def _number(value: str) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 5)


def _acquired_at(acq_date: str, acq_time: str) -> tuple[str, str | None]:
    digits = "".join(character for character in acq_time if character.isdigit())
    if not digits:
        return acq_time, None
    digits = digits.zfill(4)[-4:]
    hour, minute = int(digits[:2]), int(digits[2:])
    if len(acq_date) != 10 or hour > 23 or minute > 59:
        return digits, None
    return digits, f"{acq_date}T{digits[:2]}:{digits[2:]}:00Z"


def _confidence_label(value: object) -> str:
    text = str(value).strip()
    return CONFIDENCE_LABELS.get(text.lower(), text)


def parse_csv(text: str, source: str, map_key: str = "") -> list[dict[str, Any]]:
    payload = text.lstrip("\ufeff").strip()
    if not payload:
        raise FirmsRequestError(source, "FIRMS returned an empty body")
    reader = csv.DictReader(io.StringIO(payload))
    fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
    if "latitude" not in fieldnames or "longitude" not in fieldnames:
        raise FirmsRequestError(source, redact(payload, map_key) or "FIRMS returned no CSV header")

    label = SOURCE_LABELS.get(source, source)
    features: list[dict[str, Any]] = []
    for row in reader:
        raw = {(key or "").strip(): (value or "").strip() for key, value in row.items() if key}
        try:
            latitude = float(raw["latitude"])
            longitude = float(raw["longitude"])
        except (KeyError, ValueError):
            continue
        acq_time, acquired_at = _acquired_at(raw.get("acq_date", ""), raw.get("acq_time", ""))
        properties: dict[str, Any] = {
            "source": source,
            "source_label": label,
        }
        for key, value in raw.items():
            if key in {"latitude", "longitude"} or value == "":
                continue
            if key == "acq_time":
                properties[key] = acq_time
                continue
            if key in NUMERIC_FIELDS or (key == "confidence" and _is_number(value)):
                properties[key] = _number(value)
            else:
                properties[key] = value
        if acquired_at:
            properties["acquired_at"] = acquired_at
        if "confidence" in raw and raw["confidence"] != "":
            properties["confidence_label"] = _confidence_label(raw["confidence"])
        daynight = raw.get("daynight", "")
        if daynight in DAYNIGHT_LABELS:
            properties["daynight_label"] = DAYNIGHT_LABELS[daynight]
        feature_id = f"{source}:{raw.get('acq_date', '')}:{acq_time}:{latitude:.5f}:{longitude:.5f}"
        features.append(
            {
                "type": "Feature",
                "id": feature_id,
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": properties,
            }
        )
    return features


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def fetch_source(map_key: str, source: str, bbox: str, day_range: int) -> list[dict[str, Any]]:
    url = AREA_URL.format(key=map_key, source=source, bbox=bbox, day_range=day_range)
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/csv", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise FirmsRequestError(source, redact(f"HTTP {exc.code}: {detail}", map_key)) from None
    except urllib.error.URLError as exc:
        raise FirmsRequestError(source, redact(str(exc.reason), map_key)) from None
    return parse_csv(body, source, map_key)


def build_collection(
    map_key: str,
    *,
    bbox: str = DEFAULT_BBOX,
    day_range: int = DEFAULT_DAY_RANGE,
    sources: tuple[str, ...] | list[str] = DEFAULT_SOURCES,
    fetch: Fetch = fetch_source,
) -> dict[str, Any]:
    key = require_map_key(map_key)
    west, south, east, north = parse_bbox(bbox)
    day_range = clamp_day_range(day_range)
    if not sources:
        raise ValueError("at least one FIRMS source is required")

    features: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    workers = min(8, len(sources))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch, key, source, bbox, day_range): source for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            label = SOURCE_LABELS.get(source, source)
            try:
                rows = future.result()
            except Exception as exc:
                message = redact(str(exc), key)
                reports.append({"id": source, "label": label, "count": 0, "error": message})
                errors.append(message)
                continue
            reports.append({"id": source, "label": label, "count": len(rows)})
            features.extend(rows)

    if not features and errors:
        raise CollectionError("; ".join(errors))

    features.sort(
        key=lambda feature: (
            str(feature["properties"].get("acquired_at") or ""),
            float(feature["properties"].get("frp") or 0),
        )
    )
    if features:
        longitudes = [feature["geometry"]["coordinates"][0] for feature in features]
        latitudes = [feature["geometry"]["coordinates"][1] for feature in features]
        extent = [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]
    else:
        extent = [west, south, east, north]

    reports.sort(key=lambda report: report["id"])
    return {
        "type": "FeatureCollection",
        "bbox": extent,
        "features": features,
        "ember": {
            "region": "New Mexico",
            "query_bbox": [west, south, east, north],
            "day_range": day_range,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": reports,
            "count": len(features),
            "note": "Satellite hotspots from NASA FIRMS, not confirmed incidents.",
        },
    }


def main() -> None:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    bbox = os.environ.get("FIRMS_BBOX", DEFAULT_BBOX).strip()
    day_range = int(os.environ.get("FIRMS_DAY_RANGE", str(DEFAULT_DAY_RANGE)))
    raw_sources = os.environ.get("FIRMS_SOURCES", ",".join(DEFAULT_SOURCES))
    sources = [part.strip() for part in raw_sources.split(",") if part.strip()]
    json.dump(
        build_collection(key, bbox=bbox, day_range=day_range, sources=sources),
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except (MissingMapKey, CollectionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
