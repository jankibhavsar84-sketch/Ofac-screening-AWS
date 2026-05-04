from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from threading import Lock
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl
from uuid import uuid4

import jwt
import requests

from .config import settings
from .models import EntityExample

ACTIMIZE_POST_MAX_ATTEMPTS = 3
# Use Uvicorn's logger so backend API calls reach CloudWatch without extra app logging config.
logger = logging.getLogger("uvicorn.error")
_REDACTED = "***redacted***"
_SENSITIVE_LOG_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer_token",
    "client_assertion",
    "client_secret",
    "id_token",
    "private_key",
    "refresh_token",
    "token",
    "x-api-key",
}


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


def _normalize_prudential_dob(value: str) -> tuple[str | None, str | None]:
    """
    Prudential entity-screenings expects DOB as DD/MM/YYYY (not ISO).

    Returns (dateOfBirth, yearOfBirth).
    """
    raw = str(value or "").strip()
    if not raw:
        return None, None

    if re.match(r"^\\d{4}$", raw):
        return None, raw

    # ISO (or Excel date string) -> DD/MM/YYYY
    if re.match(r"^\\d{4}[-/]\\d{2}[-/]\\d{2}$", raw):
        normalized = raw.replace("/", "-")
        try:
            dt = datetime.strptime(normalized, "%Y-%m-%d").date()
        except ValueError:
            return None, None
        return dt.strftime("%d/%m/%Y"), None

    # Already in expected format.
    if re.match(r"^\\d{2}/\\d{2}/\\d{4}$", raw):
        try:
            datetime.strptime(raw, "%d/%m/%Y")
        except ValueError:
            return None, None
        return raw, None

    # Common variant: DD-MM-YYYY
    if re.match(r"^\\d{2}-\\d{2}-\\d{4}$", raw):
        try:
            dt = datetime.strptime(raw, "%d-%m-%Y").date()
        except ValueError:
            return None, None
        return dt.strftime("%d/%m/%Y"), None

    return None, None


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
    def __init__(self, repository: Any | None = None) -> None:
        self.base_url = settings.actimize_base_url.rstrip("/")
        self.provider = settings.actimize_provider.strip().lower() or "prudential"
        self.repository = repository
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
        self.log_raw_api_io = settings.actimize_log_raw_api_io
        self.raw_api_log_max_chars = max(settings.actimize_raw_api_log_max_chars, 1000)
        self.screening_type_cache_ttl_s = max(int(settings.actimize_screening_type_cache_ttl_s), 0)
        self.screening_type_cache_max_entries = max(int(settings.actimize_screening_type_cache_max_entries), 1)
        self._cached_access_token = ""
        self._cached_access_token_expires_at = 0.0
        self._token_lock = Lock()
        self._screening_type_cache: dict[str, tuple[str, float]] = {}
        self._screening_type_suffix_cache: dict[str, tuple[str, float]] = {}
        self._screening_type_cache_lock = Lock()
        self._screening_type_mapping_lookup_failed = False
        self._screening_type_suffix_lookup_failed = False

    def screen_single(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        return self._screen_via_prudential_api(
            query,
            screening_type=screening_type,
            mock_screening=mock_screening,
            requester_name=requester_name,
        )

    def _screen_via_prudential_api(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("ACTIMIZE_BASE_URL is required")

        endpoint = f"{self.base_url}/entity-screenings"
        payload = self._build_entity_screening_request(
            query,
            screening_type=screening_type,
            mock_screening=mock_screening,
            requester_name=requester_name,
        )
        headers = self._build_headers()
        response = self._post_entity_screening_with_retry(
            endpoint=endpoint,
            headers=headers,
            payload=payload,
            screening_type=screening_type,
        )
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

        body, logical_status_code = self._unwrap_prudential_payload(body)

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

    def _unwrap_prudential_payload(self, payload: Any) -> tuple[dict[str, Any], int | None]:
        logical_status_code: int | None = None
        current: Any = payload

        for _ in range(5):
            if isinstance(current, str):
                safe_current = current.strip()
                if not safe_current:
                    break
                try:
                    current = json.loads(safe_current)
                except Exception:
                    current = {"message": safe_current}

            if not isinstance(current, dict):
                break

            raw_status = str(current.get("status_code") or current.get("statusCode") or "").strip()
            if raw_status:
                try:
                    logical_status_code = int(raw_status)
                except ValueError:
                    pass

            if any(key in current for key in ("message", "detail", "userMessage", "code")):
                return current, logical_status_code

            nested_body = current.get("body")
            if nested_body is None:
                return current, logical_status_code
            current = nested_body

        if isinstance(current, dict):
            return current, logical_status_code
        if isinstance(current, str):
            safe_current = current.strip()
            if safe_current:
                return {"message": safe_current}, logical_status_code
        return {}, logical_status_code

    def _post_entity_screening_with_retry(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        screening_type: str | None,
    ) -> requests.Response:
        last_request_error: requests.RequestException | None = None
        last_response: requests.Response | None = None

        for attempt in range(1, ACTIMIZE_POST_MAX_ATTEMPTS + 1):
            self._log_api_request(
                operation="entity-screenings",
                endpoint=endpoint,
                headers=headers,
                payload=payload,
                screening_type=screening_type,
                attempt=attempt,
                party_key=str(payload.get("partyKey") or "").strip(),
            )
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                last_request_error = exc
                self._log_api_exception(
                    operation="entity-screenings",
                    endpoint=endpoint,
                    headers=headers,
                    payload=payload,
                    exception=exc,
                    screening_type=screening_type,
                    attempt=attempt,
                    party_key=str(payload.get("partyKey") or "").strip(),
                )
                if attempt < ACTIMIZE_POST_MAX_ATTEMPTS:
                    time.sleep(min(0.5 * (2 ** (attempt - 1)), 2.0))
                    continue
                raise ExternalApiCallError(
                    provider=self.provider,
                    operation="entity-screenings",
                    endpoint=endpoint,
                    message=str(exc),
                    details={"screening_type": screening_type, "attempts": attempt},
                ) from exc

            last_response = response
            self._log_api_response(
                operation="entity-screenings",
                endpoint=endpoint,
                headers=headers,
                payload=payload,
                response=response,
                screening_type=screening_type,
                attempt=attempt,
                party_key=str(payload.get("partyKey") or "").strip(),
            )
            if response.status_code in {429, 500, 502, 503, 504} and attempt < ACTIMIZE_POST_MAX_ATTEMPTS:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 2.0))
                continue
            return response

        if last_response is not None:
            return last_response
        if last_request_error is not None:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=endpoint,
                message=str(last_request_error),
                details={"screening_type": screening_type, "attempts": ACTIMIZE_POST_MAX_ATTEMPTS},
            ) from last_request_error
        raise ExternalApiCallError(
            provider=self.provider,
            operation="entity-screenings",
            endpoint=endpoint,
            message="Unknown retry failure",
            details={"screening_type": screening_type, "attempts": ACTIMIZE_POST_MAX_ATTEMPTS},
        )

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

        party_key_overrides_by_type = self._extract_party_keys_by_screening_type(query)
        responses_by_screening_type: dict[str, dict[str, Any]] = {}
        any_hit = False
        for screening_type in normalized_types:
            query_for_screening = query
            override_key = party_key_overrides_by_type.get(self._normalize_screening_type_key(screening_type))
            if override_key:
                props = query.properties if isinstance(query.properties, dict) else {}
                next_props = dict(props)
                next_props["partyKey"] = override_key
                query_for_screening = query.model_copy(deep=True, update={"properties": next_props})

            mapped_screening_type = self._map_screening_type(screening_type)
            response = self.screen_single(
                query_for_screening,
                screening_type=screening_type,
                mock_screening=mock_screening,
                requester_name=requester_name,
            )
            safe_response = dict(response) if isinstance(response, dict) else {}
            safe_response["requested_screening_type"] = screening_type
            safe_response["actimize_screening_type"] = mapped_screening_type or screening_type
            safe_response["party_key"] = self.resolve_party_key(query_for_screening)
            responses_by_screening_type[screening_type] = safe_response
            if self._response_has_positive_match(safe_response):
                any_hit = True

        return {
            "results": [],
            "total": {"value": 0, "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
            "engine_message": "PM" if any_hit else "NM",
            "responses_by_screening_type": responses_by_screening_type,
        }

    @staticmethod
    def _response_has_positive_match(response: dict[str, Any]) -> bool:
        if not isinstance(response, dict):
            return False
        engine_message = str(response.get("engine_message") or "").strip().upper()
        if engine_message == "PM":
            return True
        results = response.get("results")
        if not isinstance(results, list):
            return False
        return any(isinstance(result, dict) and bool(result.get("match")) for result in results)

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

        with self._token_lock:
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

            self._log_api_request(
                operation="oauth_token",
                endpoint=self.token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                payload=payload,
                screening_type=None,
                attempt=1,
                party_key="",
            )
            try:
                response = requests.post(self.token_url, data=payload, timeout=self.timeout_s)
            except requests.RequestException as exc:
                self._log_api_exception(
                    operation="oauth_token",
                    endpoint=self.token_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    payload=payload,
                    exception=exc,
                    screening_type=None,
                    attempt=1,
                    party_key="",
                )
                raise ExternalApiCallError(
                    provider=self.provider,
                    operation="oauth_token",
                    endpoint=self.token_url,
                    message=str(exc),
                ) from exc
            self._log_api_response(
                operation="oauth_token",
                endpoint=self.token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                payload=payload,
                response=response,
                screening_type=None,
                attempt=1,
                party_key="",
            )
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

    @staticmethod
    def _normalize_screening_type_key(value: str | None) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    def _extract_party_keys_by_screening_type(self, query: EntityExample) -> dict[str, str]:
        props = query.properties if isinstance(query.properties, dict) else {}
        raw_mapping = props.get("partyKeysByScreeningType")
        if not isinstance(raw_mapping, dict):
            raw_mapping = props.get("party_keys_by_screening_type")
        if not isinstance(raw_mapping, dict):
            return {}

        out: dict[str, str] = {}
        for raw_type, raw_key in raw_mapping.items():
            normalized_type = self._normalize_screening_type_key(str(raw_type or ""))
            if not normalized_type:
                continue
            resolved_key = _first_non_empty(_as_list(raw_key))
            safe_resolved_key = self._normalize_party_key(resolved_key)
            if safe_resolved_key:
                out[normalized_type] = safe_resolved_key
        return out

    def _get_cached_screening_type(self, normalized_source: str) -> str | None:
        if self.screening_type_cache_ttl_s <= 0 or not normalized_source:
            return None
        now = time.monotonic()
        with self._screening_type_cache_lock:
            cached = self._screening_type_cache.get(normalized_source)
            if cached is None:
                return None
            mapped_value, expires_at = cached
            if now >= expires_at:
                self._screening_type_cache.pop(normalized_source, None)
                return None
            return mapped_value

    def _cache_screening_type(self, normalized_source: str, mapped_value: str) -> None:
        if self.screening_type_cache_ttl_s <= 0 or not normalized_source:
            return
        with self._screening_type_cache_lock:
            if len(self._screening_type_cache) >= self.screening_type_cache_max_entries:
                if normalized_source not in self._screening_type_cache and self._screening_type_cache:
                    self._screening_type_cache.pop(next(iter(self._screening_type_cache)))
            self._screening_type_cache[normalized_source] = (
                mapped_value,
                time.monotonic() + float(self.screening_type_cache_ttl_s),
            )

    def _get_cached_screening_type_suffix(self, normalized_source: str) -> str | None:
        if self.screening_type_cache_ttl_s <= 0 or not normalized_source:
            return None
        now = time.monotonic()
        with self._screening_type_cache_lock:
            cached = self._screening_type_suffix_cache.get(normalized_source)
            if cached is None:
                return None
            suffix_value, expires_at = cached
            if now >= expires_at:
                self._screening_type_suffix_cache.pop(normalized_source, None)
                return None
            return suffix_value

    def _cache_screening_type_suffix(self, normalized_source: str, suffix_value: str) -> None:
        if self.screening_type_cache_ttl_s <= 0 or not normalized_source:
            return
        with self._screening_type_cache_lock:
            if len(self._screening_type_suffix_cache) >= self.screening_type_cache_max_entries:
                if normalized_source not in self._screening_type_suffix_cache and self._screening_type_suffix_cache:
                    self._screening_type_suffix_cache.pop(next(iter(self._screening_type_suffix_cache)))
            self._screening_type_suffix_cache[normalized_source] = (
                suffix_value,
                time.monotonic() + float(self.screening_type_cache_ttl_s),
            )

    @staticmethod
    def _normalize_party_key_suffix(value: str | None) -> str:
        digits = re.sub(r"[^0-9]", "", str(value or "").strip())
        if not digits:
            return ""
        if len(digits) > 3:
            digits = digits[-3:]
        return digits.zfill(3)

    def _resolve_party_key_suffix(self, screening_type: str | None) -> str:
        safe = str(screening_type or "").strip()
        if not safe:
            return ""
        normalized_source = self._normalize_screening_type_key(safe)
        cached = self._get_cached_screening_type_suffix(normalized_source)
        if cached is not None:
            return cached

        suffix_value = ""
        if self.repository is not None and hasattr(self.repository, "resolve_actimize_party_key_suffix"):
            try:
                resolved = self.repository.resolve_actimize_party_key_suffix(safe)
                suffix_value = self._normalize_party_key_suffix(str(resolved or ""))
                self._screening_type_suffix_lookup_failed = False
            except Exception as exc:  # noqa: BLE001
                if not self._screening_type_suffix_lookup_failed:
                    logger.warning(
                        "actimize screeningType suffix lookup failed; falling back source=%s error=%s",
                        safe,
                        exc,
                    )
                self._screening_type_suffix_lookup_failed = True

        self._cache_screening_type_suffix(normalized_source, suffix_value)
        return suffix_value

    def _map_screening_type(self, screening_type: str | None) -> str:
        safe = str(screening_type or "").strip()
        if not safe:
            return ""

        normalized_source = self._normalize_screening_type_key(safe)
        cached = self._get_cached_screening_type(normalized_source)
        if cached:
            return cached

        mapped_value = ""
        if self.repository is not None and hasattr(self.repository, "resolve_actimize_screening_type"):
            try:
                mapped = str(self.repository.resolve_actimize_screening_type(safe) or "").strip()
                if mapped:
                    self._screening_type_mapping_lookup_failed = False
                    mapped_value = mapped
            except Exception as exc:  # noqa: BLE001
                if not self._screening_type_mapping_lookup_failed:
                    logger.warning(
                        "actimize screeningType mapping lookup failed; using passthrough value source=%s error=%s",
                        safe,
                        exc,
                    )
                self._screening_type_mapping_lookup_failed = True

        if not mapped_value:
            mapped_value = safe

        self._cache_screening_type(normalized_source, mapped_value)
        return mapped_value

    def _build_entity_screening_request(
        self,
        query: EntityExample,
        screening_type: str | None = None,
        mock_screening: bool = False,
        requester_name: str | None = None,
    ) -> dict[str, Any]:
        props = query.properties if isinstance(query.properties, dict) else {}
        explicit_party_key = _first_non_empty(
            _as_list(props.get("partyKey"))
            + _as_list(props.get("party_key"))
            + _as_list(props.get("PartyKey"))
            + _as_list(props.get("party key"))
        )
        party_key = self._normalize_party_key(explicit_party_key or self._build_party_key(query))
        party_type = _to_party_type(query.schema)
        names = _as_list(props.get("name"))

        payload: dict[str, Any] = {
            "partyKey": party_key,
            "partyType": party_type,
            "names": {},
            "sourceSystem": self.source_system,
            "requesterName": (requester_name or "").strip() or self.default_requester_name,
            "mock": bool(mock_screening),
        }
        mapped_screening_type = self._map_screening_type(screening_type)
        if mapped_screening_type:
            payload["screeningType"] = mapped_screening_type
        business_unit = _first_non_empty(
            _as_list(props.get("businessUnit"))
            + _as_list(props.get("business_unit"))
            + _as_list(props.get("businessUnitCode"))
            + _as_list(props.get("business_unit_code"))
        )
        if business_unit:
            payload["businessUnit"] = business_unit

        if party_type == "I":
            first_name = _first_non_empty(_as_list(props.get("firstName")))
            last_name = _first_non_empty(_as_list(props.get("lastName")))
            middle_name = _first_non_empty(_as_list(props.get("middleName")))
            maiden_name = _first_non_empty(_as_list(props.get("maidenName")))
            full_name = _first_non_empty(_as_list(props.get("fullName")) + names)

            payload_names: dict[str, str] = {}
            if first_name:
                payload_names["firstName"] = first_name
            if middle_name:
                payload_names["middleName"] = middle_name
            if last_name:
                payload_names["lastName"] = last_name
            if maiden_name:
                payload_names["maidenName"] = maiden_name
            if full_name:
                payload_names["fullName"] = full_name
            if not payload_names:
                payload_names["fullName"] = "Unknown"
            payload["names"] = payload_names
        else:
            full_name = _first_non_empty(_as_list(props.get("fullName")) + names) or "Unknown"
            payload["names"] = {"fullName": full_name}

        payload_aliases: list[dict[str, str]] = []
        seen_alias_keys: set[str] = set()

        def _append_alias(alias_entry: dict[str, str]) -> None:
            compact = {k: v for k, v in alias_entry.items() if str(v).strip()}
            if not compact:
                return
            alias_key = json.dumps(compact, sort_keys=True, ensure_ascii=False).casefold()
            if alias_key in seen_alias_keys:
                return
            seen_alias_keys.add(alias_key)
            payload_aliases.append(compact)

        for alias in _dedupe(_as_list(props.get("alias")) + names[1:]):
            _append_alias({"fullName": alias})

        raw_aliases = props.get("aliases")
        if isinstance(raw_aliases, list):
            for raw_alias in raw_aliases:
                if isinstance(raw_alias, str):
                    safe_alias = raw_alias.strip()
                    if safe_alias:
                        _append_alias({"fullName": safe_alias})
                    continue
                if isinstance(raw_alias, dict):
                    _append_alias(
                        {
                            "firstName": _first_non_empty(_as_list(raw_alias.get("firstName"))),
                            "middleName": _first_non_empty(_as_list(raw_alias.get("middleName"))),
                            "lastName": _first_non_empty(_as_list(raw_alias.get("lastName"))),
                            "maidenName": _first_non_empty(_as_list(raw_alias.get("maidenName"))),
                            "fullName": _first_non_empty(_as_list(raw_alias.get("fullName"))),
                        }
                    )

        if payload_aliases:
            payload["aliases"] = payload_aliases[:10]

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

        payload_ids: list[dict[str, str]] = []
        default_id_type = "PASSPORT" if party_type == "I" else "TIN"
        default_id_country = countries[0] if countries else ""
        raw_ids = props.get("ids")
        if isinstance(raw_ids, list):
            for raw_id in raw_ids[:5]:
                if not isinstance(raw_id, dict):
                    continue
                id_value = _first_non_empty(
                    _as_list(raw_id.get("idValue"))
                    + _as_list(raw_id.get("idNumber"))
                )
                if not id_value:
                    continue
                id_type = _first_non_empty(_as_list(raw_id.get("idType"))) or default_id_type
                raw_country = _first_non_empty(
                    _as_list(raw_id.get("idCountry"))
                    + _as_list(raw_id.get("idIssueCountry"))
                )
                id_country = _to_iso3(raw_country) or raw_country or default_id_country
                id_entry: dict[str, str] = {"idType": id_type, "idValue": id_value}
                if id_country:
                    id_entry["idCountry"] = id_country
                payload_ids.append(id_entry)

        if not payload_ids:
            id_numbers = _as_list(props.get("idNumber")) + _as_list(props.get("registrationNumber"))
            unique_ids = _dedupe(id_numbers)
            for id_value in unique_ids[:5]:
                id_entry: dict[str, str] = {"idType": default_id_type, "idValue": id_value}
                if default_id_country:
                    id_entry["idCountry"] = default_id_country
                payload_ids.append(id_entry)

        if payload_ids:
            payload["ids"] = payload_ids

        dob = _first_non_empty(_as_list(props.get("birthDate")) + _as_list(props.get("dateOfBirth")))
        if dob:
            dob_date, dob_year = _normalize_prudential_dob(dob)
            if dob_date:
                payload["dateOfBirth"] = dob_date
            elif dob_year:
                payload["yearOfBirth"] = dob_year

        birth_location = _first_non_empty(
            _as_list(props.get("birthLocation"))
            + _as_list(props.get("countryOfBirth"))
            + _as_list(props.get("birthCountry"))
            + _as_list(props.get("BirthLocation"))
        )
        if birth_location:
            payload["countryofBirth"] = _to_iso3(birth_location) or birth_location

        gender = _first_non_empty(_as_list(props.get("gender")) + _as_list(props.get("Gender")))
        if gender:
            payload["gender"] = str(gender).strip().upper()

        title = _first_non_empty(_as_list(props.get("title")) + _as_list(props.get("Title")))
        if title:
            payload["title"] = title

        screening_notes = _first_non_empty(
            _as_list(props.get("screeningNotes"))
            + _as_list(props.get("screening_notes"))
            + _as_list(props.get("notes"))
            + _as_list(props.get("Notes"))
        )
        if screening_notes:
            payload["screeningNotes"] = screening_notes

        return payload

    @staticmethod
    def _normalize_party_key(party_key: str) -> str:
        safe_key = str(party_key or "").strip()
        if not safe_key:
            return safe_key
        canonical_prefix = "AMLP_"
        upper_key = safe_key.upper()
        if upper_key.startswith("AMLP"):
            remainder = safe_key[4:].lstrip(" _-")
            return f"{canonical_prefix}{remainder}" if remainder else canonical_prefix
        return f"{canonical_prefix}{safe_key}"

    def build_on_demand_party_key(self, screening_type: str | None = None) -> str:
        unique_key = uuid4().hex.upper()
        mapped_suffix = self._resolve_party_key_suffix(screening_type)
        if mapped_suffix:
            return self._normalize_party_key(f"OD_{unique_key}_{mapped_suffix}")

        safe_screening_type = self._normalize_screening_type_key(screening_type)
        if safe_screening_type:
            # Keep on-demand party key suffix in 3-digit shape for non-mapped types.
            digest = hashlib.sha1(safe_screening_type.encode("utf-8")).hexdigest()
            derived_suffix = f"{int(digest[:8], 16) % 1000:03d}"
            return self._normalize_party_key(f"OD_{unique_key}_{derived_suffix}")
        return self._normalize_party_key(f"OD_{unique_key}")

    def _build_party_key(self, query: EntityExample) -> str:
        normalized = query.model_dump(mode="json")
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16].upper()
        return self._normalize_party_key(f"{self.source_system}_{digest}")

    def resolve_party_key(self, query: EntityExample) -> str:
        props = query.properties if isinstance(query.properties, dict) else {}
        explicit_party_key = _first_non_empty(
            _as_list(props.get("partyKey"))
            + _as_list(props.get("party_key"))
            + _as_list(props.get("PartyKey"))
            + _as_list(props.get("party key"))
        )
        return self._normalize_party_key(explicit_party_key or self._build_party_key(query))

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

    def _log_api_request(
        self,
        *,
        operation: str,
        endpoint: str,
        headers: dict[str, Any] | None,
        payload: Any,
        screening_type: str | None,
        attempt: int,
        party_key: str,
    ) -> None:
        if not self.log_raw_api_io:
            return
        logger.info(
            "actimize api request operation=%s endpoint=%s screening_type=%s party_key=%s attempt=%s headers=%s payload=%s",
            operation,
            endpoint,
            screening_type or "Sanction",
            party_key or "-",
            attempt,
            self._format_for_log(headers),
            self._format_for_log(payload),
        )

    def _log_api_response(
        self,
        *,
        operation: str,
        endpoint: str,
        headers: dict[str, Any] | None,
        payload: Any,
        response: requests.Response,
        screening_type: str | None,
        attempt: int,
        party_key: str,
    ) -> None:
        if not self.log_raw_api_io:
            return

        logger.info(
            "actimize api response operation=%s endpoint=%s screening_type=%s party_key=%s attempt=%s http_status=%s reason=%s headers=%s payload=%s raw_response=%s",
            operation,
            endpoint,
            screening_type or "Sanction",
            party_key or "-",
            attempt,
            int(response.status_code),
            response.reason,
            self._format_for_log(headers),
            self._format_for_log(payload),
            self._format_for_log(response.text),
        )

    def _log_api_exception(
        self,
        *,
        operation: str,
        endpoint: str,
        headers: dict[str, Any] | None,
        payload: Any,
        exception: Exception,
        screening_type: str | None,
        attempt: int,
        party_key: str,
    ) -> None:
        if not self.log_raw_api_io:
            return

        logger.warning(
            "actimize api exception operation=%s endpoint=%s screening_type=%s party_key=%s attempt=%s headers=%s payload=%s error=%s",
            operation,
            endpoint,
            screening_type or "Sanction",
            party_key or "-",
            attempt,
            self._format_for_log(headers),
            self._format_for_log(payload),
            self._truncate_for_log(str(exception)),
        )

    def _format_for_log(self, value: Any) -> str:
        sanitized = self._sanitize_for_log(value)
        if isinstance(sanitized, str):
            return self._truncate_for_log(sanitized)
        try:
            rendered = json.dumps(sanitized, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        except TypeError:
            rendered = str(sanitized)
        return self._truncate_for_log(rendered)

    def _truncate_for_log(self, raw_text: str) -> str:
        safe_raw = str(raw_text or "").strip()
        if len(safe_raw) > self.raw_api_log_max_chars:
            return f"{safe_raw[:self.raw_api_log_max_chars]}...(truncated)"
        return safe_raw

    def _sanitize_for_log(self, value: Any, parent_key: str = "") -> Any:
        key_name = str(parent_key or "").strip().lower()
        if key_name in _SENSITIVE_LOG_KEYS:
            return _REDACTED
        if isinstance(value, dict):
            return {str(k): self._sanitize_for_log(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_for_log(item, parent_key) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_for_log(item, parent_key) for item in value]
        if isinstance(value, bytes):
            return self._truncate_for_log(value.decode("utf-8", errors="replace"))
        if isinstance(value, str):
            stripped = value.strip()
            if key_name in _SENSITIVE_LOG_KEYS:
                return _REDACTED
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                except Exception:  # noqa: BLE001
                    parsed = None
                if parsed is not None:
                    return self._sanitize_for_log(parsed, parent_key)
            if "=" in stripped and "&" in stripped:
                try:
                    parsed_form = dict(parse_qsl(stripped, keep_blank_values=True))
                except Exception:  # noqa: BLE001
                    parsed_form = None
                if parsed_form is not None:
                    return self._sanitize_for_log(parsed_form, parent_key)
            return stripped
        return value

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

        if message_value not in {"PM", "NM"}:
            raise ExternalApiCallError(
                provider=self.provider,
                operation="entity-screenings",
                endpoint=f"{self.base_url}/entity-screenings",
                message=(
                    f"Screening API returned unsupported result: status={status_value or 'UNKNOWN'}, "
                    f"message={message_value or 'UNKNOWN'}"
                ),
            )

        normalized_results: list[dict[str, Any]] = []
        if message_value == "PM":
            props = query.properties if isinstance(query.properties, dict) else {}
            explicit_party_key = _first_non_empty(_as_list(props.get("partyKey")) + _as_list(props.get("party_key")))
            party_key = self._normalize_party_key(
                str(body.get("partyKey") or explicit_party_key or self._build_party_key(query))
            )
            display_name = _extract_name(query)
            normalized_results.append(
                {
                    "id": party_key,
                    "caption": f"{display_name} (Potential Match)",
                    "schema": str(query.schema),
                    "match": True,
                    "properties": {
                        "name": [display_name],
                        "engineMessage": [message_value],
                        "partyKey": [party_key],
                    },
                }
            )

        return {
            "results": normalized_results,
            "total": {"value": len(normalized_results), "relation": "eq"},
            "query": query.model_dump(mode="json"),
            "status": 200,
            "engine_message": message_value,
        }
