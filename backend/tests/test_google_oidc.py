from __future__ import annotations

import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from backend.services.google_oidc import GoogleOIDCClient, OIDCVerificationError


class FlowStore:
    def __init__(self):
        self.flow = None

    async def store_oidc_flow(self, state, nonce, code_verifier, *, ttl):
        self.flow = type("Flow", (), {"state": state, "nonce": nonce, "code_verifier": code_verifier})()

    async def consume_oidc_flow(self, state):
        if self.flow is None or self.flow.state != state:
            raise OIDCVerificationError("invalid state")
        flow, self.flow = self.flow, None
        return flow


class FakeHTTP:
    def __init__(self, token, jwk):
        self.token, self.jwk = token, jwk
        self.post_data = None

    async def post(self, url, data):
        self.post_data = data
        token = self.token
        return type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"id_token": token}})()

    async def get(self, url):
        jwk = self.jwk
        return type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"keys": [jwk]}})()


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_authorization_url_uses_state_nonce_and_s256_pkce():
    async def case():
        store = FlowStore()
        client = GoogleOIDCClient(
            client_id="client-id", client_secret="secret", redirect_uri="https://app.example/api/auth/google/callback",
            flow_store=store, http=object(),
        )
        url = await client.authorization_url()
        query = parse_qs(urlsplit(url).query)
        assert query["state"] == [store.flow.state]
        assert query["nonce"] == [store.flow.nonce]
        assert query["code_challenge_method"] == ["S256"]
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(store.flow.code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert query["code_challenge"] == [expected]
        assert "redirect" not in query and "return_url" not in query

    asyncio.run(case())


def test_callback_verifies_signature_issuer_audience_expiry_nonce_and_pkce():
    global token, self_jwk
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    self_jwk = {"kty": "RSA", "kid": "test", "use": "sig", "alg": "RS256", "n": _b64(numbers.n), "e": _b64(numbers.e)}

    async def case():
        global token
        store = FlowStore()
        client = GoogleOIDCClient(
            client_id="client-id", client_secret="secret", redirect_uri="https://app.example/api/auth/google/callback",
            flow_store=store, http=None,
        )
        await client.authorization_url()
        token = jwt.encode(
            {"iss": "https://accounts.google.com", "aud": "client-id", "sub": "google-sub",
             "email": "Person@Example.com", "email_verified": True, "nonce": store.flow.nonce,
             "exp": 4102444800}, key, algorithm="RS256", headers={"kid": "test"},
        )
        fake = FakeHTTP(token, self_jwk)
        client._http = fake
        identity = await client.verify_callback(state=store.flow.state, code="auth-code")
        assert identity.google_subject == "google-sub"
        assert identity.verified_email == "person@example.com"
        assert fake.post_data["code_verifier"]

    asyncio.run(case())


def test_unverified_email_or_wrong_nonce_is_rejected():
    async def case():
        store = FlowStore()
        client = GoogleOIDCClient(
            client_id="client-id", client_secret="secret", redirect_uri="https://app.example/callback",
            flow_store=store, http=object(),
        )
        await client.authorization_url()
        with pytest.raises(OIDCVerificationError):
            client.validate_claims({"sub": "x", "email": "x@example.com", "email_verified": False,
                                    "nonce": store.flow.nonce, "exp": 4102444800})
        with pytest.raises(OIDCVerificationError):
            client.validate_claims({"sub": "x", "email": "x@example.com", "email_verified": True,
                                    "nonce": "wrong", "exp": 4102444800}, expected_nonce=store.flow.nonce)
        with pytest.raises(OIDCVerificationError):
            client.validate_claims({"sub": "x", "email": "x@example.com", "email_verified": True,
                                    "nonce": store.flow.nonce}, expected_nonce=store.flow.nonce)

    asyncio.run(case())


def test_expired_id_token_is_rejected_during_callback():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "expired", "use": "sig", "alg": "RS256",
           "n": _b64(numbers.n), "e": _b64(numbers.e)}

    async def case():
        store = FlowStore()
        client = GoogleOIDCClient(
            client_id="client-id", client_secret="secret",
            redirect_uri="https://app.example/api/auth/google/callback",
            flow_store=store, http=None,
        )
        await client.authorization_url()
        expired = jwt.encode(
            {"iss": "https://accounts.google.com", "aud": "client-id", "sub": "google-sub",
             "email": "person@example.com", "email_verified": True, "nonce": store.flow.nonce,
             "exp": 1},
            key, algorithm="RS256", headers={"kid": "expired"},
        )
        client._http = FakeHTTP(expired, jwk)
        with pytest.raises(OIDCVerificationError):
            await client.verify_callback(state=store.flow.state, code="auth-code")

    asyncio.run(case())
