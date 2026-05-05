import requests
import json
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

os.makedirs('data', exist_ok=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; TravelDashboard/1.0; +https://github.com/claycoomer/travel-dashboard)'}

TOP_15 = [
    {"code": "ATL", "name": "Atlanta Hartsfield-Jackson"},
    {"code": "LAX", "name": "Los Angeles International"},
    {"code": "ORD", "name": "Chicago O'Hare"},
    {"code": "DFW", "name": "Dallas/Fort Worth"},
    {"code": "DEN", "name": "Denver International"},
    {"code": "JFK", "name": "New York JFK"},
    {"code": "SFO", "name": "San Francisco International"},
    {"code": "SEA", "name": "Seattle-Tacoma"},
    {"code": "LAS", "name": "Las Vegas Harry Reid"},
    {"code": "MCO", "name": "Orlando International"},
    {"code": "EWR", "name": "Newark Liberty"},
    {"code": "CLT", "name": "Charlotte Douglas"},
    {"code": "PHX", "name": "Phoenix Sky Harbor"},
    {"code": "MIA", "name": "Miami International"},
    {"code": "IAH", "name": "Houston George Bush"},
]

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ─────────────────────────────────────────
# STATE DEPT TRAVEL ADVISORIES
# ─────────────────────────────────────────
def fetch_advisories():
    print("  → State Dept advisories...")
    try:
        url = "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html/"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        advisories = []
        table = soup.find('table', attrs={'class': lambda c: c and 'table-data' in c})
        if not table:
            table = soup.find('table')

        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) < 2:
                    continue
                country = cols[0].get_text(strip=True)
                level_text = cols[1].get_text(strip=True)
                match = re.search(r'Level\s*(\d)', level_text, re.IGNORECASE)
                level = int(match.group(1)) if match else 0
                date = cols[2].get_text(strip=True) if len(cols) > 2 else ''
                if country:
                    advisories.append({'country': country, 'level': level, 'level_text': level_text, 'date': date})

        print(f"     {len(advisories)} advisories fetched")
        return {'last_updated': now_iso(), 'source': 'US Department of State', 'advisories': advisories}

    except Exception as e:
        print(f"     ERROR: {e}")
        return {'last_updated': now_iso(), 'error': str(e), 'advisories': []}

# ─────────────────────────────────────────
# TSA THROUGHPUT
# ─────────────────────────────────────────
def fetch_tsa():
    print("  → TSA throughput...")
    try:
        url = "https://www.tsa.gov/travel/passenger-volumes"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        records = []
        table = soup.find('table')
        if table:
            header_row = table.find('tr')
            headers = [th.get_text(strip=True) for th in header_row.find_all(['th','td'])] if header_row else []

            for row in table.find_all('tr')[1:]:
                cols = [td.get_text(strip=True).replace(',', '') for td in row.find_all('td')]
                if len(cols) >= 2:
                    records.append({
                        'date': cols[0],
                        'travelers_current': cols[1] if len(cols) > 1 else '',
                        'travelers_prior':   cols[2] if len(cols) > 2 else '',
                    })

        records = records[:30]
        print(f"     {len(records)} daily records fetched")
        return {'last_updated': now_iso(), 'source': 'TSA Checkpoint Travel Numbers', 'records': records}

    except Exception as e:
        print(f"     ERROR: {e}")
        return {'last_updated': now_iso(), 'error': str(e), 'records': []}

# ─────────────────────────────────────────
# FAA ATC DELAYS
# ─────────────────────────────────────────
def fetch_faa_delays():
    print("  → FAA ATC delays...")
    delays = []
    endpoints = [
        "https://nasstatus.faa.gov/api/airport-delay-list",
        "https://www.fly.faa.gov/flyfaa/flyfaaAPI.jsp",
    ]

    for url in endpoints:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        delays = data
                    elif isinstance(data, dict):
                        delays = data.get('delays', data.get('GroundDelays', data.get('Delay', [])))
                    if delays:
                        break
                except Exception:
                    pass
        except Exception as e:
            print(f"     Endpoint {url} failed: {e}")
            continue

    print(f"     {len(delays)} delay records found")
    return {'last_updated': now_iso(), 'source': 'FAA NAS Status', 'delays': delays}

