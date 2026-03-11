# FrontierWildWatch

FrontierWildWatch is a high-reliability Frontier Airlines flight search engine that uses a signed mobile API client to bypass anti-bot protections and fetch real-time availability and pricing.

It is specifically designed to work with the **Frontier GoWild! Pass**, highlighting availability and low fares that are often hidden or difficult to find via traditional scrapers.

## Features

- **Signed Mobile API**: Uses an ECDSA-signed handshake to communicate with Frontier's mobile backend (`mtier.flyfrontier.com`).
- **Real-Time Fares**: Fetches actual pricing, prioritizing GoWild fares and falling back to standard availability.
- **Automated Scheduling**: Designed to run via cron or as a standalone service.
- **Telegram Notifications**: Real-time alerts when new availability or price drops are detected.

## Quick Start

1. **Setup Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure**:
   Copy `config.example.json` to `config.json` and update your desired routes:
   ```bash
   cp config.example.json config.json
   ```

3. **Run a Dry Run**:
   Before making actual API calls, verify your configuration and query plan:
   ```bash
   python3 scanner.py --config config.json --dry-run
   ```

## Usage

### The Scanner Runner

The main entry point is `scanner.py`. It reads your `config.json` and executes searches based on your `origins` and `destinations`.

```bash
python3 scanner.py --config config.json
```

### Command Line Arguments

- `--config`: Path to your configuration file (default: `config.json`).
- `--dry-run`: **Highly Recommended for testing.** This prints the planned queries (routes and dates) to the console *without* actually making any API requests. It's the safest way to verify your schedule and route logic.
- `--probe <ORIGIN> <DEST> <DATE>`: Executes a single search for a specific route and date, saving the full diagnostic output to `probe.json`.
  ```bash
  python3 scanner.py --probe SNA SFO 2026-02-27
  ```
- `--dump-json`: Prints the raw results of the scan to the console in JSON format.

## Configuration Details

The `config.json` file controls the scanner's behavior:

- `origins` / `destinations`: Lists of airport IATA codes.
- `search_days`: How many days into the future to search.
- `api.use_mobile_signing`: Must be `true` for the signed API path.
- `telegram`: Configuration for bot alerts.

## Verification

To ensure your environment is set up correctly, run the targeted API test:
```bash
# This verifies the signed handshake and search flow
python3 scanner.py --config config.json --probe LAX SFO 2026-02-28
```

---
*Maintained for Frontier Airlines GoWild! enthusiasts.*
