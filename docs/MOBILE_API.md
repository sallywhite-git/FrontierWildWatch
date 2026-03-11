# Frontier Mobile API Documentation

This document describes the reverse-engineered mobile API flow used by the Frontier Airlines Android app, which has been integrated into `FrontierWildWatch` to bypass PerimeterX blocks.

## Overview

The mobile API (`mtier.flyfrontier.com`) uses a custom request signing mechanism and a multi-step handshake to establish trust.

### Handshake Sequence

1.  **`generatenonce`**: Registers the device`s `signingKeyId` (SHA-256 hash of the public key) and `deviceId`. Returns a challenge.
2.  **`RetrieveAnonymousToken`**: A **signed** request that retrieves the session`s `authtoken` (JWT).
3.  **`GetPublicKey`**: A synchronization call to ensure the backend has correctly linked the session to the public key.
4.  **`FlightAvailabilitySimpleSearch`**: The main search endpoint, which must be **signed** with the private key.

## Request Signing Logic

Each sensitive request requires several custom headers:

*   **`x-signing-key-id`**: Base64-encoded SHA-256 hash of the public key (DER format).
*   **`x-request-data`**: Base64-encoded SHA-256 hash of a JSON metadata blob.
*   **`x-signature`**: ECDSA (SHA-256) signature of the metadata hash.
*   **`x-timestamp`**: Current epoch time in milliseconds.

### Metadata Blob Structure
```json
{
  "endpoint": "FlightAvailabilitySimpleSearch",
  "method": "POST",
  "timestamp": "1769931141428",
  "body_hash": "Base64(SHA256(request_body))"
}
```

## PerimeterX (PX) Integration

The API still requires valid PerimeterX mobile SDK headers. These are currently provided in `config.json`:
*   `x-px-uuid`
*   `x-px-authorization`
*   `x-px-device-fp`
*   `x-px-hello`

If requests begin failing with `403` or `406` errors, these headers may need to be refreshed by capturing a fresh session from the patched APK in an emulator.

## Configuration

In `config.json`, the following flags enable this behavior:
*   `"use_mobile_signing": true`
*   `"method": "POST"`
*   `"base_url": "https://mtier.flyfrontier.com/flightavailabilityssv/FlightAvailabilitySimpleSearch"`