# ─────────────────────────────────────────
# FAA NOTAMs (requires API key)
# ─────────────────────────────────────────
def fetch_notams():
    print("  → FAA NOTAMs...")
    api_key = os.environ.get('FAA_API_KEY', '')

    if not api_key:
        print("     FAA_API_KEY not configured — skipping NOTAMs")
        return {
            'last_updated': now_iso(),
            'note': 'FAA API key required. Register free at https://api.faa.gov/ then add FAA_API_KEY as a GitHub repository secret.',
            'notams': []
        }

    notams = []
    for airport in TOP_15:
        try:
            url = f"https://external-api.faa.gov/notamapi/v1/notams?icaoLocation={airport['code']}&pageSize=10"
            resp = requests.get(url, headers={**HEADERS, 'client_id': api_key}, timeout=20)
            if resp.status_code == 200:
                items = resp.json().get('items', [])
                for item in items:
                    props = item.get('properties', {}).get('coreNOTAMData', {}).get('notam', {})
                    notams.append({
                        'airport': airport['code'],
                        'id': props.get('id', ''),
                        'text': props.get('text', ''),
                        'effectiveStart': props.get('effectiveStart', ''),
                        'effectiveEnd': props.get('effectiveEnd', ''),
                    })
        except Exception as e:
            print(f"     {airport['code']} NOTAM error: {e}")

    print(f"     {len(notams)} NOTAMs fetched")
    return {'last_updated': now_iso(), 'source': 'FAA NOTAM API', 'notams': notams}

# ─────────────────────────────────────────
# ITA / i94 ARRIVALS (quarterly static)
# ─────────────────────────────────────────
def load_arrivals():
    print("  → ITA/i94 arrivals (static dataset)...")
    source_file = 'data/arrivals_source.json'
    if os.path.exists(source_file):
        with open(source_file) as f:
            return json.load(f)

    return {
        'last_updated': now_iso(),
        'data_period': '2024 Annual',
        'source': 'National Travel & Tourism Office (NTTO) / ITA i94 Arrivals',
        'note': 'Updated quarterly. Data typically lags 3–6 months. Source: ntto.gov',
        'total_arrivals': 80400000,
        'by_country': [
            {'country': 'Canada',          'arrivals': 22500000, 'share_pct': 28.1},
            {'country': 'Mexico',          'arrivals': 18200000, 'share_pct': 22.7},
            {'country': 'United Kingdom',  'arrivals':  5100000, 'share_pct':  6.4},
            {'country': 'Japan',           'arrivals':  2800000, 'share_pct':  3.5},
            {'country': 'Germany',         'arrivals':  2600000, 'share_pct':  3.2},
            {'country': 'France',          'arrivals':  2400000, 'share_pct':  3.0},
            {'country': 'Brazil',          'arrivals':  2200000, 'share_pct':  2.7},
            {'country': 'South Korea',     'arrivals':  2000000, 'share_pct':  2.5},
            {'country': 'Australia',       'arrivals':  1800000, 'share_pct':  2.2},
            {'country': 'India',           'arrivals':  1700000, 'share_pct':  2.1},
            {'country': 'Other',           'arrivals': 17100000, 'share_pct': 21.4},
        ],
        'by_visa_type': [
            {'visa_type': 'Visa Waiver Program (VWP)',  'arrivals': 28400000, 'share_pct': 35.5},
            {'visa_type': 'B-1/B-2 Tourist/Business',  'arrivals': 24600000, 'share_pct': 30.7},
            {'visa_type': 'Canadian Citizens (Exempt)', 'arrivals': 14200000, 'share_pct': 17.7},
            {'visa_type': 'Other Nonimmigrant',         'arrivals':  8200000, 'share_pct': 10.2},
            {'visa_type': 'Student (F/M Visa)',         'arrivals':  3200000, 'share_pct':  4.0},
            {'visa_type': 'Exchange Visitor (J Visa)',  'arrivals':  1800000, 'share_pct':  2.2},
        ],
        'by_age_band': [
            {'age_band': 'Under 15', 'arrivals':  6400000, 'share_pct':  8.0},
            {'age_band': '15–24',    'arrivals':  9600000, 'share_pct': 12.0},
            {'age_band': '25–34',    'arrivals': 14400000, 'share_pct': 18.0},
            {'age_band': '35–44',    'arrivals': 14400000, 'share_pct': 18.0},
            {'age_band': '45–54',    'arrivals': 12800000, 'share_pct': 16.0},
            {'age_band': '55–64',    'arrivals': 12000000, 'share_pct': 15.0},
            {'age_band': '65+',      'arrivals': 10400000, 'share_pct': 13.0},
        ],
    }

# ─────────────────────────────────────────
# RUN ALL
# ─────────────────────────────────────────
if __name__ == '__main__':
    print("Fetching travel dashboard data...")

    with open('data/advisories.json', 'w') as f:
        json.dump(fetch_advisories(), f, indent=2)

    with open('data/tsa.json', 'w') as f:
        json.dump(fetch_tsa(), f, indent=2)

    with open('data/delays.json', 'w') as f:
        json.dump(fetch_faa_delays(), f, indent=2)

    with open('data/notams.json', 'w') as f:
        json.dump(fetch_notams(), f, indent=2)

    with open('data/arrivals.json', 'w') as f:
        json.dump(load_arrivals(), f, indent=2)

    meta = {
        'last_full_update': now_iso(),
        'airports': TOP_15,
        'version': '1.0'
    }
    with open('data/meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

    print("Done. All data files updated in data/")
