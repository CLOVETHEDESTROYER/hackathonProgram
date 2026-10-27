"""Bedrock vision recommendations, with the ring rules as the safety net.

The primary model is a US Claude Sonnet inference profile. If that invoke
fails because of access, throttle, or timeout, the next call is Nova Lite.
If both fail, the caller keeps the heuristic recommendations already on
the payload. maxTokens is always set.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import assess

PRIMARY_MODEL = "us.anthropic.claude-sonnet-4-6"
FALLBACK_MODEL = "us.amazon.nova-lite-v1:0"
MAX_IMAGE_BYTES = 3_500_000

SYSTEM = (
    "You are EmberGuard, advising a New Mexico homeowner on wildfire home ignition. "
    "You see one nadir aerial photo. Follow the NFPA Home Ignition Zone "
    "(0–5 ft, 5–30 ft, 30–100 ft), IBHS Wildfire Prepared Home, and New Mexico State Forestry. "
    "Do not promise that a house will survive, do not mention insurance discounts, and do not allege a code violation. "
    "A roof class, vent mesh, gutter debris, a 6-inch wall base, and under-deck storage are never visible enough "
    "to close from this photo. Those five stay ground checks. Reply with one JSON object and no markdown."
)

_SOURCE = {
    "aerial": ("NFPA Home Ignition Zone; NM State Forestry", assess.NM_HOME),
    "inferred": ("IBHS Wildfire Prepared Home", assess.IBHS),
    "ground_required": ("IBHS Wildfire Prepared Home; NM State Forestry", assess.NM_HOME),
}

# Word-boundary needles. "vent" must not match "prevent".
_GROUND_NEEDLES = (
    ("class a",),
    ("vent", "vents"),
    ("gutter", "gutters"),
    ("6 inches", "6 inch", "6-inch", "six inch"),
    ("under the deck", "under-deck", "under deck", "under decks"),
)
_WALKTHROUGH_NEEDLES = ("wildfire prepared", "wui", "walkthrough", "santa fe county")


class ModelFailure(Exception):
    def __init__(self, code: str, detail: str, try_next: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.try_next = try_next


def _models() -> list[str]:
    primary = os.environ.get("BEDROCK_MODEL_ID", PRIMARY_MODEL).strip() or PRIMARY_MODEL
    fallback = os.environ.get("BEDROCK_FALLBACK_MODEL_ID", FALLBACK_MODEL).strip()
    models = [primary]
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _max_tokens() -> int:
    raw = os.environ.get("BEDROCK_MAX_TOKENS", "2048")
    try:
        value = int(raw)
    except ValueError:
        return 2048
    return max(256, min(value, 4096))


def _has(text: str, needle: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text) is not None


def _matches(rec: dict[str, Any], needles: tuple[str, ...]) -> bool:
    blob = f"{rec.get('title', '')} {rec.get('detail', '')}".lower()
    return any(_has(blob, needle) for needle in needles)


def _one(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    priority = str(item.get("priority") or "").strip().upper()
    if priority not in {"P0", "P1", "P2"}:
        return None
    evidence = str(item.get("evidence") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if evidence not in _SOURCE:
        return None
    confidence = str(item.get("confidence") or "med").strip().lower()
    if confidence not in {"high", "med", "low"}:
        confidence = "med"
    title = " ".join(str(item.get("title") or "").split())[:140]
    detail = " ".join(str(item.get("detail") or "").split())[:700]
    zone = " ".join(str(item.get("zone") or "property").split())[:40] or "property"
    if not title or not detail:
        return None
    source, url = _SOURCE[evidence]
    return {
        "priority": priority,
        "zone": zone,
        "title": title,
        "detail": detail,
        "evidence": evidence,
        "confidence": confidence,
        "source": source,
        "source_url": url,
    }


def _canonical() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    recs = assess.recommendations_for({"imagery_ok": False}, "buffer")
    ground = [rec for rec in recs if rec["evidence"] == "ground_required"]
    walk = next((rec for rec in recs if rec["priority"] == "P2"), None)
    return ground, walk


def ensure_required(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the model's list, and force the five structural checks plus the walkthrough."""
    ground, walk = _canonical()
    kept: list[dict[str, Any]] = []
    for rec in recs:
        if rec["evidence"] in _SOURCE and rec["priority"] in {"P0", "P1", "P2"}:
            kept.append(rec)
    claimed: set[int] = set()
    for needles in _GROUND_NEEDLES:
        canonical = next(rec for rec in ground if _matches(rec, needles))
        match = next((rec for rec in kept if id(rec) not in claimed and _matches(rec, needles)), None)
        if match is None:
            added = dict(canonical)
            kept.append(added)
            claimed.add(id(added))
            continue
        match["evidence"] = "ground_required"
        match["priority"] = "P0"
        match["source"], match["source_url"] = _SOURCE["ground_required"]
        claimed.add(id(match))
    if walk is not None and not any(_matches(rec, _WALKTHROUGH_NEEDLES) for rec in kept):
        kept.append(dict(walk))
    ordered = assess.sort_recommendations(kept)
    required = [rec for rec in ordered if rec["evidence"] == "ground_required" or rec["priority"] == "P2"]
    rest = [rec for rec in ordered if rec not in required]
    room = max(0, 12 - len(required))
    return assess.sort_recommendations(rest[:room] + required)


