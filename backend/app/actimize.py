from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any
from uuid import uuid4

import jwt
import requests

from .config import settings
from .models import EntityExample


class ExternalApiCallError(RuntimeError):
    def __init__(
        self,
        provider: str,
        operation: str,
        endpoint: str,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.provider = str(provider or "").strip().lower() or "unknown"
        self.operation = str(operation or "").strip() or "unknown"
        self.endpoint = str(endpoint or "").strip()
        self.status_code = status_code if isinstance(status_code, int) else None
        self.details = details or {}
        base = f"{self.provider} {self.operation} failed"
        if self.status_code is not None:
            base = f"{base} ({self.status_code})"
        if self.endpoint:
            base = f"{base} at {self.endpoint}"
        super().__init__(f"{base}: {message}")


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


class ActimizeClient:
    def __init__(self) -> None:
        self.base_url = settings.actimize_base_url.rstrip("/")
        self.provider = settings.actimize_provider.strip().lower() or "prudential"
        self.api_key = settings.actimize_api_key
        self.bearer_token = settings.actimize_bearer_token
        self.token_url = settings.actimize_token_url
        self.client_id = settings.actimize_client_id
        self.client_secret = settings.actimize_client_secret
        self.client_assertion_type = settings.actimize_client_assertion_type
        self.client_assertion_algorithm = settings.actimize_client_assertion_algorithm
        self.client_assertion_audience = settings.actimize_client_assertion_audience
        self.client_assertion_kid = settings.actimize_client_assertion_kid
        self.client_assertion_private_key = settings.actimize_client_assertion_private_key
        self.client_assertion_private_key_b64 = settings.actimize_client_assertion_private_key_b64
        self.client_assertion_private_key_path = settings.actimize_client_assertion_private_key_path
        self.scope = settings.actimize_scope
        self.source_system = _sanitize_source_system(settings.actimize_source_system)
        self.default_requester_name = settings.actimize_requester_name.strip() or "SCREENING_SYSTEM"
        self.timeout_s = settings.actimize_timeout_s
        self._cached_access_token = ""
        self._cached_access_token_expires_at = 0.0

    def screen_single(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        return self._screen_via_prudential_api(query, screening_type=screening_type, requester_name=requester_name)

    def _screen_via_prudential_api(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("ACTIMIZE_BASE_URL is required")

        endpoint = f"{self.base_url}/entity-screenings"
        payload = self._build_entity_screening_request(query, requester_name=requester_name)
        try:
            response = requests.post(
                endpoint,
                headers=self._build_headers(),
                json=payload,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=endpoint,
                message=str(exc),
                details={"screening_type": screening_type},
            ) from exc
        if response.status_code >= 400:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=endpoint,
                status_code=int(response.status_code),
                message=self._extract_error_detail(response),
                details={"screening_type": screening_type},
            )

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=endpoint,
                status_code=int(response.status_code),
                message="Screening API returned non-JSON response",
                details={"screening_type": screening_type},
            ) from exc

        logical_status_code: int | None = None
        if isinstance(body, dict) and "status_code" in body and "body" in body:
            raw_status = str(body.get("status_code") or "").strip()
            try:
                logical_status_code = int(raw_status) if raw_status else None
            except ValueError:
                logical_status_code = None

            nested_body = body.get("body")
            if isinstance(nested_body, str):
                try:
                    nested_body = json.loads(nested_body)
                except Exception:
                    nested_body = {"message": nested_body}
            if isinstance(nested_body, dict):
                body = nested_body

        if logical_status_code is not None and logical_status_code >= 400:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=endpoint,
                status_code=logical_status_code,
                message=self._extract_error_detail_from_payload(body),
                details={"screening_type": screening_type},
            )

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
                    merged[key] = dict(candidate)
                    continue

                existing["score"] = max(float(existing.get("score", 0.0) or 0.0), float(candidate.get("score", 0.0) or 0.0))
                existing["match"] = bool(existing.get("match", False) or candidate.get("match", False))

                datasets = existing.get("datasets") if isinstance(existing.get("datasets"), list) else []
                next_datasets = candidate.get("datasets") if isinstance(candidate.get("datasets"), list) else []
                existing["datasets"] = sorted(set([str(x) for x in datasets + next_datasets]))

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
        if not self.token_url or not self.client_id:
            return ""

        now = time.time()
        if self._cached_access_token and now < self._cached_access_token_expires_at:
            return self._cached_access_token

        client_assertion = self._build_client_assertion()
        if not client_assertion and not self.client_secret:
            return ""

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
        }
        if client_assertion:
            payload["client_assertion_type"] = self.client_assertion_type
            payload["client_assertion"] = client_assertion
        elif self.client_secret:
            payload["client_secret"] = self.client_secret
        if self.scope:
            payload["scope"] = self.scope

        try:
            response = requests.post(self.token_url, data=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="oauth_token",
                endpoint=self.token_url,
                message=str(exc),
            ) from exc
        if response.status_code >= 400:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="oauth_token",
                endpoint=self.token_url,
                status_code=int(response.status_code),
                message=self._extract_error_detail(response),
            )

        try:
            body = response.json() if response.content else {}
        except Exception as exc:  # noqa: BLE001
            raise ExternalApiCallError(
                provider=self.provider,
                operation="oauth_token",
                endpoint=self.token_url,
                status_code=int(response.status_code),
                message="OAuth token endpoint returned non-JSON response",
            ) from exc
        access_token = str(body.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("OAuth token response missing access_token")

        expires_in = int(body.get("expires_in") or 300)
        self._cached_access_token = access_token
        self._cached_access_token_expires_at = time.time() + max(expires_in - 60, 30)
        return access_token

    def _build_client_assertion(self) -> str:
        private_key = self._resolve_client_assertion_private_key()
        if not private_key:
            return ""

        now = int(time.time())
        audience = self.client_assertion_audience.strip() or self.token_url
        claims: dict[str, Any] = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": audience,
            "iat": now,
            "exp": now + 120,
            "jti": str(uuid4()),
        }
        headers: dict[str, str] = {"typ": "JWT"}
        if self.client_assertion_kid:
            headers["kid"] = self.client_assertion_kid

        token = jwt.encode(
            claims,
            private_key,
            algorithm=self.client_assertion_algorithm,
            headers=headers,
        )
        return str(token)

    def _resolve_client_assertion_private_key(self) -> str:
        if self.client_assertion_private_key:
            return self.client_assertion_private_key
        if self.client_assertion_private_key_b64:
            raw = base64.b64decode(self.client_assertion_private_key_b64.encode("utf-8"))
            return raw.decode("utf-8")
        if self.client_assertion_private_key_path:
            with open(self.client_assertion_private_key_path, "r", encoding="utf-8") as handle:
                return handle.read()
        return ""

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
        return self._extract_error_detail_from_payload(body)

    @staticmethod
    def _extract_error_detail_from_payload(body: Any) -> str:
        if isinstance(body, dict):
            for key in ("message", "detail", "userMessage", "code"):
                value = body.get(key)
                if value:
                    return str(value)
            return str(body)[:500]
        return str(body)[:500]

    def _normalize_prudential(self, body: dict[str, Any], query: EntityExample, screening_type: str | None = None) -> dict[str, Any]:
        status_value = str(body.get("status") or "").strip().upper()
        message_value = str(body.get("message") or "").strip().upper()

        if message_value == "JSON_VALIDATION_FAILED":
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=f"{self.base_url}/entity-screenings",
                message="Screening API input validation failed",
            )

        is_hit = status_value == "HIT" or message_value in {"PM", "HIT", "MATCH", "POTENTIAL_MATCH"}
        if status_value == "FAILURE" and not is_hit and message_value not in {"NM", "NO_HIT"}:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=f"{self.base_url}/entity-screenings",
                message=f"Screening API returned FAILURE: {message_value or 'UNKNOWN'}",
            )

        normalized_results: list[dict[str, Any]] = []
        if is_hit:
            party_key = str(body.get("partyKey") or self._build_party_key(query))
            display_name = _extract_name(query)
            normalized_results.append(
                {
                    "id": party_key,
                    "caption": f"{display_name} (Potential Match)",
                    "schema": str(query.schema),
                    "match": True,
                    "properties": {
                        "name": [display_name],
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
