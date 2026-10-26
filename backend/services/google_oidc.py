"""Google OIDC Authorization Code flow with PKCE and strict ID-token validation."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

from jose import JWTError, jwt


class OIDCVerificationError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    google_subject: str
    verified_email: str
    display_name: str | None


class GoogleOIDCClient:
    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
    ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str, flow_store, http) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._flow_store = flow_store
        self._http = http

    async def authorization_url(self) -> str:
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        await self._flow_store.store_oidc_flow(
            state, nonce, verifier, ttl=timedelta(minutes=5),
        )
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        return self.AUTHORIZATION_ENDPOINT + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    async def verify_callback(self, *, state: str, code: str) -> GoogleIdentity:
        try:
            flow = await self._flow_store.consume_oidc_flow(state)
            response = await self._http.post(self.TOKEN_ENDPOINT, data={
                "client_id": self.client_id,
                "client_secret": self._client_secret,
                "code": code,
                "code_verifier": flow.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            })
            response.raise_for_status()
            id_token = response.json()["id_token"]
            jwks_response = await self._http.get(self.JWKS_ENDPOINT)
            jwks_response.raise_for_status()
            header = jwt.get_unverified_header(id_token)
            key = next(
                item for item in jwks_response.json()["keys"]
                if item.get("kid") == header.get("kid") and item.get("alg", "RS256") == "RS256"
            )
            claims = jwt.decode(
                id_token, key, algorithms=["RS256"], audience=self.client_id,
                options={"verify_at_hash": False, "require_exp": True},
            )
            if claims.get("iss") not in self.ISSUERS:
                raise OIDCVerificationError("invalid issuer")
            return self.validate_claims(claims, expected_nonce=flow.nonce)
        except OIDCVerificationError:
            raise
        except (JWTError, KeyError, StopIteration, ValueError, TypeError) as error:
            raise OIDCVerificationError("Google identity verification failed") from error
        except Exception as error:
            raise OIDCVerificationError("Google OIDC exchange failed") from error

    def validate_claims(self, claims: dict, *, expected_nonce: str | None = None) -> GoogleIdentity:
        subject = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().casefold()
        if "exp" not in claims or not subject or "@" not in email or claims.get("email_verified") is not True:
            raise OIDCVerificationError("verified Google email required")
        if expected_nonce is not None and not secrets.compare_digest(
            str(claims.get("nonce") or ""), expected_nonce,
        ):
            raise OIDCVerificationError("invalid nonce")
        name = str(claims.get("name") or "").strip() or None
        return GoogleIdentity(subject, email, name)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
