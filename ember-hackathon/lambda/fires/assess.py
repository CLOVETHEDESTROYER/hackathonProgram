"""Property wildfire-prevention assessment for a New Mexico lat/lon.

NAIP comes from the public USGS NAIP image service (PNG). Esri World
Imagery is the fallback. Building outlines come from OpenStreetMap.
Slope comes from USGS 3DEP. Recommendations prefer a Bedrock vision read
of the aerial chip. The signal table is the fallback when that call fails.
"""

from __future__ import annotations

import json
import math
import os
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

FT = 0.3048
ZONE0_M = 5 * FT
TOUCH_M = 3 * FT
CANOPY_CLEAR_M = 10 * FT
ZONE1_M = 30 * FT
ZONE2_M = 100 * FT
ZONE2_STEEP_M = 200 * FT
SLOPE_EXTEND = 20.0
BUFFER_RADIUS_M = 10.0
HALF_WINDOW_M = 100.0
IMAGE_SIZE = 384
NM_WEST, NM_SOUTH, NM_EAST, NM_NORTH = -109.05, 31.33, -103.0, 37.0
USER_AGENT = "ember-hackathon/1.0 (Santa Fe hackathon demo)"
OVERPASS_ENDPOINTS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
)
NAIP_EXPORT = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage"
ESRI_EXPORT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
EPQS = "https://epqs.nationalmap.gov/v1/json"
NM_HOME = "https://www.emnrd.nm.gov/sfd/fire-prevention-programs/protecting-your-home-from-wildfire/"
NFPA_HIZ = "https://www.nfpa.org/education-and-research/wildfire/preparing-homes-for-wildfire"
IBHS = "https://wildfireprepared.org/research/"
SF_WUI = "https://www.santafecountynm.gov/fire/property-assessment-request"
DEMO_LAT = 35.520712
DEMO_LON = -105.937037

_CACHE: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_SECONDS = 600


class BadRequest(Exception):
    """The lat/lon query cannot be assessed."""


class Chip:
    def __init__(
        self,
        width: int,
        height: int,
        west: float,
        south: float,
        east: float,
        north: float,
        pixels: list[tuple[int, int, int]],
        source: str,
    ) -> None:
        self.width = width
        self.height = height
        self.west = west
        self.south = south
        self.east = east
        self.north = north
        self.pixels = pixels
        self.source = source

    def color(self, col: int, row: int) -> tuple[int, int, int]:
        return self.pixels[row * self.width + col]

    def latlon(self, col: int, row: int) -> tuple[float, float]:
        lon = self.west + (col + 0.5) / self.width * (self.east - self.west)
        lat = self.north - (row + 0.5) / self.height * (self.north - self.south)
        return lat, lon


def is_assess_path(path: str) -> bool:
    cleaned = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    return cleaned == "/assess" or cleaned.endswith("/assess")


def parse_lat_lon(lat: Any, lon: Any) -> tuple[float, float]:
    if lat is None or lon is None or lat == "" or lon == "":
        raise BadRequest("Pass lat and lon, for example /assess?lat=35.5207&lon=-105.9370")
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as exc:
        raise BadRequest("lat and lon must be decimal degrees") from exc
    if not (NM_SOUTH <= latitude <= NM_NORTH and NM_WEST <= longitude <= NM_EAST):
        raise BadRequest(
            "lat/lon must be inside the New Mexico box "
            "(-109.05, 31.33, -103.00, 37.00)"
        )
    return latitude, longitude


