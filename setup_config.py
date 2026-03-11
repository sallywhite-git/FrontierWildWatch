import json
import os
import secrets
import sys
import uuid

# Add the project root to the path so we can import src modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.frontier_client import FrontierClient, FrontierClientConfig

def generate_config():
    example_path = "config.example.json"
    target_path = "config.json"
    
    if not os.path.exists(example_path):
        print(f"Error: {example_path} not found.")
        sys.exit(1)
        
    with open(example_path, "r", encoding="utf-8") as f:
        cfg_dict = json.load(f)
        print("Using anonymous mobile SDK tokens from example config for out-of-the-box setup.")

    # Initialize a temporary client to test the handshake
    api_cfg = cfg_dict.get("api", {})
    config = FrontierClientConfig(
        base_url=api_cfg.get("base_url", "https://mtier.flyfrontier.com/flightavailabilityssv/FlightAvailabilitySimpleSearch"),
        method=api_cfg.get("method", "POST"),
        params_template=api_cfg.get("params_template", {}),
        headers=api_cfg.get("headers", {}),
        timeout_seconds=int(api_cfg.get("timeout_seconds", 20)),
        retries=int(api_cfg.get("retries", 3)),
        backoff_seconds=float(api_cfg.get("backoff_seconds", 2.0)),
        min_delay_seconds=float(api_cfg.get("min_delay_seconds", 1.0)),
        max_delay_seconds=float(api_cfg.get("max_delay_seconds", 3.0)),
        user_agents=api_cfg.get("user_agents"),
        date_format=api_cfg.get("date_format", "%Y-%m-%d"),
        flights_path=None,
        field_map={},
        mock_response_path=api_cfg.get("mock_response_path"),
        json_template=api_cfg.get("json_template"),
        use_mobile_signing=api_cfg.get("use_mobile_signing", True),
    )
    
    client = FrontierClient(config)
    print("\nAttempting API handshake to verify newly generated identity...")
    success = client.run_mobile_handshake()
    
    if success:
        print("✅ Handshake successful! The generated tokens work.")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(cfg_dict, f, indent=2)
        print(f"✅ Saved valid config to {target_path}")
    else:
        print("❌ Handshake failed. The new tokens were rejected. Check your connection or mobile api conditions.")
        sys.exit(1)

if __name__ == "__main__":
    generate_config()
