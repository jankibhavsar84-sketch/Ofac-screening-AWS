from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from uuid import uuid4

import requests

from .config import settings
from .models import EntityExample

_ISO2_TO_ISO3: dict[str, str] = {
    "US": "USA",
    "CA": "CAN",
    "GB": "GBR",
    "UK": "GBR",
    "IN": "IND",
    "AU": "AUS",
    "DE": "DEU",
    "FR": "FRA",
    "IT": "ITA",
    "ES": "ESP",
    "NL": "NLD",
    "BE": "BEL",
    "CH": "CHE",
    "IE": "IRL",
    "SE": "SWE",
    "NO": "NOR",
    "DK": "DNK",
    "FI": "FIN",
    "JP": "JPN",
    "CN": "CHN",
    "HK": "HKG",
    "SG": "SGP",
    "AE": "ARE",
    "SA": "SAU",
    "BR": "BRA",
    "MX": "MEX",
    "AR": "ARG",
    "ZA": "ZAF",
    "RU": "RUS",
    "UA": "UKR",
    "TR": "TUR",
    "KR": "KOR",
    "TW": "TWN",
}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        safe = value.strip()
        return [safe] if safe else []
    return []


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        safe = str(value).strip()
        if safe:
            return safe
    return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        safe = value.strip()
        if not safe:
            continue
        key = safe.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(safe)
    return out


def _extract_name(query: EntityExample) -> str:
    props = query.properties if isinstance(query.properties, dict) else {}
    names = _as_list(props.get("name"))
    if names:
        return names[0]
    return "Unknown"


def _split_person_name(full_name: str) -> tuple[str, str]:
    tokens = [token for token in str(full_name or "").strip().split() if token]
    if not tokens:
        return "UNKNOWN", "UNKNOWN"
    if len(tokens) == 1:
        return tokens[0], tokens[0]
    return tokens[0], " ".join(tokens[1:])


def _to_party_type(schema_name: str | None) -> str:
    normalized = str(schema_name or "").strip().lower()
    if normalized in {"person", "individual"}:
        return "I"
    if normalized in {"company", "organization", "legalentity", "unknown", "vessel", "aircraft"}:
        return "E"
    return "U"


def _query_for_provider(query: EntityExample) -> EntityExample:
    normalized_schema = str(query.schema or "").strip().lower()
    if normalized_schema != "unknown":
        return query
    props = query.properties if isinstance(query.properties, dict) else {}
    return EntityExample(schema="Company", properties=dict(props))


def _to_iso3(country: str) -> str:
    safe = str(country or "").strip().upper()
    if not safe:
        return ""
    if len(safe) == 3:
        return safe
    if len(safe) == 2:
        return _ISO2_TO_ISO3.get(safe, "")
    return ""


