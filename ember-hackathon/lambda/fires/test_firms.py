"""Unit tests for FIRMS CSV → GeoJSON. No network and no MAP_KEY."""

from __future__ import annotations

import unittest

import firms

VIIRS_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
35.02621,-106.64411,300.86,0.39,0.36,2026-10-26,900,N21,VIIRS,n,2.0NRT,279.91,0.48,N
34.10000,-105.20000,320.00,0.40,0.37,2026-10-27,1842,N21,VIIRS,h,2.0NRT,290.00,12.5,D
"""

MODIS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
32.42000,-104.23000,330.1,1.1,1.0,2026-10-27,1730,Aqua,MODIS,82,6.1NRT,295.4,8.2,D
"""


class ParseCsvTests(unittest.TestCase):
    def test_viirs_point_and_labels(self) -> None:
        features = firms.parse_csv(VIIRS_CSV, "VIIRS_NOAA21_NRT")
        self.assertEqual(len(features), 2)
        first = features[0]
        self.assertEqual(first["geometry"], {"type": "Point", "coordinates": [-106.64411, 35.02621]})
        props = first["properties"]
        self.assertEqual(props["source"], "VIIRS_NOAA21_NRT")
        self.assertEqual(props["source_label"], "VIIRS NOAA-21")
        self.assertEqual(props["acquired_at"], "2026-10-26T09:00:00Z")
        self.assertEqual(props["acq_time"], "0900")
        self.assertEqual(props["confidence"], "n")
        self.assertEqual(props["confidence_label"], "nominal")
        self.assertEqual(props["daynight_label"], "night")
        self.assertEqual(props["frp"], 0.48)
        self.assertNotIn("latitude", props)

    def test_modis_numeric_confidence(self) -> None:
        features = firms.parse_csv(MODIS_CSV, "MODIS_NRT")
        props = features[0]["properties"]
        self.assertEqual(props["confidence"], 82)
        self.assertEqual(props["confidence_label"], "82")
        self.assertEqual(props["source_label"], "MODIS Terra/Aqua")
        self.assertEqual(props["daynight_label"], "day")
        self.assertEqual(props["brightness"], 330.1)

    def test_header_only_is_empty(self) -> None:
        header = VIIRS_CSV.splitlines()[0]
        self.assertEqual(firms.parse_csv(header, "VIIRS_SNPP_NRT"), [])

    def test_error_body_redacts_key(self) -> None:
        with self.assertRaises(firms.FirmsRequestError) as caught:
            firms.parse_csv("Invalid MAP_KEY secretvalue", "MODIS_NRT", "secretvalue")
        self.assertNotIn("secretvalue", str(caught.exception))
        self.assertIn("[MAP_KEY]", str(caught.exception))

    def test_skips_bad_coordinates(self) -> None:
        text = "latitude,longitude,frp\nnope,-106.0,1\n35.0,-106.0,2\n"
        features = firms.parse_csv(text, "MODIS_NRT")
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["properties"]["frp"], 2)


class CollectionTests(unittest.TestCase):
    def test_placeholder_does_not_fetch(self) -> None:
        def fetch(*_args: object) -> list[dict[str, object]]:
            raise AssertionError("FIRMS was called")

        with self.assertRaises(firms.MissingMapKey):
            firms.build_collection(
                "REPLACE_ME",
                bbox=firms.DEFAULT_BBOX,
                day_range=2,
                sources=["MODIS_NRT"],
                fetch=fetch,
            )

    def test_merges_sources_and_sorts(self) -> None:
        def fetch(_key: str, source: str, _bbox: str, _day_range: int) -> list[dict[str, object]]:
            if source == "MODIS_NRT":
                raise firms.FirmsRequestError(source, "HTTP 503: busy")
            return firms.parse_csv(VIIRS_CSV, source)

        payload = firms.build_collection(
            "abc123def456",
            bbox=firms.DEFAULT_BBOX,
            day_range=2,
            sources=["VIIRS_NOAA21_NRT", "MODIS_NRT"],
            fetch=fetch,
        )
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(payload["ember"]["count"], 2)
        self.assertEqual(payload["features"][0]["properties"]["acquired_at"], "2026-10-26T09:00:00Z")
        self.assertEqual(payload["features"][1]["properties"]["acquired_at"], "2026-10-27T18:42:00Z")
        by_id = {report["id"]: report for report in payload["ember"]["sources"]}
        self.assertEqual(by_id["MODIS_NRT"]["count"], 0)
        self.assertIn("busy", by_id["MODIS_NRT"]["error"])
        self.assertEqual(by_id["VIIRS_NOAA21_NRT"]["count"], 2)
        self.assertEqual(payload["ember"]["query_bbox"], [-109.05, 31.33, -103.0, 37.0])

    def test_all_sources_failed(self) -> None:
        def fetch(_key: str, source: str, _bbox: str, _day_range: int) -> list[dict[str, object]]:
            raise firms.FirmsRequestError(source, "down")

        with self.assertRaises(firms.CollectionError):
            firms.build_collection(
                "abc123def456",
                sources=["MODIS_NRT"],
                fetch=fetch,
            )

    def test_bbox_and_day_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            firms.parse_bbox("-103,31,-109,37")
        with self.assertRaises(ValueError):
            firms.clamp_day_range(6)

    def test_redact_truncates(self) -> None:
        text = firms.redact("x" * 400, "")
        self.assertLessEqual(len(text), 301)
        self.assertTrue(text.endswith("…"))


if __name__ == "__main__":
    unittest.main()
