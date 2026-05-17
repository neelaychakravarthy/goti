"""AgentField reasoner: pause for the user to pick listings to negotiate.

Shares ``app`` (and therefore ``app.memory`` + ``app.pause``) with the
other reasoners — see ``_af_app.py``. Invoked by the hunt lifecycle
(``api/orchestration/hunts.py``) once discovery + valuation finish.

The reasoner doesn't do any LLM work itself — it just hands the
``{listing, valuation}`` pairs to the user via ``app.pause()`` and
awaits the user's selection. The bridge router
(``api/routes/agent_bridge.py``) turns the pause into a
``listings_found`` notification + DB-backed approval row; the user POSTs
to ``/api/approvals/{id}`` with
``{decision: "approve", feedback: {picked_listing_ids: [...]}}`` and
the future resumes.

Verified against agentfield 0.1.84.
"""

from __future__ import annotations

import logging

from api.agents._af_app import app

logger = logging.getLogger(__name__)


@app.reasoner()
async def pick_listings(
    hunt_id: str,
    listings_with_valuations: list,
    user_id: str = "",
) -> dict:
    """Pause for the user to pick which listings to negotiate.

    Returns ``{"picked_listing_ids": [...]}`` once the user resolves the
    pause. Empty list on rejection or any non-approve resolution — the
    hunt lifecycle treats that as "close the hunt with no negotiations".
    """
    logger.info(
        "pick_listings: hunt=%s n_listings=%d user=%s",
        hunt_id,
        len(listings_with_valuations),
        user_id,
    )

    approval_request_id = f"hunt-{hunt_id}-pick"
    approval_request_url = f"http://localhost:8000/api/hunts/{hunt_id}"

    payload = {
        "kind": "listings_found",
        "title": f"Found {len(listings_with_valuations)} listings",
        "body": "Pick which listings to negotiate.",
        "hunt_id": hunt_id,
        "user_id": user_id,
        "target_href": f"/c/{hunt_id}",
        "listings_with_valuations": listings_with_valuations,
        "count": len(listings_with_valuations),
    }

    try:
        result = await app.pause(
            approval_request_id=approval_request_id,
            approval_request_url=approval_request_url,
            payload=payload,
        )
    except TypeError:
        # Some AgentField versions don't accept ``payload`` on pause(); fall
        # back to the minimal call. The bridge router upserts the approval
        # row anyway — Goti's pause-payload extension is informational only.
        try:
            result = await app.pause(
                approval_request_id=approval_request_id,
                approval_request_url=approval_request_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("pick_listings: app.pause() raised")
            return {
                "picked_listing_ids": [],
                "approval_status": "pause_failed",
                "error": str(exc),
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("pick_listings: app.pause() raised")
        return {
            "picked_listing_ids": [],
            "approval_status": "pause_failed",
            "error": str(exc),
        }

    feedback = _extract_feedback(result)
    picked: list[str] = []
    if isinstance(feedback, dict):
        raw = (
            feedback.get("picked_listing_ids")
            or feedback.get("listing_ids")
            or feedback.get("picks")
        )
        if isinstance(raw, list):
            picked = [str(i) for i in raw if isinstance(i, (str, int))]
    decision = _extract_decision(result)
    return {
        "picked_listing_ids": picked,
        "approval_status": decision,
    }


def _extract_feedback(result):  # noqa: ANN001 — duck-typed across dict + dataclass
    """Pull the .feedback / .response field off an ApprovalResult-or-dict."""
    if isinstance(result, dict):
        return result.get("feedback") or result.get("response")
    return getattr(result, "feedback", None) or getattr(result, "response", None)


def _extract_decision(result) -> str:  # noqa: ANN001
    if isinstance(result, dict):
        raw = result.get("decision", "approved")
    else:
        raw = getattr(result, "decision", "approved")
    raw = str(raw).lower()
    if raw in ("approve", "approved"):
        return "approved"
    if raw in ("reject", "rejected"):
        return "rejected"
    return raw
