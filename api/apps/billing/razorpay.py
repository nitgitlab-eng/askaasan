"""Minimal Razorpay REST client (Orders, Payments, Subscriptions) and signature checks."""

import hashlib
import hmac
from dataclasses import dataclass

import httpx

API = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class Keys:
    key_id: str
    secret: str

    @property
    def mode(self) -> str:
        return "live" if self.key_id.startswith("rzp_live_") else "test"


def _call(keys: Keys, method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict:
    try:
        r = httpx.request(
            method, f"{API}{path}", auth=(keys.key_id, keys.secret), json=json, params=params, timeout=20
        )
    except httpx.HTTPError as e:
        raise RazorpayError("network", str(e)[:200]) from e
    if r.status_code == 401:
        raise RazorpayError("bad_keys", "Razorpay rejected the key id / secret")
    if r.status_code >= 400:
        try:
            desc = r.json().get("error", {}).get("description", "")
        except ValueError:
            desc = r.text[:200]
        raise RazorpayError("api_error", f"{r.status_code}: {desc}"[:240])
    return r.json()


def create_order(keys: Keys, amount_paise: int, currency: str, receipt: str, notes: dict) -> dict:
    return _call(
        keys,
        "POST",
        "/orders",
        json={"amount": amount_paise, "currency": currency, "receipt": receipt, "notes": notes},
    )


def fetch_payment(keys: Keys, payment_id: str) -> dict:
    return _call(keys, "GET", f"/payments/{payment_id}")


def fetch_order_payments(keys: Keys, order_id: str) -> list[dict]:
    """Every payment attempt Razorpay holds for one order (reconciliation asks this, never the browser)."""
    items = _call(keys, "GET", f"/orders/{order_id}/payments").get("items")
    return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []


def capture_payment(keys: Keys, payment_id: str, amount_paise: int, currency: str) -> dict:
    return _call(
        keys, "POST", f"/payments/{payment_id}/capture", json={"amount": amount_paise, "currency": currency}
    )


def create_refund(keys: Keys, payment_id: str, amount_paise: int, notes: dict) -> dict:
    return _call(
        keys,
        "POST",
        f"/payments/{payment_id}/refund",
        json={"amount": amount_paise, "notes": notes, "speed": "normal"},
    )


def create_subscription(keys: Keys, plan_id: str, total_count: int, notes: dict) -> dict:
    return _call(
        keys,
        "POST",
        "/subscriptions",
        json={
            "plan_id": plan_id,
            "total_count": total_count,
            "quantity": 1,
            "customer_notify": 1,
            "notes": notes,
        },
    )


def fetch_subscription(keys: Keys, subscription_id: str) -> dict:
    return _call(keys, "GET", f"/subscriptions/{subscription_id}")


def cancel_subscription(keys: Keys, subscription_id: str, at_cycle_end: bool) -> dict:
    return _call(
        keys,
        "POST",
        f"/subscriptions/{subscription_id}/cancel",
        json={"cancel_at_cycle_end": 1 if at_cycle_end else 0},
    )


def resume_subscription(keys: Keys, subscription_id: str) -> dict:
    return _call(keys, "POST", f"/subscriptions/{subscription_id}/resume", json={"resume_at": "now"})


def ping(keys: Keys) -> None:
    _call(keys, "GET", "/orders", params={"count": 1})


def _sig(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def valid_payment_signature(secret: str, order_id: str, payment_id: str, signature: str) -> bool:
    return bool(secret and signature) and hmac.compare_digest(
        _sig(secret, f"{order_id}|{payment_id}".encode()), signature
    )


def valid_webhook_signature(secret: str, body: bytes, signature: str) -> bool:
    return bool(secret and signature) and hmac.compare_digest(_sig(secret, body), signature)


def valid_subscription_signature(secret: str, payment_id: str, subscription_id: str, signature: str) -> bool:
    """Checkout with subscription_id signs "<payment_id>|<subscription_id>"."""
    return bool(secret and signature and payment_id and subscription_id) and hmac.compare_digest(
        _sig(secret, f"{payment_id}|{subscription_id}".encode()), signature
    )
