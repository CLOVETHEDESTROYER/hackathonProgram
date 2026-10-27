"""Assessment rules, image decoders, and ring geometry. No network."""

from __future__ import annotations

import struct
import unittest
import zlib

import assess


def _png(colors: list[tuple[int, int, int]], width: int, height: int) -> bytes:
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        for col in range(width):
            r, g, b = colors[row * width + col]
            raw.extend((r, g, b))
    compressed = zlib.compress(bytes(raw))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def _bmp32(colors: list[tuple[int, int, int]], width: int, height: int) -> bytes:
    stride = width * 4
    pixels = bytearray()
    for row in range(height):
        for col in range(width):
            r, g, b = colors[row * width + col]
            pixels.extend((b, g, r, 255))
    header_size = 40
    offset = 14 + header_size
    file_size = offset + len(pixels)
    info = struct.pack("<IiiHHIIiiII", header_size, width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, offset)
    return file_header + info + pixels


class ImageTests(unittest.TestCase):
    def test_png_roundtrip_north_up(self) -> None:
        colors = [(10, 20, 30), (1, 2, 3), (200, 10, 10), (9, 9, 9)]
        width, height, pixels = assess.parse_png(_png(colors, 2, 2))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(pixels, colors)

    def test_bmp32_top_down(self) -> None:
        colors = [(8, 9, 10), (11, 12, 13), (14, 15, 16), (17, 18, 19)]
        width, height, pixels = assess.parse_bmp(_bmp32(colors, 2, 2))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(pixels, colors)


class RuleTests(unittest.TestCase):
    def _signals(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "imagery_ok": True,
            "hardscape_pct_b0": 0.9,
            "veg_cover_b0": 0.02,
            "woody_cover_b1": 0.1,
            "woody_continuous_b1": False,
            "sides_with_touching_veg": 0,
            "touch_sides": [],
            "overhang_flag": False,
            "min_canopy_distance_ft": 24.0,
            "outbuildings_within_30_ft": 0,
            "outbuilding_dark_roof": False,
            "fence_junction": False,
            "slope_percent": 4.0,
            "downhill": "S",
            "b2_feet": 100,
        }
        base.update(overrides)
        return base

    def _titles(self, signals: dict[str, object]) -> list[str]:
        return [rec["title"] for rec in assess.recommendations_for(signals, "osm")]

    def test_clean_photo_still_has_five_ground_checks(self) -> None:
        recs = assess.recommendations_for(self._signals(), "osm")
        ground = [rec for rec in recs if rec["evidence"] == "ground_required"]
        self.assertEqual(len(ground), 5)
        self.assertTrue(all(rec["priority"] == "P0" and rec["confidence"] == "high" for rec in ground))
        blob = " ".join(rec["title"] + rec["detail"] for rec in ground)
        for phrase in ("Class A", "1/8-inch", "gutters", "6 inches", "under the deck"):
            self.assertIn(phrase, blob)
        self.assertNotIn("Make the first 5 feet noncombustible", self._titles(self._signals()))

    def test_zone0_and_slope_and_canopy_rules(self) -> None:
        titles = self._titles(
            self._signals(
                hardscape_pct_b0=0.2,
                veg_cover_b0=0.4,
                sides_with_touching_veg=2,
                touch_sides=["N", "W"],
                overhang_flag=True,
                woody_cover_b1=0.55,
                woody_continuous_b1=True,
                min_canopy_distance_ft=4.0,
                outbuildings_within_30_ft=1,
                outbuilding_dark_roof=True,
                fence_junction=True,
                slope_percent=28.0,
                downhill="SW",
                b2_feet=200,
            )
        )
        for title in (
            "Make the first 5 feet noncombustible",
            "Clear vegetation against the walls",
            "Get branches off the roof",
            "Break the trees into islands",
            "Give mature canopy 10 feet of clearance",
            "Clear around the nearby outbuilding",
            "Break the fence where it meets the house",
            "Extend the work downhill",
        ):
            self.assertIn(title, titles)
        recs = assess.recommendations_for(
            self._signals(veg_cover_b0=0.4, hardscape_pct_b0=0.2),
            "osm",
        )
        evidences = {rec["evidence"] for rec in recs}
        self.assertTrue(evidences <= {"aerial", "inferred", "ground_required"})
        self.assertEqual(recs[0]["priority"], "P0")

    def test_missing_imagery_skips_aerial_rules(self) -> None:
        titles = self._titles(self._signals(imagery_ok=False, veg_cover_b0=None, hardscape_pct_b0=None))
        self.assertNotIn("Make the first 5 feet noncombustible", titles)
        self.assertIn("Confirm a Class A roof", titles)

    def test_hardscape_alone_is_medium_confidence(self) -> None:
        recs = assess.recommendations_for(self._signals(hardscape_pct_b0=0.4, veg_cover_b0=0.05), "osm")
        zone = next(rec for rec in recs if rec["title"].startswith("Make the first"))
        self.assertEqual(zone["confidence"], "med")
        self.assertEqual(zone["evidence"], "aerial")

    def test_nm_bounds(self) -> None:
        with self.assertRaises(assess.BadRequest):
            assess.parse_lat_lon(40, -105)
        lat, lon = assess.parse_lat_lon("35.52", "-105.94")
        self.assertEqual((lat, lon), (35.52, -105.94))
        self.assertTrue(assess.is_assess_path("/assess"))
        self.assertTrue(assess.is_assess_path("/assess/"))
        self.assertFalse(assess.is_assess_path("/"))


class GeometryTests(unittest.TestCase):
    def test_square_distance_and_buffer(self) -> None:
        ring = assess.ensure_ccw([(0, 0), (10, 0), (10, 10), (0, 10)])
        self.assertEqual(assess.distance_to_ring(5, 5, ring), 0)
        self.assertAlmostEqual(assess.distance_to_ring(12, 5, ring), 2, places=5)
        buffered = assess.buffer_ring(ring, 5)
        self.assertGreater(len(buffered), 8)
        self.assertFalse(assess.point_in_ring(0, 0, buffered) and assess.distance_to_ring(-1, 5, ring) < 1)
        outside = [point for point in buffered[:-1] if assess.distance_to_ring(point[0], point[1], ring) > 3]
        self.assertGreater(len(outside), 4)

    def test_green_chip_triggers_zone0(self) -> None:
        lat, lon = 35.52, -105.94
        half = 20
        size = 41
        north, _ = assess.offset_m(lat, lon, 0, half)
        south, _ = assess.offset_m(lat, lon, 0, -half)
        _, east = assess.offset_m(lat, lon, half, 0)
        _, west = assess.offset_m(lat, lon, -half, 0)
        green = [(30, 120, 40)] * (size * size)
        chip = assess.Chip(size, size, west, south, east, north, green, "test")
        footprint = assess.circle_ring(8)
        signals = assess.analyze(chip, footprint, [], [], lon, lat, {"available": False})
        self.assertTrue(signals["imagery_ok"])
        self.assertGreater(signals["veg_cover_b0"], 0.15)
        titles = [rec["title"] for rec in assess.recommendations_for(signals, "buffer")]
        self.assertIn("Make the first 5 feet noncombustible", titles)


if __name__ == "__main__":
    unittest.main()
