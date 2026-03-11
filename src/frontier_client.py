import base64
import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from src.engine.models import Flight, QueryDiagnostics, QueryOutcome, QuerySpec, QueryStatus


class FrontierBlockedError(Exception):
    def __init__(self, url: str, status_code: int, reason: str, response_headers: Dict[str, str], body_snippet: str):
        self.url = url
        self.status_code = status_code
        self.reason = reason
        self.response_headers = response_headers
        self.body_snippet = body_snippet
        super().__init__(f"Frontier blocked request: {status_code} {reason}")


@dataclass
class FrontierClientConfig:
    base_url: str
    method: str
    params_template: Dict[str, str]
    headers: Dict[str, str]
    timeout_seconds: int
    retries: int
    backoff_seconds: float
    min_delay_seconds: float
    max_delay_seconds: float
    user_agents: List[str]
    date_format: str
    flights_path: Optional[List[str]]
    field_map: Dict[str, List[str]]
    mock_response_path: Optional[str]
    json_template: Optional[Dict[str, Any]] = None
    use_mobile_signing: bool = False


class FrontierClient:
    def __init__(self, cfg: FrontierClientConfig) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.auth_token = None
        self.frontier_token = cfg.headers.get("frontiertoken", "")
        
        if cfg.use_mobile_signing:
            # Initialize EC keys for signing
            self.private_key = ec.generate_private_key(ec.SECP256R1())
            self.public_key = self.private_key.public_key()
            pub_bytes = self.public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            self.key_id = base64.b64encode(hashlib.sha256(pub_bytes).digest()).decode()

    def _build_params(self, origin: str, destination: str, date_str: str) -> Dict[str, str]:
        params = {}
        for key, template in self.cfg.params_template.items():
            if isinstance(template, str):
                params[key] = (
                    template.replace("{origin}", origin)
                    .replace("{destination}", destination)
                    .replace("{date}", date_str)
                )
            else:
                params[key] = template
        return params

    def _build_json(self, origin: str, destination: str, date_str: str) -> Optional[Dict[str, Any]]:
        if not self.cfg.json_template:
            return None

        def _replace(obj: Any) -> Any:
            if isinstance(obj, str):
                return obj.replace("{origin}", origin).replace("{destination}", destination).replace("{date}", date_str)
            if isinstance(obj, dict):
                return {k: _replace(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_replace(i) for i in obj]
            return obj

        return _replace(self.cfg.json_template)

    def _pick_headers(self) -> Dict[str, str]:
        headers = {
            "Host": "mtier.flyfrontier.com",
            "device-id": self.cfg.headers.get("device-id", ""),
            "ocp-apim-subscription-key": self.cfg.headers.get("ocp-apim-subscription-key", ""),
            "user-agent": self.cfg.headers.get("user-agent", self.user_agent if hasattr(self, 'user_agent') else "NCPAndroid/3.5.4"),
            "frontiertoken": self.frontier_token,
        }
        
        # Add PerimeterX headers
        px_defaults = {
            "x-px-os-version": "16",
            "x-px-uuid": "1ee1f538-ff40-11f0-a77b-45348a5e92ff",
            "x-px-authorization": "1",
            "x-px-device-fp": "d2b77ff2a2b4d96d",
            "x-px-device-model": "sdk_gphone64_arm64",
            "x-px-os": "Android",
            "x-px-hello": "AlZWAlUGAAseVVUHAx4CAlUDHlIEBFEeBwYABwtSBlYKAVVV",
            "x-px-mobile-sdk-version": "3.4.5"
        }
        headers.update(px_defaults)

        if self.auth_token:
            headers["authtoken"] = self.auth_token
            
        return headers

    def _sign_request(self, endpoint: str, method: str, body_dict: Optional[Dict[str, Any]]) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        
        if body_dict:
            # Use compact serialization to match server expectation
            body_json = json.dumps(body_dict, separators=(',', ':'))
            body_hash = base64.b64encode(hashlib.sha256(body_json.encode()).digest()).decode()
        else:
            # For empty body, use empty string hash
            body_hash = base64.b64encode(hashlib.sha256(b"").digest()).decode()
        
        metadata = {
            "endpoint": endpoint,
            "method": method,
            "timestamp": timestamp,
            "body_hash": body_hash
        }
        # Standard metadata compact serialization
        metadata_json = json.dumps(metadata, separators=(',', ':'))
        metadata_hash_bytes = hashlib.sha256(metadata_json.encode()).digest()
        
        signature_bytes = self.private_key.sign(
            metadata_hash_bytes,
            ec.ECDSA(hashes.SHA256())
        )
        
        return {
            "x-signing-key-id": self.key_id,
            "x-signature": base64.b64encode(signature_bytes).decode(),
            "x-request-data": base64.b64encode(metadata_hash_bytes).decode(),
            "x-timestamp": timestamp,
            "x-device-id": self.cfg.headers.get("device-id", ""),
            "x-platform": "Android",
            "content-type": "application/json; charset=utf-8"
        }

    def _rate_limit_pause(self) -> None:
        if self.cfg.max_delay_seconds <= 0:
            return
        delay = random.uniform(self.cfg.min_delay_seconds, self.cfg.max_delay_seconds)
        time.sleep(delay)

    def run_mobile_handshake(self) -> bool:
        if not self.cfg.use_mobile_signing:
            return True
            
        try:
            # 1. Nonce
            domain = self.cfg.base_url.split("//")[-1].split("/")[0]
            base_domain_url = f"https://{domain}"
            
            url_nonce = f"{base_domain_url}/registrationssv/generatenonce"
            nonce_body = {
                "deviceId": self.cfg.headers.get("device-id"),
                "signingKeyId": self.key_id,
                "platform": "Android"
            }
            resp = self.session.post(url_nonce, headers=self._pick_headers(), json=nonce_body, timeout=self.cfg.timeout_seconds)
            if resp.status_code != 200:
                print(f"Handshake error: Nonce failed {resp.status_code}: {resp.text}")
                return False
            
            # 2. Token (Signed)
            endpoint = "RetrieveAnonymousToken"
            url_token = f"{base_domain_url}/registrationssv/{endpoint}"
            signing_headers = self._sign_request(endpoint, "POST", None)
            
            # Retrieve token with SIGNED request (empty body)
            resp = self.session.post(url_token, headers=self._pick_headers() | signing_headers, data="", timeout=self.cfg.timeout_seconds)
            if resp.status_code == 200:
                self.auth_token = resp.json().get("data", {}).get("authToken")
            else:
                print(f"Handshake error: Token failed {resp.status_code}: {resp.text}")
                return False

            # 3. Sync Public Key
            url_pub = f"{base_domain_url}/registrationssv/GetPublicKey"
            self.session.get(url_pub, headers=self._pick_headers(), timeout=self.cfg.timeout_seconds)
            
            return True
        except Exception as e:
            print(f"Handshake exception: {e}")
            return False

    def _request(self, origin: str, destination: str, date_str: str) -> Tuple[str, int, Dict[str, str], str, str]:
        if self.cfg.mock_response_path:
            with open(self.cfg.mock_response_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return ("application/json", 200, {}, json.dumps(payload), self.cfg.base_url)

        # Refresh token if using mobile signing and we don't have one
        if self.cfg.use_mobile_signing and not self.auth_token:
            self.run_mobile_handshake()

        params = self._build_params(origin, destination, date_str)
        json_payload = self._build_json(origin, destination, date_str)
        headers = self._pick_headers()
        method = self.cfg.method.upper()
        
        if self.cfg.use_mobile_signing:
            endpoint = self.cfg.base_url.split('/')[-1]
            signing_headers = self._sign_request(endpoint, method, json_payload)
            headers.update(signing_headers)
            if self.auth_token:
                headers["authtoken"] = self.auth_token

        # Force lowercase keys for absolute consistency with working script
        headers = {k.lower(): v for k, v in headers.items()}

        # Use compact serialization for the body if it's a signed request
        data = None
        if json_payload:
            data = json.dumps(json_payload, separators=(',', ':'))

        response = self.session.request(
            method,
            self.cfg.base_url,
            params=params if method == "GET" else None,
            data=data if method != "GET" else None,
            headers=headers,
            timeout=self.cfg.timeout_seconds,
        )
        
        return (
            response.headers.get("Content-Type", ""),
            response.status_code,
            dict(response.headers),
            response.text,
            response.url,
        )

    def _fetch_with_retries(self, origin: str, destination: str, date_str: str) -> Tuple[str, int, Dict[str, str], str, str]:
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.retries):
            try:
                content_type, status_code, headers, body, url = self._request(origin, destination, date_str)
                if status_code == 200:
                    return (content_type, status_code, headers, body, url)
                
                if status_code in (403, 406):
                    # Check for PerimeterX challenge
                    if "px" in body.lower() or "challenge" in body.lower():
                        raise FrontierBlockedError(url, status_code, "Blocked by PerimeterX", headers, body[:500])
                if 400 <= status_code < 500 and status_code != 429:
                    # Don't retry client errors except rate limits
                    return (content_type, status_code, headers, body, url)
            except (requests.RequestException, FrontierBlockedError) as exc:
                last_exc = exc
                if attempt < self.cfg.retries - 1:
                    time.sleep(self.cfg.backoff_seconds * (2**attempt))
                    if isinstance(exc, requests.RequestException) and getattr(exc.response, 'status_code', 0) == 401:
                        self.auth_token = None
                else:
                    raise last_exc
        raise last_exc or Exception("Unknown fetch error")

    def search_outcome(self, spec: QuerySpec) -> QueryOutcome:
        self._rate_limit_pause()
        try:
            content_type, status_code, headers_dict, body_text, url = self._fetch_with_retries(
                spec.origin, spec.destination, spec.date
            )
        except FrontierBlockedError as exc:
            return QueryOutcome(
                status=QueryStatus.BLOCKED,
                flights=[],
                error=str(exc),
                diagnostics=QueryDiagnostics(
                    url=exc.url,
                    status_code=exc.status_code,
                    reason=exc.reason,
                    response_headers=exc.response_headers,
                    body_snippet=exc.body_snippet,
                ),
            )
        except requests.RequestException as exc:
            return QueryOutcome(
                status=QueryStatus.NETWORK_ERROR,
                flights=[],
                error=str(exc),
                diagnostics=QueryDiagnostics(reason=str(exc)),
            )
        except Exception as exc:
            return QueryOutcome(
                status=QueryStatus.UNKNOWN_ERROR,
                flights=[],
                error=str(exc),
                diagnostics=QueryDiagnostics(reason=str(exc)),
            )

        diagnostics = QueryDiagnostics(
            url=url or self.cfg.base_url,
            status_code=status_code,
            response_headers=headers_dict,
            body_snippet=(body_text or "")[:500],
            content_type=content_type or "",
        )

        payload: Any
        lower_content_type = (content_type or "").lower()
        if "application/json" in lower_content_type or "application/problem+json" in lower_content_type:
            try:
                payload = json.loads(body_text or "{}")
            except Exception as exc:
                return QueryOutcome(
                    status=QueryStatus.PARSE_ERROR,
                    flights=[],
                    error=f"Failed to parse JSON: {exc}",
                    diagnostics=diagnostics,
                )
        else:
            return QueryOutcome(
                status=QueryStatus.PARSE_ERROR,
                flights=[],
                error=f"Unexpected content type: {content_type}",
                diagnostics=diagnostics,
            )

        flights_raw = _extract_path(payload, self.cfg.flights_path, spec.origin, spec.destination)
        if flights_raw is None:
            return QueryOutcome(status=QueryStatus.OK, flights=[], diagnostics=diagnostics)

        if not isinstance(flights_raw, list):
            flights_raw = [flights_raw]

        flights = [self._normalize_flight(spec.origin, spec.destination, spec.date, raw) for raw in flights_raw]
        return QueryOutcome(status=QueryStatus.OK, flights=flights, diagnostics=diagnostics)

    def _get_best_price(self, raw: Any) -> Optional[float]:
        try:
            # New Mobile API structure: raw -> fares[0] -> gowildfareAvailabilityKey
            # Then index into fareBundleInfo
            fares = raw.get("fares", [])
            if not fares:
                return None
            
            fare_obj = fares[0]
            bundle_info = fare_obj.get("fareBundleInfo", {})
            
            # Priority 1: GoWild
            gw_key = fare_obj.get("gowildfareAvailabilityKey")
            if gw_key and gw_key in bundle_info:
                price = bundle_info[gw_key].get("economyBundlePrice")
                if price is not None:
                    return float(price)
                
            # Priority 2: Standard (fallback)
            std_key = fare_obj.get("standardfareAvailabilityKey")
            if std_key and std_key in bundle_info:
                price = bundle_info[std_key].get("economyBundlePrice")
                if price is not None:
                    return float(price)
            
            return None
        except Exception:
            return None

    def _normalize_flight(self, origin: str, destination: str, date_str: str, raw: Any) -> Flight:
        mapped = {}
        for field, path in self.cfg.field_map.items():
            if field == "price":
                mapped[field] = self._get_best_price(raw)
            else:
                mapped[field] = _extract_value(raw, path, origin, destination)
        
        return Flight(
            origin=origin,
            destination=destination,
            date=date_str,
            depart_time=mapped.get("depart_time"),
            arrive_time=mapped.get("arrive_time"),
            stops=mapped.get("stops"),
            price=mapped.get("price"),
            raw=raw,
        )


def _extract_path(data: Any, path: Optional[Iterable[str]], origin: str = "", destination: str = "") -> Any:
    if path is None:
        return data
    current = data
    for key in path:
        if current is None:
            return None
        if isinstance(key, str):
            key = key.replace("{origin}", origin).replace("{destination}", destination)
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            try:
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            except (ValueError, TypeError):
                return None
        else:
            return None
    return current


def _extract_value(data: Any, path: Optional[Iterable[str]], origin: str = "", destination: str = "") -> Any:
    if path is None:
        return None
    return _extract_path(data, path, origin, destination)
