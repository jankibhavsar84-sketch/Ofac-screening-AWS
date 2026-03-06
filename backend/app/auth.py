from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Any, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from .config import settings

bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None

ROLE_PERMISSION_MAP: dict[str, set[str]] = {
    "viewer": {"screening.read", "screening.single.mock"},
    "analyst": {"screening.read", "screening.write"},
    "compliance": {"screening.read", "screening.write", "screening.daily"},
    "admin": {
        "screening.read",
        "screening.write",
        "screening.daily",
        "screening.admin",
        "screening.useradmin",
        "screening.single.mock",
    },
}

ROLE_ALIASES: dict[str, str] = {
    "admin": "admin",
    "screening admin": "admin",
    "screening.admin": "admin",
    "screening-admin": "admin",
    "compliance": "compliance",
    "compliance officer": "compliance",
    "compliance_officer": "compliance",
    "compliance-officer": "compliance",
    "analyst": "analyst",
    "viewer": "viewer",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass
class AuthPrincipal:
    user_id: str
    user_name: str
    email: str
    scopes: set[str]
    roles: set[str]
    claims: dict[str, Any]


_audit_principal_ctx: ContextVar[AuthPrincipal | None] = ContextVar("audit_principal", default=None)


def get_audit_principal() -> AuthPrincipal | None:
    return _audit_principal_ctx.get()


def clear_audit_principal() -> None:
    _audit_principal_ctx.set(None)


def _split_scope(value: Any) -> set[str]:
    if isinstance(value, str):
        return {s.strip() for s in value.split(" ") if s.strip()}
    if isinstance(value, list):
        return {str(s).strip() for s in value if str(s).strip()}
    return set()


def _to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else []
    return []


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate
    return ""


def _is_technical_identifier(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True
    if raw.isdigit():
        return True
    if _UUID_RE.match(raw):
        return True
    return False


def _normalize_role(role: str) -> str:
    lowered = role.strip().lower()
    if not lowered:
        return ""
    collapsed = re.sub(r"[\s_-]+", " ", lowered).strip()
    return ROLE_ALIASES.get(collapsed, lowered)


def _extract_roles(payload: dict[str, Any]) -> set[str]:
    roles_raw: set[str] = set()

    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        roles_raw.update(_to_string_list(realm_access.get("roles")))

    resource_access = payload.get("resource_access")
    if isinstance(resource_access, dict):
        for _, client_access in resource_access.items():
            if not isinstance(client_access, dict):
                continue
            roles_raw.update(_to_string_list(client_access.get("roles")))

    roles_raw.update(_to_string_list(payload.get("roles")))
    roles_raw.update(_to_string_list(payload.get("groups")))
    roles_raw.update(_to_string_list(payload.get("cognito:groups")))
    roles_raw.update(_to_string_list(payload.get("custom:roles")))

    roles: set[str] = set()
    for role in roles_raw:
        normalized = _normalize_role(role)
        if normalized:
            roles.add(normalized)
    return roles


def _effective_permissions(scopes: set[str], roles: set[str]) -> set[str]:
    permissions = {s.strip().lower() for s in scopes if s.strip()}

    for role in roles:
        role_lower = role.strip().lower()
        if not role_lower:
            continue
        permissions.update(ROLE_PERMISSION_MAP.get(role_lower, set()))
        if role_lower.startswith("screening."):
            permissions.add(role_lower)

    if "screening.admin" in permissions:
        permissions.update(ROLE_PERMISSION_MAP["admin"])
    elif "screening.write" in permissions:
        permissions.update({"screening.read"})

    return permissions


def principal_permissions(principal: AuthPrincipal) -> set[str]:
    return _effective_permissions(principal.scopes, principal.roles)


def principal_has_permission(principal: AuthPrincipal, *required: str) -> bool:
    normalized = {r.strip().lower() for r in required if r.strip()}
    if not normalized:
        return True
    permissions = principal_permissions(principal)
    return bool(permissions.intersection(normalized))


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.auth_jwks_url)
    return _jwks_client


def _decode_token(raw_token: str) -> dict[str, Any]:
    jwks_client = _get_jwks_client()
    signing_key = jwks_client.get_signing_key_from_jwt(raw_token)

    algorithms = [a.strip() for a in settings.auth_algorithms.split(",") if a.strip()]
    if not algorithms:
        algorithms = ["RS256"]

    kwargs: dict[str, Any] = {
        "algorithms": algorithms,
        "issuer": settings.auth_issuer,
        # Validate audience-like claims manually so Cognito access tokens
        # without "aud" can still be checked against app client id.
        "options": {"verify_aud": False},
    }

    payload = jwt.decode(
        raw_token,
        signing_key.key,
        **kwargs,
    )
    if not isinstance(payload, dict):
        raise InvalidTokenError("JWT payload must be an object")

    expected_audience = settings.auth_audience.strip()
    if expected_audience:
        audience_claim = payload.get("aud")
        client_id_claim = payload.get("client_id")
        authorized_party_claim = payload.get("azp")

        audience_values: set[str] = set()
        if isinstance(audience_claim, str) and audience_claim.strip():
            audience_values.add(audience_claim.strip())
        elif isinstance(audience_claim, list):
            audience_values.update(str(v).strip() for v in audience_claim if str(v).strip())

        for value in (client_id_claim, authorized_party_claim):
            if isinstance(value, str) and value.strip():
                audience_values.add(value.strip())

        if expected_audience not in audience_values:
            raise InvalidTokenError(
                'Token audience mismatch: expected AUTH_AUDIENCE in "aud", "client_id", or "azp" claim'
            )

    return payload


def _claims_to_principal(payload: dict[str, Any]) -> AuthPrincipal:
    user_id = _first_non_empty(
        payload.get("sub"),
        payload.get("preferred_username"),
        payload.get("cognito:username"),
        payload.get("username"),
        payload.get("email"),
    )
    email = _first_non_empty(payload.get("email"))

    user_name_candidate = _first_non_empty(
        payload.get("name"),
        payload.get("preferred_username"),
        payload.get("cognito:username"),
        payload.get("username"),
        email,
        user_id,
    )
    if _is_technical_identifier(user_name_candidate):
        user_name = _first_non_empty(email, payload.get("cognito:username"), payload.get("username"), user_name_candidate)
    else:
        user_name = user_name_candidate

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not include a user identifier",
        )

    scopes = _split_scope(payload.get("scope")) | _split_scope(payload.get("scp"))
    roles = _extract_roles(payload)

    return AuthPrincipal(
        user_id=user_id,
        user_name=user_name,
        email=email,
        scopes=scopes,
        roles=roles,
        claims=payload,
    )


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthPrincipal:
    clear_audit_principal()

    if not settings.auth_enabled:
        principal = AuthPrincipal(
            user_id="local-dev-user",
            user_name="Local Dev User",
            email="",
            scopes={
                "screening.read",
                "screening.write",
                "screening.daily",
                "screening.admin",
                "screening.useradmin",
                "screening.single.mock",
            },
            roles={"admin"},
            claims={},
        )
        _audit_principal_ctx.set(principal)
        return principal

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    if not settings.auth_issuer or not settings.auth_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth is enabled but AUTH_ISSUER/AUTH_JWKS_URL are not configured",
        )

    try:
        payload = _decode_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid access token: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
        ) from exc

    principal = _claims_to_principal(payload)
    _audit_principal_ctx.set(principal)
    return principal


def require_any_scope(*required_scopes: str) -> Callable[[AuthPrincipal], AuthPrincipal]:
    normalized = {s.strip().lower() for s in required_scopes if s.strip()}

    def dependency(principal: AuthPrincipal = Depends(get_current_principal)) -> AuthPrincipal:
        if not normalized:
            return principal

        if principal_has_permission(principal, *normalized):
            return principal

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient scope. Required one of: {', '.join(sorted(normalized))}",
        )

    return dependency