def offset_m(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat2 = lat + north_m / 111_320
    lon2 = lon + east_m / (111_320 * math.cos(math.radians(lat)))
    return lat2, lon2


def to_xy(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    x = (lon - lon0) * 111_320 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 111_320
    return x, y


def from_xy(x: float, y: float, lon0: float, lat0: float) -> tuple[float, float]:
    lon = lon0 + x / (111_320 * math.cos(math.radians(lat0)))
    lat = lat0 + y / 111_320
    return lon, lat


def signed_area(ring: list[tuple[float, float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        area += x1 * y2 - x2 * y1
    return area / 2


def ensure_closed(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ring:
        return ring
    if ring[0] != ring[-1]:
        return ring + [ring[0]]
    return ring


def ensure_ccw(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    closed = ensure_closed(ring)
    if signed_area(closed) < 0:
        return list(reversed(closed))
    return closed


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _dist_to_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_ring(x: float, y: float, ring: list[tuple[float, float]]) -> float:
    if point_in_ring(x, y, ring):
        return 0.0
    best = float("inf")
    for i in range(len(ring) - 1):
        ax, ay = ring[i]
        bx, by = ring[i + 1]
        best = min(best, _dist_to_seg(x, y, ax, ay, bx, by))
    return best


def ring_gap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    best = float("inf")
    for x, y in a[:-1]:
        best = min(best, distance_to_ring(x, y, b))
    for x, y in b[:-1]:
        best = min(best, distance_to_ring(x, y, a))
    return best


def circle_ring(radius_m: float, segments: int = 64) -> list[tuple[float, float]]:
    points = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        points.append((radius_m * math.sin(angle), radius_m * math.cos(angle)))
    points.append(points[0])
    return points


def _outward_normal(ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    return dy / length, -dx / length


def buffer_ring(ring: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    closed = ensure_ccw(ring)
    pts = closed[:-1]
    count = len(pts)
    if count < 3 or distance <= 0:
        return closed
    outline: list[tuple[float, float]] = []
    for i in range(count):
        prev = pts[(i - 1) % count]
        cur = pts[i]
        nxt = pts[(i + 1) % count]
        n1 = _outward_normal(prev[0], prev[1], cur[0], cur[1])
        n2 = _outward_normal(cur[0], cur[1], nxt[0], nxt[1])
        a1 = math.atan2(n1[1], n1[0])
        a2 = math.atan2(n2[1], n2[0])
        sweep = (a2 - a1) % (2 * math.pi)
        if sweep > math.pi:
            sweep -= 2 * math.pi
        steps = max(1, int(abs(sweep) / (math.pi / 8)))
        for step in range(steps + 1):
            angle = a1 + sweep * step / steps
            outline.append((cur[0] + math.cos(angle) * distance, cur[1] + math.sin(angle) * distance))
    outline.append(outline[0])
    return outline


def classify_rgb(r: int, g: int, b: int) -> str:
    exg = 2 * g - r - b
    bright = (r + g + b) / 3
    is_veg = g >= 35 and exg >= 12 and g + 10 >= r and g > b + 6
    if is_veg and bright < 130:
        return "woody"
    if is_veg:
        return "veg"
    if bright >= 115 and exg < 22:
        return "hard"
    return "other"


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def parse_png(blob: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos + 8 <= len(blob):
        length = struct.unpack(">I", blob[pos : pos + 4])[0]
        kind = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat.extend(data)
        elif kind == b"IEND":
            break
    if width is None or interlace or bit_depth != 8 or color_type not in (2, 6):
        raise ValueError("unsupported png")
    channels = 3 if color_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    prev = bytearray(stride)
    index = 0
    pixels: list[tuple[int, int, int]] = []
    for _row in range(height):
        filter_type = raw[index]
        index += 1
        scan = raw[index : index + stride]
        index += stride
        recon = bytearray(stride)
        for col in range(stride):
            left = recon[col - channels] if col >= channels else 0
            up = prev[col]
            up_left = prev[col - channels] if col >= channels else 0
            raw_byte = scan[col]
            if filter_type == 0:
                value = raw_byte
            elif filter_type == 1:
                value = (raw_byte + left) & 255
            elif filter_type == 2:
                value = (raw_byte + up) & 255
            elif filter_type == 3:
                value = (raw_byte + ((left + up) // 2)) & 255
            elif filter_type == 4:
                value = (raw_byte + _paeth(left, up, up_left)) & 255
            else:
                raise ValueError("unsupported png filter")
            recon[col] = value
        prev = recon
        for col in range(width):
            base = col * channels
            pixels.append((recon[base], recon[base + 1], recon[base + 2]))
    return width, height, pixels


def encode_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        for col in range(width):
            red, green, blue = pixels[row * width + col]
            raw.extend((red & 255, green & 255, blue & 255))
    compressed = zlib.compress(bytes(raw), 6)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def parse_bmp(blob: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
    if len(blob) < 54 or blob[:2] != b"BM":
        raise ValueError("not a bmp")
    offset = struct.unpack_from("<I", blob, 10)[0]
    header_size = struct.unpack_from("<I", blob, 14)[0]
    width, height = struct.unpack_from("<ii", blob, 18)
    bpp = struct.unpack_from("<H", blob, 28)[0]
    compression = struct.unpack_from("<I", blob, 30)[0]
    if header_size < 40 or compression != 0 or bpp not in (24, 32) or width <= 0 or height == 0:
        raise ValueError("unsupported bmp")
    top_down = height < 0
    height = abs(height)
    bytes_per = bpp // 8
    stride = ((width * bytes_per + 3) // 4) * 4
    rows: list[list[tuple[int, int, int]] | None] = [None] * height
    for file_row in range(height):
        visual = file_row if top_down else height - 1 - file_row
        start = offset + file_row * stride
        row: list[tuple[int, int, int]] = []
        for col in range(width):
            pixel = blob[start + col * bytes_per : start + col * bytes_per + 3]
            if len(pixel) < 3:
                raise ValueError("truncated bmp")
            row.append((pixel[2], pixel[1], pixel[0]))
        rows[visual] = row
    pixels = [pixel for row in rows if row is not None for pixel in row]
    return width, height, pixels


def _window(lat: float, lon: float) -> tuple[float, float, float, float]:
    north, _ = offset_m(lat, lon, 0, HALF_WINDOW_M)
    south, _ = offset_m(lat, lon, 0, -HALF_WINDOW_M)
    _, east = offset_m(lat, lon, HALF_WINDOW_M, 0)
    _, west = offset_m(lat, lon, -HALF_WINDOW_M, 0)
    return west, south, east, north


def _get(url: str, timeout: float, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _chip_from_bytes(blob: bytes, bounds: tuple[float, float, float, float], source: str) -> Chip:
    west, south, east, north = bounds
    if blob.startswith(b"\x89PNG"):
        width, height, pixels = parse_png(blob)
    elif blob.startswith(b"BM"):
        width, height, pixels = parse_bmp(blob)
    else:
        raise ValueError("imagery was not png or bmp")
    return Chip(width, height, west, south, east, north, pixels, source)


def fetch_chip(lat: float, lon: float) -> Chip | None:
    bounds = _window(lat, lon)
    west, south, east, north = bounds
    naip = (
        f"{NAIP_EXPORT}?bbox={west},{south},{east},{north}"
        f"&bboxSR=4326&imageSR=4326&size={IMAGE_SIZE},{IMAGE_SIZE}&format=png&f=image"
    )
    esri = (
        f"{ESRI_EXPORT}?bbox={west},{south},{east},{north}"
        f"&bboxSR=4326&imageSR=4326&size={IMAGE_SIZE},{IMAGE_SIZE}&format=bmp&f=image"
    )
    for url, source, timeout in ((naip, "naip", 8), (esri, "esri-world-imagery", 8)):
        try:
            blob = _get(url, timeout)
            return _chip_from_bytes(blob, bounds, source)
        except (urllib.error.URLError, ValueError, TimeoutError, zlib.error, OSError):
            continue
    return None


def _overpass_query(lat: float, lon: float) -> str:
    return (
        f"[out:json][timeout:10];("
        f'way["building"](around:70,{lat},{lon});'
        f'way["barrier"~"^(fence|wall|retaining_wall)$"](around:45,{lat},{lon});'
        f");out geom;"
    )


def fetch_context(lat: float, lon: float) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]], bool]:
    body = urllib.parse.urlencode({"data": _overpass_query(lat, lon)}).encode()
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            raw = _get(endpoint, 8, data=body)
            payload = json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, OSError):
            continue
        buildings: list[list[tuple[float, float]]] = []
        fences: list[list[tuple[float, float]]] = []
        for element in payload.get("elements", []):
            if element.get("type") != "way":
                continue
            geometry = element.get("geometry") or []
            if len(geometry) < 2:
                continue
            ring = [(point["lon"], point["lat"]) for point in geometry]
            tags = element.get("tags") or {}
            if "building" in tags and len(ring) >= 3:
                buildings.append(ensure_closed(ring))
            elif tags.get("barrier") in {"fence", "wall", "retaining_wall"}:
                fences.append(ring)
        return buildings, fences, True
    return [], [], False


def _elevation(lat: float, lon: float) -> float | None:
    url = f"{EPQS}?x={lon}&y={lat}&units=Meters&wkid=4326"
    try:
        payload = json.loads(_get(url, 6).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, OSError, ValueError):
        return None
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return None
    if value < -1000:
        return None
    return value


def fetch_slope(lat: float, lon: float) -> dict[str, Any]:
    samples = [("C", 0.0, 0.0), ("N", 0.0, 30.0), ("E", 30.0, 0.0), ("S", 0.0, -30.0), ("W", -30.0, 0.0)]
    heights: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = []
        for name, east, north in samples:
            sample_lat, sample_lon = offset_m(lat, lon, east, north)
            futures.append((name, east, north, pool.submit(_elevation, sample_lat, sample_lon)))
        for name, east, north, future in futures:
            value = future.result()
            if value is not None:
                heights[name] = value
    center = heights.get("C")
    neighbors = [(name, east, north, heights[name]) for name, east, north, _future in futures if name != "C" and name in heights]
    if center is None or not neighbors:
        return {"available": False}
    lowest = min(neighbors, key=lambda item: item[3])
    grade = (center - lowest[3]) / 30 * 100
    return {
        "available": True,
        "percent": round(max(0.0, grade), 1),
        "downhill": _compass(lowest[1], lowest[2]) if grade > 0 else None,
    }


def _compass(east: float, north: float) -> str:
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    degrees = (math.degrees(math.atan2(east, north)) + 360) % 360
    return names[int((degrees + 22.5) // 45) % 8]


def _side(east: float, north: float) -> str:
    degrees = (math.degrees(math.atan2(east, north)) + 360) % 360
    if degrees < 45 or degrees >= 315:
        return "N"
    if degrees < 135:
        return "E"
    if degrees < 225:
        return "S"
    return "W"


def _xy_ring(ring_ll: list[tuple[float, float]], lon0: float, lat0: float) -> list[tuple[float, float]]:
    return [to_xy(lon, lat, lon0, lat0) for lon, lat in ring_ll]


def choose_footprint(
    buildings: list[list[tuple[float, float]]],
    lat: float,
    lon: float,
) -> tuple[list[tuple[float, float]], str, list[list[tuple[float, float]]]]:
    origin = (0.0, 0.0)
    converted = [_xy_ring(ring, lon, lat) for ring in buildings]
    containing = [ring for ring in converted if point_in_ring(origin[0], origin[1], ring)]
    if containing:
        main = min(containing, key=lambda ring: abs(signed_area(ring)))
        return ensure_ccw(main), "osm", [ring for ring in converted if ring is not main]
    best: list[tuple[float, float]] | None = None
    best_d = 40.0
    for ring in converted:
        count = max(1, len(ring) - 1)
        cx = sum(point[0] for point in ring[:-1]) / count
        cy = sum(point[1] for point in ring[:-1]) / count
        distance = math.hypot(cx, cy)
        if distance < best_d:
            best = ring
            best_d = distance
    if best is not None:
        others = [ring for ring in converted if ring is not best]
        return ensure_ccw(best), "osm", others
    return circle_ring(BUFFER_RADIUS_M), "buffer", []


def _ll_ring(ring_xy: list[tuple[float, float]], lon0: float, lat0: float) -> list[list[float]]:
    return [[round(lon, 6), round(lat, 6)] for lon, lat in (from_xy(x, y, lon0, lat0) for x, y in ring_xy)]


def zone_features(
    footprint: list[tuple[float, float]],
    lon0: float,
    lat0: float,
    b2_m: float,
) -> list[dict[str, Any]]:
    bands = [
        ("0-5 ft", "B0", ZONE0_M, 0.0),
        ("5-30 ft", "B1", ZONE1_M, ZONE0_M),
        ("30-100 ft" if b2_m <= ZONE2_M + 1 else "30-200 ft", "B2", b2_m, ZONE1_M),
    ]
    features = []
    for label, band, outer_m, inner_m in bands:
        outer = buffer_ring(footprint, outer_m)
        hole = footprint if inner_m == 0 else buffer_ring(footprint, inner_m)
        features.append(
            {
                "type": "Feature",
                "properties": {"zone": label, "band": band, "outer_ft": round(outer_m / FT), "inner_ft": round(inner_m / FT)},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        _ll_ring(ensure_ccw(outer), lon0, lat0),
                        list(reversed(_ll_ring(ensure_ccw(hole), lon0, lat0))),
                    ],
                },
            }
        )
    return features


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(var)


def analyze(
    chip: Chip | None,
    footprint: list[tuple[float, float]],
    others: list[list[tuple[float, float]]],
    fences: list[list[tuple[float, float]]],
    lon0: float,
    lat0: float,
    slope: dict[str, Any],
) -> dict[str, Any]:
    b2_m = ZONE2_STEEP_M if slope.get("available") and (slope.get("percent") or 0) > SLOPE_EXTEND else ZONE2_M
    counts = {"B0": {"n": 0, "veg": 0, "hard": 0}, "B1": {"n": 0, "woody": 0}}
    touch = {"N": 0, "E": 0, "S": 0, "W": 0}
    woody_b1: set[tuple[int, int]] = set()
    canopy_dist: float | None = None
    overhang = 0
    if chip is not None:
        for row in range(chip.height):
            for col in range(chip.width):
                lat, lon = chip.latlon(col, row)
                x, y = to_xy(lon, lat, lon0, lat0)
                dist = distance_to_ring(x, y, footprint)
                kind = classify_rgb(*chip.color(col, row))
                if kind == "woody":
                    if canopy_dist is None or dist < canopy_dist:
                        canopy_dist = dist
                    if dist == 0:
                        overhang += 1
                if dist == 0 or dist > b2_m:
                    continue
                if dist <= ZONE0_M:
                    band = counts["B0"]
                    band["n"] += 1
                    if kind in {"veg", "woody"}:
                        band["veg"] += 1
                    elif kind == "hard":
                        band["hard"] += 1
                    if kind in {"veg", "woody"} and dist <= TOUCH_M:
                        touch[_side(x, y)] += 1
                elif dist <= ZONE1_M:
                    counts["B1"]["n"] += 1
                    if kind == "woody":
                        counts["B1"]["woody"] += 1
                        woody_b1.add((col, row))
    b0_n = counts["B0"]["n"]
    b1_n = counts["B1"]["n"]
    veg_cover = counts["B0"]["veg"] / b0_n if b0_n else None
    hardscape = counts["B0"]["hard"] / b0_n if b0_n else None
    woody_cover = counts["B1"]["woody"] / b1_n if b1_n else None
    continuity = _continuity(woody_b1)
    woody_continuous = bool(
        woody_cover is not None and woody_cover > 0.40 and continuity >= 0.50 and counts["B1"]["woody"] >= 12
    )
    sides = sum(1 for count in touch.values() if count >= 3)
    out_count, dark_roof = _outbuildings(chip, footprint, others, lon0, lat0)
    fence = _fence_junction(footprint, fences)
    return {
        "imagery": chip.source if chip else "unavailable",
        "imagery_ok": chip is not None and b0_n > 0,
        "hardscape_pct_b0": None if hardscape is None else round(hardscape, 3),
        "veg_cover_b0": None if veg_cover is None else round(veg_cover, 3),
        "woody_cover_b1": None if woody_cover is None else round(woody_cover, 3),
        "woody_continuous_b1": woody_continuous,
        "sides_with_touching_veg": sides,
        "touch_sides": [side for side, count in touch.items() if count >= 3],
        "overhang_flag": overhang >= 4,
        "min_canopy_distance_ft": None if canopy_dist is None else round(canopy_dist / FT, 1),
        "outbuildings_within_30_ft": out_count,
        "outbuilding_dark_roof": dark_roof,
        "fence_junction": fence,
        "slope_percent": slope.get("percent") if slope.get("available") else None,
        "downhill": slope.get("downhill"),
        "b2_feet": 200 if b2_m > ZONE2_M + 1 else 100,
        "pixels_b0": b0_n,
        "pixels_b1": b1_n,
    }


def _continuity(cells: set[tuple[int, int]]) -> float:
    if not cells:
        return 0.0
    seen: set[tuple[int, int]] = set()
    largest = 0
    for start in cells:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            col, row = stack.pop()
            size += 1
            for nxt in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if nxt in cells and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        largest = max(largest, size)
    return largest / len(cells)


def _outbuildings(
    chip: Chip | None,
    footprint: list[tuple[float, float]],
    others: list[list[tuple[float, float]]],
    lon0: float,
    lat0: float,
) -> tuple[int, bool]:
    close: list[list[tuple[float, float]]] = []
    for ring in others:
        area = abs(signed_area(ensure_closed(ring)))
        if not 6 <= area <= 120:
            continue
        if ring_gap(footprint, ensure_closed(ring)) <= ZONE1_M:
            close.append(ring)
    dark = False
    if chip is not None:
        for ring in close:
            brightness: list[float] = []
            for row in range(0, chip.height, 2):
                for col in range(0, chip.width, 2):
                    lat, lon = chip.latlon(col, row)
                    x, y = to_xy(lon, lat, lon0, lat0)
                    if point_in_ring(x, y, ring):
                        r, g, b = chip.color(col, row)
                        brightness.append((r + g + b) / 3)
            if len(brightness) < 4:
                continue
            mean, std = _mean_std(brightness)
            if mean < 130 and (mean < 110 or std > 18):
                dark = True
                break
    return len(close), dark


def _fence_junction(
    footprint: list[tuple[float, float]],
    fences_xy: list[list[tuple[float, float]]],
) -> bool:
    for fence in fences_xy:
        for x, y in fence:
            if distance_to_ring(x, y, footprint) <= 2.5:
                return True
    return False


def _stroke_m(chip: Chip) -> float:
    mid_col = min(chip.width - 2, max(0, chip.width // 2))
    lat_a, lon_a = chip.latlon(mid_col, chip.height // 2)
    lat_b, lon_b = chip.latlon(mid_col + 1, chip.height // 2)
    meters = math.hypot(*to_xy(lon_b, lat_b, lon_a, lat_a))
    return max(0.6, meters * 2.4)


def annotated_png(
    chip: Chip,
    footprint: list[tuple[float, float]],
    lon0: float,
    lat0: float,
    b2_m: float,
) -> bytes:
    """Draw the footprint and the three home-ignition rings on a PNG chip."""
    stroke = _stroke_m(chip)
    rings = (
        (ZONE0_M, (255, 59, 48)),
        (ZONE1_M, (255, 149, 0)),
        (b2_m, (255, 214, 10)),
    )
    painted = list(chip.pixels)
    for row in range(chip.height):
        for col in range(chip.width):
            lat, lon = chip.latlon(col, row)
            x, y = to_xy(lon, lat, lon0, lat0)
            dist = distance_to_ring(x, y, footprint)
            color = None
            for radius, ring_color in rings:
                if abs(dist - radius) <= stroke:
                    color = ring_color
                    break
            if dist <= stroke and _edge_distance(x, y, footprint) <= stroke:
                color = (255, 255, 255)
            if color is not None:
                painted[row * chip.width + col] = color
    blob = encode_png(chip.width, chip.height, painted)
    if len(blob) <= 3_500_000:
        return blob
    return _downsample_png(chip.width, chip.height, painted)


def _edge_distance(x: float, y: float, ring: list[tuple[float, float]]) -> float:
    best = float("inf")
    for index in range(len(ring) - 1):
        ax, ay = ring[index]
        bx, by = ring[index + 1]
        best = min(best, _dist_to_seg(x, y, ax, ay, bx, by))
    return best


def _downsample_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    next_w = max(1, width // 2)
    next_h = max(1, height // 2)
    small: list[tuple[int, int, int]] = []
    for row in range(next_h):
        for col in range(next_w):
            small.append(pixels[(row * 2) * width + (col * 2)])
    blob = encode_png(next_w, next_h, small)
    if len(blob) <= 3_500_000 or next_w < 64:
        return blob
    return _downsample_png(next_w, next_h, small)


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{round(value * 100)}"


def recommendations_for(signals: dict[str, Any], footprint_source: str) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    imagery_ok = bool(signals.get("imagery_ok"))
    confidence = "med" if footprint_source == "buffer" else "high"

    def add(**kwargs: Any) -> None:
        recs.append(kwargs)

    if imagery_ok:
        hard = signals.get("hardscape_pct_b0")
        veg = signals.get("veg_cover_b0")
        if (hard is not None and hard < 0.70) or (veg is not None and veg > 0.15):
            zone_confidence = "high" if veg is not None and veg > 0.15 else "med"
            if footprint_source == "buffer":
                zone_confidence = "med"
            add(
                priority="P0",
                zone="0-5 ft",
                title="Make the first 5 feet noncombustible",
                detail=(
                    f"In the band within 5 feet of the building, about {_pct(veg)}% of the "
                    f"aerial pixels look like vegetation and about {_pct(hard)}% look like "
                    "bare ground, gravel, or pavement. That band should be gravel, pavers, "
                    "or concrete — no plants, bark mulch, or anything stored against the walls."
                ),
                evidence="aerial",
                confidence=zone_confidence,
                source="IBHS Wildfire Prepared Home; NM State Forestry",
                source_url=NM_HOME,
            )
        sides = [side for side in ("N", "E", "S", "W") if side in (signals.get("touch_sides") or [])]
        if signals.get("sides_with_touching_veg", 0) >= 1 and sides:
            names = {"N": "north", "E": "east", "S": "south", "W": "west"}
            pretty = [names[side] for side in sides]
            if len(pretty) == 1:
                listed = f"the {pretty[0]} side"
            else:
                listed = "the " + ", ".join(pretty[:-1]) + f" and {pretty[-1]} sides"
            add(
                priority="P0",
                zone="0-5 ft",
                title="Clear vegetation against the walls",
                detail=(
                    f"Vegetation shows up within about 3 feet of the building on {listed}. "
                    "That is as close as this aerial photo can place it. Embers and small "
                    "flames catch there, especially at corners."
                ),
                evidence="aerial",
                confidence=confidence,
                source="NFPA Home Ignition Zone; IBHS",
                source_url=NFPA_HIZ,
            )
        if signals.get("overhang_flag"):
            add(
                priority="P0",
                zone="0-5 ft",
                title="Get branches off the roof",
                detail=(
                    "Tree canopy appears to overlap the roof. Prune limbs off the roof and deck, "
                    "and keep branches about 10 feet clear of a chimney."
                ),
                evidence="aerial",
                confidence=confidence,
                source="NFPA; CAL FIRE defensible-space guidance used as best practice",
                source_url=NFPA_HIZ,
            )
        if signals.get("woody_continuous_b1"):
            add(
                priority="P0",
                zone="5-30 ft",
                title="Break the trees into islands",
                detail=(
                    f"Woody cover between 5 and 30 feet is about {_pct(signals.get('woody_cover_b1'))}% "
                    "and it reads as one connected canopy. Separate the crowns, prune ladder fuels, "
                    "and keep plants in small groups rather than a continuous band."
                ),
                evidence="aerial",
                confidence=confidence,
                source="Syphard, Brennan, and Keeley 2014; NFPA",
                source_url=NFPA_HIZ,
            )
        canopy_ft = signals.get("min_canopy_distance_ft")
        if canopy_ft is not None and canopy_ft < 10:
            add(
                priority="P0",
                zone="5-30 ft",
                title="Give mature canopy 10 feet of clearance",
                detail=(
                    f"The nearest dark canopy is about {canopy_ft:.0f} feet from the building. "
                    "Prune or remove so mature crowns stay at least 10 feet off the walls."
                ),
                evidence="aerial",
                confidence=confidence,
                source="NFPA Home Ignition Zone; NM State Forestry",
                source_url=NM_HOME,
            )
        if signals.get("outbuildings_within_30_ft") and signals.get("outbuilding_dark_roof"):
            add(
                priority="P1",
                zone="5-30 ft",
                title="Clear around the nearby outbuilding",
                detail=(
                    "Another small roof sits within 30 feet and looks dark from above. Harden it "
                    "or move it, and keep about 10 feet of bare ground around it."
                ),
                evidence="aerial",
                confidence="med",
                source="IBHS Wildfire Prepared Home",
                source_url=IBHS,
            )
        if signals.get("fence_junction"):
            add(
                priority="P0",
                zone="0-5 ft",
                title="Break the fence where it meets the house",
                detail=(
                    "A mapped fence comes within a few feet of the building. If it is wood, "
                    "replace the first 5 feet with a noncombustible section so it cannot carry "
                    "flame to the wall. Confirm the material on site."
                ),
                evidence="inferred",
                confidence="low",
                source="IBHS Wildfire Prepared Home",
                source_url=IBHS,
            )
        slope = signals.get("slope_percent")
        if slope is not None and slope > SLOPE_EXTEND:
            downhill = signals.get("downhill") or "the downhill"
            add(
                priority="P1",
                zone="30-200 ft",
                title="Extend the work downhill",
                detail=(
                    f"The ground drops about {slope:.0f}% toward the {downhill} over 30 meters. "
                    "Fire runs uphill, so on this slope carry fuel work downhill toward 200 feet "
                    "where you can, especially in piñon-juniper."
                ),
                evidence="aerial",
                confidence="high" if footprint_source == "osm" else "med",
                source="NM Living with Fire; USGS 3DEP",
                source_url=NM_HOME,
            )

    ground = [
        (
            "Confirm a Class A roof",
            "Overhead photos cannot see a roof rating. NM Forestry treats a Class A roof, with defensible space, as a main reason a house survives. Look for composition, metal, or tile — not wood shake — and clear needles off the surface.",
            NM_HOME,
        ),
        (
            "Screen the vents",
            "Use ember-resistant vents, or 1/8-inch metal mesh, on attic, eave, soffit, and foundation vents. Mesh size is not visible from above. Do not permanently block the ventilation.",
            IBHS,
        ),
        (
            "Clean the gutters",
            "Metal gutters are preferred, and they need to be empty of needles and leaves. Debris inside a gutter does not show in a straight-down photo.",
            NM_HOME,
        ),
        (
            "Check the bottom 6 inches of wall",
            "The base of each wall should be a noncombustible surface for at least 6 inches above the ground and above any deck. That joint has to be walked.",
            IBHS,
        ),
        (
            "Nothing stored under the deck",
            "Clear storage and debris from under decks and porches, and screen the underside. A top-down photo cannot see what is underneath.",
            IBHS,
        ),
    ]
    for title, detail, url in ground:
        add(
            priority="P0",
            zone="structure",
            title=title,
            detail=detail,
            evidence="ground_required",
            confidence="high",
            source="IBHS Wildfire Prepared Home; NM State Forestry",
            source_url=url,
        )
    add(
        priority="P2",
        zone="property",
        title="Ask for a local walkthrough",
        detail=(
            "Before fire season, request a Santa Fe County wildland-urban interface assessment "
            "(they pause visits in peak season). New Mexico also points homeowners to the IBHS "
            "Wildfire Prepared Home standard."
        ),
        evidence="inferred",
        confidence="high",
        source="Santa Fe County Fire; IBHS",
        source_url=SF_WUI,
    )
    return sort_recommendations(recs)


def sort_recommendations(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order_p = {"P0": 0, "P1": 1, "P2": 2}
    order_e = {"aerial": 0, "inferred": 1, "ground_required": 2}
    recs.sort(key=lambda rec: (order_p[rec["priority"]], order_e[rec["evidence"]], rec["title"]))
    return recs


def top_p0(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rec for rec in recs if rec.get("priority") == "P0"][:5]


def _summary(signals: dict[str, Any], footprint_source: str) -> str:
    parts: list[str] = []
    if not signals.get("imagery_ok"):
        parts.append("The aerial chip did not load, so the vegetation scores are missing.")
    else:
        veg = signals.get("veg_cover_b0") or 0
        hard = signals.get("hardscape_pct_b0")
        if veg > 0.15:
            parts.append("The first 5 feet look vegetated from above.")
        elif hard is not None and hard < 0.70:
            parts.append("The first 5 feet are not mostly open ground in the photo.")
        else:
            parts.append("The first 5 feet look relatively clear from above.")
    if footprint_source == "buffer":
        parts.append("No mapped building was found, so the rings start from a 10 meter circle.")
    parts.append("Five ground checks still have to be walked.")
    return " ".join(parts)


def build_assessment(
    lat: float,
    lon: float,
    *,
    fetch_buildings: Callable[..., tuple[list[Any], list[Any], bool]] = fetch_context,
    fetch_image: Callable[[float, float], Chip | None] = fetch_chip,
    fetch_grade: Callable[[float, float], dict[str, Any]] = fetch_slope,
) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=3) as pool:
        buildings_future = pool.submit(fetch_buildings, lat, lon)
        image_future = pool.submit(fetch_image, lat, lon)
        slope_future = pool.submit(fetch_grade, lat, lon)
        buildings, fences_ll, overpass_ok = buildings_future.result()
        chip = image_future.result()
        slope = slope_future.result()
    footprint, source, others = choose_footprint(buildings, lat, lon)
    fence_xy = [_xy_ring(fence, lon, lat) for fence in fences_ll]
    signals = analyze(chip, footprint, others, fence_xy, lon, lat, slope)
    if not overpass_ok:
        signals["context"] = "overpass_unavailable"
    else:
        signals["context"] = "osm"
    recs = recommendations_for(signals, source)
    b2_m = ZONE2_STEEP_M if signals["b2_feet"] == 200 else ZONE2_M
    footprint_ll = _ll_ring(footprint, lon, lat)
    image_png = None
    if chip is not None:
        try:
            image_png = annotated_png(chip, footprint, lon, lat, b2_m)
        except (ValueError, zlib.error, OSError):
            image_png = None
    return {
        "type": "PropertyAssessment",
        "assessed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "point": {"lat": lat, "lon": lon},
        "engine": "heuristic",
        "model_id": None,
        "image_png": image_png,
        "footprint": {
            "source": source,
            "geojson": {
                "type": "Feature",
                "properties": {"role": "footprint", "source": source},
                "geometry": {"type": "Polygon", "coordinates": [footprint_ll]},
            },
        },
        "zones": {"type": "FeatureCollection", "features": zone_features(footprint, lon, lat, b2_m)},
        "signals": signals,
        "recommendations": recs,
        "top_p0": top_p0(recs),
        "summary": _summary(signals, source),
        "disclaimer": (
            "Advisory only. Not a substitute for a Santa Fe County WUI assessment, and not a "
            "prediction that a home will survive a fire. Overhead imagery cannot see roof class, "
            "vent mesh, gutter debris, a 6-inch noncombustible wall base, or what is stored under a deck."
        ),
    }


def assess(lat: Any, lon: Any) -> dict[str, Any]:
    latitude, longitude = parse_lat_lon(lat, lon)
    key = (round(latitude, 4), round(longitude, 4))
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > now:
            payload = dict(cached[1])
            payload["cache"] = "memory"
            return payload
    payload = build_assessment(latitude, longitude)
    png = payload.pop("image_png", None)
    payload["cache"] = "fresh"
    if os.environ.get("BEDROCK_ENABLED", "1") == "0":
        payload["bedrock"] = {"ok": False, "error": "disabled", "tried": []}
    else:
        import vision

        vision.upgrade(payload, png if isinstance(png, bytes) else None)
    if payload["signals"].get("context") != "overpass_unavailable":
        ttl = _cache_ttl(payload)
        if ttl:
            with _CACHE_LOCK:
                _CACHE[key] = (now + ttl, payload)
    return payload


def _cache_ttl(payload: dict[str, Any]) -> int:
    bedrock = payload.get("bedrock") or {}
    if bedrock.get("ok") or bedrock.get("error") in {None, "disabled", "no_image"}:
        return CACHE_SECONDS
    error = str(bedrock.get("error") or "")
    if error in {"ThrottlingException", "ReadTimeoutError", "ConnectTimeoutError", "ModelTimeoutException"}:
        return 45
    return 120
