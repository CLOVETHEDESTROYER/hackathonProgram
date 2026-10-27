"""Vision JSON normalization. No network and no boto3."""

from __future__ import annotations

import json
import os
import unittest

os.environ["BEDROCK_MODEL_ID"] = "us.anthropic.claude-sonnet-4-6"
os.environ["BEDROCK_FALLBACK_MODEL_ID"] = "us.amazon.nova-lite-v1:0"

import assess
import vision


def _payload() -> dict:
    recommendations = assess.recommendations_for({"imagery_ok": False}, "buffer")
    return {
        "engine": "heuristic",
        "model_id": None,
        "summary": "Five ground checks still have to be walked.",
        "recommendations": recommendations,
        "top_p0": assess.top_p0(recommendations),
        "signals": {"imagery_ok": False, "b2_feet": 100, "context": "osm"},
        "footprint": {"source": "osm"},
    }


class VisionNormalizeTests(unittest.TestCase):
    def test_png_roundtrip_and_ring_paint(self) -> None:
        colors = [(10, 80, 20)] * 9
        blob = assess.encode_png(3, 3, colors)
        width, height, pixels = assess.parse_png(blob)
        self.assertEqual((width, height), (3, 3))
        self.assertEqual(pixels, colors)
        lat, lon = 35.52, -105.94
        half = 30.0
        north, _ = assess.offset_m(lat, lon, 0, half)
        south, _ = assess.offset_m(lat, lon, 0, -half)
        _, east = assess.offset_m(lat, lon, half, 0)
        _, west = assess.offset_m(lat, lon, -half, 0)
        chip = assess.Chip(3, 3, west, south, east, north, colors, "test")
        painted = assess.annotated_png(chip, assess.circle_ring(1.0), lon, lat, assess.ZONE2_M)
        _, _, out = assess.parse_png(painted)
        self.assertIn((255, 255, 255), out)

    def test_ground_checks_survive_a_partial_model(self) -> None:
        text = json.dumps(
            {
                "summary": "The red ring still has plants.",
                "recommendations": [
                    {
                        "priority": "P0",
                        "zone": "0-5 ft",
                        "title": "Gravel the first 5 feet",
                        "detail": "Plants fill the red ring against the wall.",
                        "evidence": "aerial",
                        "confidence": "high",
                    },
                    {
                        "priority": "P0",
                        "zone": "structure",
                        "title": "Confirm a Class A roof",
                        "detail": "The photo cannot prove the rating.",
                        "evidence": "aerial",
                        "confidence": "low",
                    },
                ],
            }
        )
        recs, summary = vision.parse_model_json(text)
        self.assertIn("red ring", summary)
        roof = next(rec for rec in recs if "Class A" in rec["title"])
        self.assertEqual(roof["evidence"], "ground_required")
        self.assertEqual(roof["priority"], "P0")
        ground = [rec for rec in recs if rec["evidence"] == "ground_required"]
        self.assertEqual(len(ground), 5)
        blob = " ".join(rec["title"] + rec["detail"] for rec in ground).lower()
        for phrase in ("class a", "vent", "gutter", "6 inch", "deck"):
            self.assertIn(phrase, blob)
        self.assertTrue(any(rec["priority"] == "P2" for rec in recs))

    def test_access_denied_tries_nova_then_keeps_rules(self) -> None:
        payload = _payload()
        calls: list[str] = []

        def converse(model_id: str, png: bytes, prompt: str) -> str:
            calls.append(model_id)
            raise vision.ModelFailure("AccessDeniedException", "use case details required", True)

        vision.upgrade(payload, b"\x89PNG-test", converse=converse)
        self.assertEqual(calls, ["us.anthropic.claude-sonnet-4-6", "us.amazon.nova-lite-v1:0"])
        self.assertEqual(payload["engine"], "heuristic")
        self.assertIsNone(payload["model_id"])
        self.assertEqual(payload["bedrock"]["error"], "AccessDeniedException")
        self.assertEqual(len([rec for rec in payload["recommendations"] if rec["evidence"] == "ground_required"]), 5)

    def test_nova_result_is_the_bedrock_path(self) -> None:
        payload = _payload()

        def converse(model_id: str, png: bytes, prompt: str) -> str:
            if model_id.startswith("us.anthropic"):
                raise vision.ModelFailure("AccessDeniedException", "use case", True)
            return json.dumps(
                {
                    "summary": "Clear the first five feet, then walk the structure.",
                    "recommendations": [
                        {
                            "priority": "P0",
                            "zone": "0-5 ft",
                            "title": "Gravel the first 5 feet",
                            "detail": "The red ring is planted.",
                            "evidence": "aerial",
                            "confidence": "med",
                        }
                    ],
                }
            )

        vision.upgrade(payload, b"\x89PNG-test", converse=converse)
        self.assertEqual(payload["engine"], "bedrock")
        self.assertEqual(payload["model_id"], "us.amazon.nova-lite-v1:0")
        self.assertEqual(payload["bedrock"]["primary_error"], "AccessDeniedException")
        self.assertEqual(len(payload["top_p0"]), 5)
        self.assertEqual(payload["top_p0"][0]["title"], "Gravel the first 5 feet")

    def test_missing_chip_skips_the_model(self) -> None:
        payload = _payload()

        def converse(model_id: str, png: bytes, prompt: str) -> str:
            raise AssertionError("model should not be called")

        vision.upgrade(payload, None, converse=converse)
        self.assertEqual(payload["engine"], "heuristic")
        self.assertEqual(payload["bedrock"]["error"], "no_image")

    def test_prompt_mentions_required_ground_checks(self) -> None:
        prompt = vision.build_prompt(_payload())
        for phrase in ("Class A", "1/8 inch", "gutter", "6 inch", "under the deck", "ground_required"):
            self.assertIn(phrase, prompt)
        self.assertLessEqual(vision._max_tokens(), 4096)


if __name__ == "__main__":
    unittest.main()