def parse_model_json(text: str) -> tuple[list[dict[str, Any]], str]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("json was not an object")
    items = data.get("recommendations")
    if not isinstance(items, list) or not items:
        raise ValueError("recommendations missing")
    parsed = [rec for rec in (_one(item) for item in items) if rec is not None]
    if not parsed:
        raise ValueError("no usable recommendations")
    summary = data.get("summary") if isinstance(data.get("summary"), str) else ""
    summary = " ".join(summary.split())[:400]
    return ensure_required(parsed), summary


def build_prompt(payload: dict[str, Any]) -> str:
    signals = payload.get("signals") or {}
    kept = {
        key: signals.get(key)
        for key in (
            "imagery",
            "hardscape_pct_b0",
            "veg_cover_b0",
            "woody_cover_b1",
            "woody_continuous_b1",
            "sides_with_touching_veg",
            "touch_sides",
            "overhang_flag",
            "min_canopy_distance_ft",
            "outbuildings_within_30_ft",
            "outbuilding_dark_roof",
            "fence_junction",
            "slope_percent",
            "downhill",
            "b2_feet",
            "context",
        )
    }
    footprint = (payload.get("footprint") or {}).get("source") or "buffer"
    outer = kept.get("b2_feet") or 100
    return (
        "The image is a 200 meter aerial chip centered on the property. North is up. "
        f"The white line is the building footprint (source: {footprint}). "
        "If that source is buffer, the white ring is a 10 meter circle because no building was mapped — "
        "say that, and use med or low confidence on distance claims. "
        f"Red ring: 0–5 ft. Orange ring: 5–30 ft. Yellow ring: 30–{outer} ft.\n"
        f"Measured signals, which you may override when the photo disagrees: {json.dumps(kept, default=str)}\n\n"
        'Return JSON: {"summary":"one plain sentence","recommendations":['
        '{"priority":"P0","zone":"0-5 ft","title":"...","detail":"...","evidence":"aerial","confidence":"high"}]}\n'
        "evidence is only aerial, inferred, or ground_required. "
        "confidence is only high, med, or low. priority is only P0, P1, or P2.\n"
        "Emit an aerial or inferred item only when the photo or the signals support it:\n"
        "- 0–5 ft is not mostly gravel, pavement, or bare ground, or plants show in that band: "
        "P0, make the first 5 feet noncombustible.\n"
        "- vegetation against a wall: P0, name the side when you can see it.\n"
        "- canopy over the roof: P0, prune it off the roof and keep about 10 feet off a chimney.\n"
        "- woody cover is continuous between 5 and 30 feet: P0, break the crowns into islands.\n"
        "- mature canopy closer than 10 feet: P0.\n"
        "- a small dark-roof outbuilding within 30 feet: P1, clear about 10 feet around it.\n"
        "- a fence meets the wall: P0 inferred, replace the first 5 feet if it is wood. Omit if no fence is visible.\n"
        "- slope is over about 20 percent: P1, extend the fuel work downhill toward 200 feet.\n"
        "Always include these five P0 items with evidence ground_required: "
        "Class A roof, ember-resistant vents or 1/8 inch mesh, clean gutters, "
        "a 6 inch noncombustible wall base, and nothing stored under the deck.\n"
        "Always include one P2 telling the owner to ask Santa Fe County for a wildland-urban interface "
        "walkthrough and to look at the IBHS Wildfire Prepared Home standard.\n"
        "Six to twelve items. Short sentences. No markdown."
    )


