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


def _map_screening_type_to_dataset(screening_type: str | None) -> str:
    normalized = str(screening_type or "").strip().lower()
    if normalized == "pep":
        return "peps"
    if normalized == "ame":
        return "default"
    if normalized == "fincen 314(a)":
        return "sanctions"
    if normalized == "global sanction":
        return "sanctions"
    return "sanctions"


class ActimizeClient:
    def __init__(self) -> None:
        self.base_url = settings.actimize_base_url.rstrip("/")
        self.api_key = settings.actimize_api_key
        self.timeout_s = settings.actimize_timeout_s
        self.mock = settings.actimize_mock

    def screen_single(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
    ) -> dict[str, Any]:
        if self.mock:
            return self._mock_response(query, screening_type)
        base_url = self.base_url or "https://api.opensanctions.org"
        dataset = _map_screening_type_to_dataset(screening_type)
        endpoint = f"{base_url}/match/{dataset}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"

        payload: dict[str, Any] = {"queries": {"item_1": query.model_dump(mode="json")}}
        params = {"limit": settings.screening_result_limit}

        response = requests.post(endpoint, headers=headers, params=params, json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        body = response.json()
        return self._normalize(body, query)

    def screen_many_types(
        self,
        query: EntityExample,
        screening_types: list[str] | None = None,
        mock_screening: bool = False,
    ) -> dict[str, Any]:
        normalized_types = [safe for safe in [str(t).strip() for t in (screening_types or [])] if safe]
        if not normalized_types:
            normalized_types = ["Sanction"]

        merged: dict[str, dict[str, Any]] = {}
        for screening_type in normalized_types:
            response = self.screen_single(query, screening_type=screening_type, mock_screening=mock_screening)
            results = response.get("results", [])
            if not isinstance(results, list):
                continue

            for candidate in results:
                if not isinstance(candidate, dict):
                    continue

                key = str(candidate.get("id") or candidate.get("caption") or "")
                if not key:
                    key = f"{screening_type}:{len(merged) + 1}"

                existing = merged.get(key)
                if existing is None:
                    copy_candidate = dict(candidate)
                    properties = copy_candidate.get("properties")
                    if not isinstance(properties, dict):
                        properties = {}
                    properties = dict(properties)
                    properties["screeningType"] = [screening_type]
                    copy_candidate["properties"] = properties
                    merged[key] = copy_candidate
                    continue

                existing["score"] = max(float(existing.get("score", 0.0) or 0.0), float(candidate.get("score", 0.0) or 0.0))
                existing["match"] = bool(existing.get("match", False) or candidate.get("match", False))

                datasets = existing.get("datasets") if isinstance(existing.get("datasets"), list) else []
                next_datasets = candidate.get("datasets") if isinstance(candidate.get("datasets"), list) else []
                existing["datasets"] = sorted(set([str(x) for x in datasets + next_datasets]))

                properties = existing.get("properties")
                if not isinstance(properties, dict):
                    properties = {}
                screening = properties.get("screeningType") if isinstance(properties.get("screeningType"), list) else []
                properties["screeningType"] = sorted(set([str(x) for x in screening + [screening_type]]))
                existing["properties"] = properties

        merged_results = sorted(merged.values(), key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return {
            "results": merged_results,
            "total": {"value": len(merged_results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
        }

    def _normalize(self, body: dict[str, Any], query: EntityExample) -> dict[str, Any]:
        raw_results: list[Any] = []
        response_query = query.model_dump(mode="json")
        response_status = int(body.get("status", 200) or 200)

        responses = body.get("responses")
        if isinstance(responses, dict) and responses:
            first = next(iter(responses.values()))
            if isinstance(first, dict):
                first_results = first.get("results")
                if isinstance(first_results, list):
                    raw_results = first_results
                first_query = first.get("query")
                if isinstance(first_query, dict):
                    response_query = first_query
                response_status = int(first.get("status", response_status) or response_status)
        else:
            maybe_results = body.get("results")
            if isinstance(maybe_results, list):
                raw_results = maybe_results
            else:
                maybe_hits = body.get("hits", [])
                raw_results = maybe_hits if isinstance(maybe_hits, list) else []

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
            "query": response_query,
            "status": response_status,
        }

    def _mock_response(self, query: EntityExample, screening_type: str | None = None) -> dict[str, Any]:
        name = _extract_name(query)
        seed = f"{name.lower()}::{(screening_type or '').lower()}"
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
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
                    "properties": {"name": [name], "screeningType": [screening_type or "Sanction"]},
                }
            ]

        return {
            "results": results,
            "total": {"value": len(results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
        }
