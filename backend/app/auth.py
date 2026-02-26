from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from .config import settings

bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


@dataclass
class AuthPrincipal:
    user_id: str
    user_name: str
    email: str
    scopes: set[str]
    roles: set[str]
    claims: dict[str, Any]


def _split_scope(value: Any) -> set[str]:
    if isinstance(value, str):
        return {s.strip() for s in value.split(" ") if s.strip()}
    if isinstance(value, list):
        return {str(s).strip() for s in value if str(s).strip()}
    return set()


def _extract_roles(payload: dict[str, Any]) -> set[str]:
    roles: set[str] = set()

    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        realm_roles = realm_access.get("roles")
        if isinstance(realm_roles, list):
            roles.update(str(r).strip() for r in realm_roles if str(r).strip())

    resource_access = payload.get("resource_access")
    if isinstance(resource_access, dict):
        for _, client_access in resource_access.items():
            if not isinstance(client_access, dict):
                continue
            client_roles = client_access.get("roles")
            if isinstance(client_roles, list):
                roles.update(str(r).strip() for r in client_roles if str(r).strip())

    return roles


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

    verify_aud = bool(settings.auth_audience.strip())
    kwargs: dict[str, Any] = {
        "algorithms": algorithms,
        "issuer": settings.auth_issuer,
        "options": {"verify_aud": verify_aud},
    }
    if verify_aud:
        kwargs["audience"] = settings.auth_audience

    payload = jwt.decode(
        raw_token,
        signing_key.key,
        **kwargs,
    )
    if not isinstance(payload, dict):
        raise InvalidTokenError("JWT payload must be an object")
    return payload


def _claims_to_principal(payload: dict[str, Any]) -> AuthPrincipal:
    user_id = str(payload.get("sub") or payload.get("preferred_username") or payload.get("email") or "").strip()
    user_name = str(payload.get("name") or payload.get("preferred_username") or payload.get("email") or user_id).strip()
    email = str(payload.get("email") or "").strip()

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
    if not settings.auth_enabled:
        return AuthPrincipal(
            user_id="local-dev-user",
            user_name="Local Dev User",
            email="",
            scopes={"screening.read", "screening.write", "screening.admin"},
            roles={"admin"},
            claims={},
        )

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

    return _claims_to_principal(payload)


def require_any_scope(*required_scopes: str) -> Callable[[AuthPrincipal], AuthPrincipal]:
    normalized = {s.strip().lower() for s in required_scopes if s.strip()}

    def dependency(principal: AuthPrincipal = Depends(get_current_principal)) -> AuthPrincipal:
        if not normalized:
            return principal

        principal_scopes = {s.lower() for s in principal.scopes}
        principal_roles = {r.lower() for r in principal.roles}
        if "admin" in principal_roles or "screening.admin" in principal_scopes or "screening.admin" in principal_roles:
            return principal

        if principal_scopes.intersection(normalized):
            return principal
        if principal_roles.intersection(normalized):
            return principal

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient scope. Required one of: {', '.join(sorted(normalized))}",
        )

    return dependency
