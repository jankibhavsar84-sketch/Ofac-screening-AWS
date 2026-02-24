from __future__ import annotations

import hashlib
from typing import Any

import requests

from .config import settings
from .models import EntityExample


def _extract_name(query: EntityExample) -> str:
    names = query.properties.get("name", [])
    if isinstance(names, list) and names:
        return str(names[0]).strip()
    if isinstance(names, str):
        return names.strip()
    return "Unknown"


class ActimizeClient:
    def __init__(self) -> None:
        self.base_url = settings.actimize_base_url.rstrip("/")
        self.api_key = settings.actimize_api_key
        self.timeout_s = settings.actimize_timeout_s
        self.mock = settings.actimize_mock

    def screen_single(self, query: EntityExample) -> dict[str, Any]:
        if self.mock:
            return self._mock_response(query)
        if not self.base_url:
            raise RuntimeError("ACTIMIZE_BASE_URL is required when ACTIMIZE_MOCK=false")

        endpoint = f"{self.base_url}/screen"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"entity": query.model_dump(mode="json")}
        response = requests.post(endpoint, headers=headers, json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        body = response.json()
        return self._normalize(body, query)

    def _normalize(self, body: dict[str, Any], query: EntityExample) -> dict[str, Any]:
        raw_results = body.get("results")
        if not isinstance(raw_results, list):
            raw_results = body.get("hits", [])

        normalized_results = []
        for idx, candidate in enumerate(raw_results):
            if not isinstance(candidate, dict):
                continue
            score = float(candidate.get("score", 0.0) or 0.0)
            normalized_results.append(
                {
                    "id": str(candidate.get("id", f"ACT-{idx + 1}")),
                    "caption": str(candidate.get("caption") or candidate.get("name") or "Unknown"),
                    "schema": str(candidate.get("schema") or query.schema),
                    "score": score,
                    "match": bool(candidate.get("match", score >= 0.7)),
                    "datasets": candidate.get("datasets") if isinstance(candidate.get("datasets"), list) else [],
                    "properties": candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {},
                }
            )

        return {
            "results": normalized_results,
            "total": {"value": len(normalized_results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
        }

    def _mock_response(self, query: EntityExample) -> dict[str, Any]:
        name = _extract_name(query)
        digest = hashlib.sha1(name.lower().encode("utf-8")).hexdigest()
        marker = int(digest[:2], 16)
        hit = marker < 52  # ~20% synthetic hit rate for demos

        if not hit:
            results: list[dict[str, Any]] = []
        else:
            score = round(0.70 + ((marker % 30) / 100), 4)
            results = [
                {
                    "id": f"ACTIMIZE-{digest[:8]}",
                    "caption": f"{name} (Watchlist Candidate)",
                    "schema": query.schema,
                    "score": score,
                    "match": True,
                    "datasets": ["actimize_watchlist"],
                    "properties": {"name": [name]},
                }
            ]

        return {
            "results": results,
            "total": {"value": len(results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
        }

