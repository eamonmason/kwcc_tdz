#!/usr/bin/env python3
"""Test script to fetch Stage 1 TdZ event from ZwiftPower with OAuth authentication."""

import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse

from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def test_zwiftpower_oauth():
    """Test ZwiftPower OAuth authentication and find TdZ events."""
    username = os.environ.get("ZWIFTPOWER_USERNAME")
    password = os.environ.get("ZWIFTPOWER_PASSWORD")

    if not username or not password:
        print("ERROR: ZWIFTPOWER_USERNAME and ZWIFTPOWER_PASSWORD must be set in .env")
        sys.exit(1)

    print(f"Attempting OAuth login for: {username}")
    print()

    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:

        # Step 1: Start the OAuth flow
        print("=" * 60)
        print("Step 1: Starting OAuth flow...")
        print("=" * 60)

        oauth_url = "https://zwiftpower.com/ucp.php?mode=login&login=external&oauth_service=oauthzpsso"
        print(f"Requesting: {oauth_url}")

        response = client.get(oauth_url)
        print(f"Status: {response.status_code}")
        print(f"Redirected to: {response.url}")

        # The OAuth flow should redirect to Zwift's login page
        if "zwift.com" not in str(response.url):
            print("Unexpected redirect - not going to Zwift OAuth")
            return False

        print("Redirected to Zwift login page")
        soup = BeautifulSoup(response.text, "lxml")

        # Look for login form on Zwift
        login_form = soup.find("form")
        if not login_form:
            print("No login form found")
            return False

        print("Found Zwift login form")
        action = login_form.get("action", "")
        print(f"Form action: {action}")

        # Get form fields
        form_data = {}
        inputs = login_form.find_all("input")
        for inp in inputs:
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        # Fill in credentials
        if "username" in form_data or "email" in form_data:
            email_field = "email" if "email" in form_data else "username"
            form_data[email_field] = username
            form_data["password"] = password

        print()
        print("=" * 60)
        print("Step 2: Submitting Zwift login...")
        print("=" * 60)

        # Determine the submit URL
        if action.startswith("http"):
            submit_url = action
        elif action.startswith("/"):
            parsed = urlparse(str(response.url))
            submit_url = f"{parsed.scheme}://{parsed.netloc}{action}"
        else:
            submit_url = str(response.url)

        print(f"Submitting to: {submit_url}")

        # Submit login form
        login_response = client.post(
            submit_url,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        print(f"Login response status: {login_response.status_code}")
        print(f"Redirected to: {login_response.url}")

        # Check if we're back on ZwiftPower
        if "zwiftpower.com" not in str(login_response.url):
            print("Login may have failed or OAuth flow incomplete")
            return False

        print("Successfully redirected back to ZwiftPower!")

        # Step 3: Access events page
        print()
        print("=" * 60)
        print("Step 3: Accessing events page...")
        print("=" * 60)

        events_response = client.get("https://zwiftpower.com/events.php")
        print(f"Events page status: {events_response.status_code}")

        # Save HTML for debugging
        debug_file = DATA_DIR / "debug_events_page.html"
        debug_file.parent.mkdir(parents=True, exist_ok=True)
        debug_file.write_text(events_response.text)
        print(f"Saved events page HTML to: {debug_file}")

        soup = BeautifulSoup(events_response.text, "lxml")

        # Check if still requiring login
        if "Login Required" in events_response.text:
            print("Still seeing Login Required - OAuth may need more steps")
            return False

        print("Events page loaded!")

        # Look for event links in various formats
        all_links = soup.find_all("a", href=True)
        zid_links = [a for a in all_links if "zid=" in a.get("href", "")]
        print(f"Found {len(zid_links)} links with zid parameter")

        # The events page uses DataTables - check if there's data in script tags
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "DataTable" in script.string:
                print("Found DataTable initialization")

        # Check page title and structure
        title = soup.find("title")
        if title:
            print(f"Page title: {title.get_text(strip=True)}")

        # Step 4: Try the correct ZwiftPower API endpoints
        print()
        print("=" * 60)
        print("Step 4: Fetching events via ZwiftPower API...")
        print("=" * 60)

        # Try the cached events list first (past 3 days with results)
        endpoints = [
            ("Cached results (3 days)", "https://zwiftpower.com/cache3/lists/0_zwift_event_list_results_3.json"),
            ("Cached results (7 days)", "https://zwiftpower.com/cache3/lists/0_zwift_event_list_results_7.json"),
            ("Dynamic API (7 days)", "https://zwiftpower.com/api3.php?do=zwift_event_list_results&DAYS=7"),
        ]

        all_events = []

        for name, url in endpoints:
            print(f"\nTrying: {name}")
            print(f"URL: {url}")
            try:
                api_response = client.get(url)
                print(f"Status: {api_response.status_code}")

                if api_response.status_code == 200:
                    data = api_response.json()
                    if data and "data" in data:
                        print(f"  Found {len(data['data'])} events")
                        all_events.extend(data["data"])

                        # Debug: print first event structure
                        if data["data"]:
                            print("  Sample event keys:")
                            first_event = data["data"][0]
                            for k, v in list(first_event.items())[:15]:
                                print(f"    {k}: {str(v)[:50]}")
                        break  # Use first successful endpoint
                    else:
                        print(f"  No 'data' key in response")
            except json.JSONDecodeError:
                print(f"  Not JSON: {api_response.text[:100]}")
            except Exception as e:
                print(f"  Error: {e}")

        # Step 5: Filter for TdZ events and fetch results
        print()
        print("=" * 60)
        print("Step 5: Finding TdZ events and fetching results...")
        print("=" * 60)

        if all_events:
            # Filter for TdZ events (Stage 1: "Turf N Surf" on Makuri)
            # Fields: t = title/name, zid = event ID, tm = timestamp, r = route ID
            tdz_events = []
            for event in all_events:
                name = str(event.get("t", "")).lower()
                # Look for Tour de Zwift events
                if "tour de zwift" in name or "tdz" in name or "turf n surf" in name:
                    tdz_events.append(event)

            print(f"Found {len(tdz_events)} TdZ-related events from {len(all_events)} total")

            if tdz_events:
                print("\nTdZ Events:")
                from datetime import datetime as dt
                for event in tdz_events[:20]:
                    event_id = event.get("zid", event.get("DT_RowId", "?"))
                    event_name = event.get("t", "Unknown")
                    event_tm = event.get("tm", 0)
                    event_route = event.get("r", "")
                    # Convert timestamp to date
                    event_date = dt.fromtimestamp(event_tm).strftime("%Y-%m-%d %H:%M") if event_tm else "?"
                    print(f"  {event_id}: {event_name}")
                    print(f"       Route ID: {event_route}, Date: {event_date}")

                # Try fetching results for Category C events
                cat_c_events = [e for e in tdz_events if "cat.c" in str(e.get("t", "")).lower()]
                if not cat_c_events:
                    cat_c_events = tdz_events[:3]  # Take first 3 if no Cat.C

                for event in cat_c_events[:3]:
                    event_id = event.get("zid", event.get("DT_RowId"))
                    event_name = event.get("t", "Unknown")

                    if event_id:
                        print(f"\nFetching results for event {event_id}...")
                        print(f"Event: {event_name}")

                        # Try the results API
                        results_url = f"https://zwiftpower.com/cache3/results/{event_id}_view.json"
                        results_response = client.get(results_url)

                        if results_response.status_code == 200:
                            try:
                                results_data = results_response.json()
                                if "data" in results_data and results_data["data"]:
                                    print(f"Got {len(results_data['data'])} results!")

                                    # Save the results for debugging
                                    debug_results = DATA_DIR / f"debug_results_{event_id}.json"
                                    debug_results.write_text(json.dumps(results_data, indent=2))
                                    print(f"Saved results to: {debug_results}")

                                    # Show top 5
                                    print("Top 5 finishers:")
                                    for r in results_data["data"][:5]:
                                        rider_name = r.get("name", r.get("n", "Unknown"))
                                        time_str = r.get("time", r.get("t", "N/A"))
                                        print(f"  {rider_name}: {time_str}")
                                else:
                                    print(f"No data in response: {str(results_data)[:200]}")
                            except json.JSONDecodeError:
                                print(f"Not JSON: {results_response.text[:100]}")

                        # Also try dynamic API
                        dyn_url = f"https://zwiftpower.com/api3.php?do=event_results&zid={event_id}"
                        dyn_response = client.get(dyn_url)
                        if dyn_response.status_code == 200:
                            try:
                                dyn_data = dyn_response.json()
                                if "data" in dyn_data:
                                    print(f"Dynamic API: {len(dyn_data['data'])} results")
                            except json.JSONDecodeError:
                                pass
            else:
                print("No TdZ events found")
                print("\nFirst 10 events found:")
                for event in all_events[:10]:
                    event_id = event.get("zid", event.get("DT_RowId", "?"))
                    event_name = event.get("t", "Unknown")
                    print(f"  {event_id}: {event_name}")
        else:
            print("No events found in any API endpoint")

        # Step 6: Look for KWCC riders in the results
        print()
        print("=" * 60)
        print("Step 6: Finding KWCC riders in TdZ Stage 1 results...")
        print("=" * 60)

        # Load KWCC rider IDs from CSV
        from src.config import load_riders_from_csv
        riders_csv = PROJECT_ROOT / "KW TDZ sign on 2026 - Sheet1.csv"
        if riders_csv.exists():
            rider_registry = load_riders_from_csv(riders_csv)
            kwcc_ids = {r.zwiftpower_id for r in rider_registry.riders}
            kwcc_by_id = {r.zwiftpower_id: r for r in rider_registry.riders}
            print(f"Loaded {len(kwcc_ids)} KWCC rider IDs")

            # Search through all TdZ events for KWCC riders
            kwcc_found = []

            # Get unique Cat.C TdZ events (Turf N Surf route = 763 based on ZP data)
            # We need to search all events that match Stage 1 pattern
            stage1_events = [e for e in tdz_events if "stage 1" in e.get("t", "").lower()]
            print(f"\nSearching {len(stage1_events)} Stage 1 events for KWCC riders...")

            for event in stage1_events[:50]:  # Check up to 50 events
                event_id = event.get("zid")
                event_name = event.get("t", "Unknown")

                if not event_id:
                    continue

                # Fetch results
                results_url = f"https://zwiftpower.com/cache3/results/{event_id}_view.json"
                try:
                    results_response = client.get(results_url)
                    if results_response.status_code == 200:
                        results_data = results_response.json()
                        if "data" in results_data:
                            for rider in results_data["data"]:
                                rider_zwid = str(rider.get("zwid", ""))
                                if rider_zwid in kwcc_ids:
                                    kwcc_found.append({
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "rider_id": rider_zwid,
                                        "rider_name": rider.get("name", "Unknown"),
                                        "time": rider.get("time", [0, 0])[0] if isinstance(rider.get("time"), list) else rider.get("time", 0),
                                        "category": rider.get("category", "?"),
                                        "kwcc_rider": kwcc_by_id.get(rider_zwid),
                                    })
                except Exception as e:
                    pass  # Skip failed requests

            if kwcc_found:
                print(f"\nFound {len(kwcc_found)} KWCC results in Stage 1 events!")
                print("\nKWCC Riders with Stage 1 results:")
                for result in kwcc_found[:30]:
                    kwcc_rider = result.get("kwcc_rider")
                    handicap = kwcc_rider.handicap_group if kwcc_rider else "?"
                    time_secs = result["time"]
                    time_mins = time_secs // 60
                    time_rem = time_secs % 60
                    print(f"  {result['rider_name']} ({handicap})")
                    print(f"    Event: {result['event_name']}")
                    print(f"    Time: {int(time_mins)}:{int(time_rem):02d} ({time_secs:.1f}s), Cat: {result['category']}")
            else:
                print("No KWCC riders found in Stage 1 events yet")
        else:
            print(f"Riders CSV not found: {riders_csv}")

        print()
        print("=" * 60)
        print("Summary")
        print("=" * 60)
        print("OAuth authentication successful!")
        print(f"Debug HTML saved to: {debug_file}")

        return True


if __name__ == "__main__":
    test_zwiftpower_oauth()