def live_converse(model_id: str, png: bytes, prompt: str) -> str:
    if len(png) > MAX_IMAGE_BYTES:
        raise ModelFailure("image_too_large", "aerial chip exceeded 3.5 MB", False)
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError
    except ImportError as exc:
        raise ModelFailure("no_boto3", "boto3 is not installed", False) from exc

    client = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2",
        config=Config(
            retries={"max_attempts": 2, "mode": "adaptive"},
            read_timeout=18,
            connect_timeout=3,
        ),
    )
    try:
        response = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": "png", "source": {"bytes": png}}},
                        {"text": prompt},
                    ],
                }
            ],
            inferenceConfig={"maxTokens": _max_tokens(), "temperature": 0},
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code") or "ClientError")
        message = str(error.get("Message") or "")
        try_next = code in {
            "AccessDeniedException",
            "ThrottlingException",
            "ServiceUnavailableException",
            "ModelTimeoutException",
            "InternalServerException",
            "ModelNotReadyException",
            "ResourceNotFoundException",
            "ServiceQuotaExceededException",
        } or (code == "ValidationException" and "use case" in message.lower())
        raise ModelFailure(code, message[:180], try_next) from None
    except ReadTimeoutError:
        raise ModelFailure("ReadTimeoutError", "bedrock read timed out", True) from None
    except BotoCoreError as exc:
        raise ModelFailure(type(exc).__name__, str(exc)[:180], True) from None

    blocks = ((response.get("output") or {}).get("message") or {}).get("content") or []
    text = "\n".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
    if not text.strip():
        raise ModelFailure("empty_model", "model returned no text", True)
    return text


def upgrade(
    payload: dict[str, Any],
    png: bytes | None,
    converse: Callable[[str, bytes, str], str] | None = None,
) -> dict[str, Any]:
    """Replace recommendations when a vision model returns valid JSON."""
    if not png:
        payload["engine"] = "heuristic"
        payload["model_id"] = None
        payload["bedrock"] = {"ok": False, "error": "no_image", "tried": []}
        return payload

    caller = converse or live_converse
    prompt = build_prompt(payload)
    tried: list[str] = []
    primary_error: str | None = None
    last: ModelFailure | None = None
    models = _models()
    for index, model_id in enumerate(models):
        tried.append(model_id)
        try:
            text = caller(model_id, png, prompt)
            recommendations, summary = parse_model_json(text)
        except ModelFailure as exc:
            last = exc
            if index == 0:
                primary_error = exc.code
            if not exc.try_next:
                break
            continue
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            last = ModelFailure("bad_json", str(exc)[:180], True)
            if index == 0:
                primary_error = "bad_json"
            continue
        payload["recommendations"] = recommendations
        payload["top_p0"] = assess.top_p0(recommendations)
        if summary:
            payload["summary"] = summary
        payload["engine"] = "bedrock"
        payload["model_id"] = model_id
        payload["bedrock"] = {
            "ok": True,
            "error": None,
            "tried": tried,
            "primary_error": primary_error,
        }
        return payload

    payload["engine"] = "heuristic"
    payload["model_id"] = None
    payload["top_p0"] = assess.top_p0(payload.get("recommendations") or [])
    payload["bedrock"] = {
        "ok": False,
        "error": last.code if last else "bedrock_failed",
        "detail": last.detail if last else "",
        "tried": tried,
        "primary_error": primary_error,
    }
    return payload