def _sanitize_source_system(value: str | None) -> str:
    safe = re.sub(r"[^A-Za-z0-9]", "", str(value or "").strip()).upper()
    return safe or "ZIP"


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
        self.provider = settings.actimize_provider.strip().lower() or "opensanctions"
        self.api_key = settings.actimize_api_key
        self.bearer_token = settings.actimize_bearer_token
        self.token_url = settings.actimize_token_url
        self.client_id = settings.actimize_client_id
        self.client_secret = settings.actimize_client_secret
        self.scope = settings.actimize_scope
        self.source_system = _sanitize_source_system(settings.actimize_source_system)
        self.default_requester_name = settings.actimize_requester_name.strip() or "SCREENING_SYSTEM"
        self.timeout_s = settings.actimize_timeout_s
        self.mock = settings.actimize_mock
        self._cached_access_token = ""
        self._cached_access_token_expires_at = 0.0

    def screen_single(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        if self.mock:
            return self._mock_response(query, screening_type)

        if self.provider in {"prudential", "sanctions_api", "sanction-screening"}:
            return self._screen_via_prudential_api(query, screening_type=screening_type, requester_name=requester_name)
        return self._screen_via_opensanctions(query, screening_type=screening_type)

    def _screen_via_opensanctions(
        self,
        query: EntityExample,
        screening_type: str | None = None,
    ) -> dict[str, Any]:
        base_url = self.base_url or "https://api.opensanctions.org"
        dataset = _map_screening_type_to_dataset(screening_type)
        endpoint = f"{base_url.rstrip('/')}/match/{dataset}"

        headers = {"Content-Type": "application/json"}
        auth = self._build_auth_header()
        if auth:
            headers["Authorization"] = auth

        screen_query = _query_for_provider(query)
        payload: dict[str, Any] = {"queries": {"item_1": screen_query.model_dump(mode="json")}}
        params = {"limit": settings.screening_result_limit}

        response = requests.post(
            endpoint,
            headers=headers,
            params=params,
            json=payload,
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenSanctions API error {response.status_code}: {self._extract_error_detail(response)}")

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("OpenSanctions API returned non-JSON response") from exc

        return self._normalize_opensanctions(body, query)

    def _screen_via_prudential_api(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("ACTIMIZE_BASE_URL is required when ACTIMIZE_MOCK=false")

        endpoint = f"{self.base_url}/entity-screenings"
        payload = self._build_entity_screening_request(query, requester_name=requester_name)
        response = requests.post(
            endpoint,
            headers=self._build_headers(),
            json=payload,
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Screening API error {response.status_code}: {self._extract_error_detail(response)}")

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Screening API returned non-JSON response") from exc

        return self._normalize_prudential(body, query, screening_type)

    def screen_many_types(
        self,
        query: EntityExample,
        screening_types: list[str] | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_types = [safe for safe in [str(t).strip() for t in (screening_types or [])] if safe]
        if not normalized_types:
            normalized_types = ["Sanction"]

        merged: dict[str, dict[str, Any]] = {}
        for screening_type in normalized_types:
            response = self.screen_single(
                query,
                screening_type=screening_type,
                mock_screening=mock_screening,
                requester_name=requester_name,
            )
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

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid4()),
        }
        auth = self._build_auth_header()
        if auth:
            headers["Authorization"] = auth
        return headers

    def _build_auth_header(self) -> str:
        if self.bearer_token:
            return f"Bearer {self.bearer_token}"

        dynamic_token = self._load_access_token()
        if dynamic_token:
            return f"Bearer {dynamic_token}"

        if self.api_key:
            return f"ApiKey {self.api_key}"
        return ""

    def _load_access_token(self) -> str:
        if not self.token_url or not self.client_id or not self.client_secret:
            return ""

        now = time.time()
        if self._cached_access_token and now < self._cached_access_token_expires_at:
            return self._cached_access_token

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            payload["scope"] = self.scope

        response = requests.post(self.token_url, data=payload, timeout=self.timeout_s)
        if response.status_code >= 400:
            raise RuntimeError(f"OAuth token request failed ({response.status_code}): {self._extract_error_detail(response)}")

        try:
            body = response.json() if response.content else {}
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("OAuth token endpoint returned non-JSON response") from exc
        access_token = str(body.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("OAuth token response missing access_token")

        expires_in = int(body.get("expires_in") or 300)
        self._cached_access_token = access_token
        self._cached_access_token_expires_at = time.time() + max(expires_in - 60, 30)
        return access_token

    def _build_entity_screening_request(
        self,
        query: EntityExample,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        props = query.properties if isinstance(query.properties, dict) else {}
        party_type = _to_party_type(query.schema)
        names = _as_list(props.get("name"))
        primary_name = _first_non_empty(names) or "Unknown"

        payload: dict[str, Any] = {
            "partyKey": self._build_party_key(query),
            "partyType": party_type,
            "names": {},
            "sourceSystem": self.source_system,
            "requesterName": (requester_name or "").strip() or self.default_requester_name,
        }

        if party_type == "I":
            first_name = _first_non_empty(_as_list(props.get("firstName")))
            last_name = _first_non_empty(_as_list(props.get("lastName")))
            middle_name = _first_non_empty(_as_list(props.get("middleName")))

            derived_first, derived_last = _split_person_name(primary_name)
            first_name = first_name or derived_first
            last_name = last_name or derived_last

            payload["names"] = {
                "firstName": first_name,
                "lastName": last_name,
                "fullName": primary_name,
            }
            if middle_name:
                payload["names"]["middleName"] = middle_name
        else:
            payload["names"] = {"fullName": primary_name}

        aliases = _as_list(props.get("alias")) + _as_list(props.get("aliases")) + names[1:]
        unique_aliases = _dedupe(aliases)
        if unique_aliases:
            payload_aliases: list[dict[str, str]] = []
            for alias in unique_aliases[:10]:
                alias_entry: dict[str, str] = {"fullName": alias}
                if party_type == "I":
                    alias_first, alias_last = _split_person_name(alias)
                    alias_entry["firstName"] = alias_first
                    alias_entry["lastName"] = alias_last
                payload_aliases.append(alias_entry)
            payload["aliases"] = payload_aliases

        countries_raw = _as_list(props.get("nationality")) + _as_list(props.get("country")) + _as_list(props.get("jurisdiction"))
        countries: list[str] = []
        for country in countries_raw:
            iso3 = _to_iso3(country)
            if iso3:
                countries.append(iso3)
        countries = _dedupe(countries)
        if party_type == "I" and countries:
            payload["nationalities"] = [{"country": country} for country in countries[:5]]

        addresses = _as_list(props.get("address"))
        if addresses:
            default_country = countries[0] if countries else ""
            payload_addresses: list[dict[str, str]] = []
            for address in addresses[:5]:
                address_entry: dict[str, str] = {"street1": address}
                if default_country:
                    address_entry["country"] = default_country
                payload_addresses.append(address_entry)
            payload["addresses"] = payload_addresses

        id_numbers = _as_list(props.get("idNumber")) + _as_list(props.get("registrationNumber"))
        unique_ids = _dedupe(id_numbers)
        if unique_ids:
            id_country = countries[0] if countries else ""
            payload_ids: list[dict[str, str]] = []
            default_id_type = "PASSPORT" if party_type == "I" else "TIN"
            for id_value in unique_ids[:5]:
                id_entry: dict[str, str] = {"idType": default_id_type, "idValue": id_value}
                if id_country:
                    id_entry["idCountry"] = id_country
                payload_ids.append(id_entry)
            payload["ids"] = payload_ids

        dob = _first_non_empty(_as_list(props.get("birthDate")) + _as_list(props.get("dateOfBirth")))
        if dob:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", dob):
                payload["dateOfBirth"] = dob
            elif re.match(r"^\d{4}$", dob):
                payload["yearOfBirth"] = dob

        return payload

    def _build_party_key(self, query: EntityExample) -> str:
        normalized = query.model_dump(mode="json")
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16].upper()
        return f"{self.source_system}_{digest}"

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            raw = response.text.strip()
            return raw[:500] if raw else response.reason

        if isinstance(body, dict):
            for key in ("message", "detail", "userMessage", "code"):
                value = body.get(key)
                if value:
                    return str(value)
            return str(body)[:500]
        return str(body)[:500]

    def _normalize_opensanctions(self, body: dict[str, Any], query: EntityExample) -> dict[str, Any]:
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

    def _normalize_prudential(self, body: dict[str, Any], query: EntityExample, screening_type: str | None = None) -> dict[str, Any]:
        status_value = str(body.get("status") or "").strip().upper()
        message_value = str(body.get("message") or "").strip().upper()

        if message_value == "JSON_VALIDATION_FAILED":
            raise RuntimeError("Screening API input validation failed")

        is_hit = status_value == "HIT" or message_value in {"PM", "HIT", "MATCH", "POTENTIAL_MATCH"}
        if status_value == "FAILURE" and not is_hit and message_value not in {"NM", "NO_HIT"}:
            raise RuntimeError(f"Screening API returned FAILURE: {message_value or 'UNKNOWN'}")

        normalized_results: list[dict[str, Any]] = []
        if is_hit:
            party_key = str(body.get("partyKey") or self._build_party_key(query))
            display_name = _extract_name(query)
            normalized_results.append(
                {
                    "id": party_key,
                    "caption": f"{display_name} (Potential Match)",
                    "schema": str(query.schema),
                    "score": 0.99,
                    "match": True,
                    "datasets": ["prudential_sanctions_screening"],
                    "properties": {
                        "name": [display_name],
                        "screeningType": [screening_type or "Sanction"],
                        "engineMessage": [message_value or "PM"],
                        "partyKey": [party_key],
                    },
                }
            )

        return {
            "results": normalized_results,
            "total": {"value": len(normalized_results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
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
