import requests
import json
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

os.makedirs('data', exist_ok=True)

HEADERS = {'User-Agent': 'TravelDashboard/1.0 (contact: github.com/claycoomer/travel-dashboard)'}

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

INTL_AIRPORTS = [
    {"code": "ATL", "name": "Atlanta Hartsfield-Jackson"},
    {"code": "LAX", "name": "Los Angeles International"},
    {"code": "ORD", "name": "Chicago O'Hare"},
    {"code": "DFW", "name": "Dallas/Fort Worth"},
    {"code": "JFK", "name": "New York JFK"},
    {"code": "SFO", "name": "San Francisco International"},
    {"code": "SEA", "name": "Seattle-Tacoma"},
    {"code": "MIA", "name": "Miami International"},
    {"code": "EWR", "name": "Newark Liberty"},
    {"code": "IAH", "name": "Houston George Bush"},
    {"code": "MCO", "name": "Orlando International"},
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
        table = soup.find('table')
        if table:
            for row in table.find_all('tr'):
                th = row.find('th')
                tds = row.find_all('td')
                if not th or not tds:
                    continue
                country = re.sub(r'\d+$', '', th.get_text(strip=True)).strip()
                level_text = tds[0].get_text(strip=True)
                match = re.search(r'Level\s*(\d)', level_text, re.IGNORECASE)
                level = int(match.group(1)) if match else 0
                date = tds[-1].get_text(strip=True)
                if country and level > 0:
                    advisories.append({'country': country, 'level': level, 'level_text': level_text, 'date': date})

        advisories.sort(key=lambda x: x['level'], reverse=True)
        print(f"     {len(advisories)} advisories fetched")
        return {'last_updated': now_iso(), 'source': 'US Department of State', 'advisories': advisories}
    except Exception as e:
        print(f"     ERROR: {e}")
        return {'last_updated': now_iso(), 'error': str(e), 'advisories': []}

# ─────────────────────────────────────────
# TSA THROUGHPUT
# ─────────────────────────────────────────
def load_tsa_archive():
    path = 'data/tsa_archive.json'
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_tsa_archive(archive, new_records):
    for r in new_records:
        if r.get('date') and r.get('travelers_current'):
            archive[r['date']] = r['travelers_current']
    with open('data/tsa_archive.json', 'w') as f:
        json.dump(archive, f, indent=2)

def prior_year_count(archive, date_str):
    from datetime import timedelta
    current = None
    for fmt in ['%m/%d/%Y', '%-m/%-d/%Y', '%m/%d/%y']:
        try:
            current = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if not current:
        return ''
    for delta in [0, 1, -1, 2, -2, 3, -3]:
        candidate = current.replace(year=current.year - 1) + timedelta(days=delta)
        for fmt in ['%-m/%-d/%Y', '%m/%d/%Y']:
            try:
                key = candidate.strftime(fmt)
                if key in archive:
                    return archive[key]
            except Exception:
                continue
    return ''

def fetch_tsa():
    print("  → TSA throughput...")
    archive = load_tsa_archive()
    try:
        url = "https://www.tsa.gov/travel/passenger-volumes"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        records = []
        table = soup.find('table')
        if table:
            header_row = table.find('tr')
            header_cells = header_row.find_all(['th', 'td']) if header_row else []
            print(f"     TSA columns: {[c.get_text(strip=True) for c in header_cells]}")
            for row in table.find_all('tr')[1:]:
                cols = [td.get_text(strip=True).replace(',', '') for td in row.find_all('td')]
                if not cols or not cols[0]:
                    continue
                records.append({
                    'date': cols[0],
                    'travelers_current': cols[1] if len(cols) > 1 else '',
                    'travelers_prior':   cols[2] if len(cols) > 2 else '',
                })

        records = records[:30]
        for r in records:
            if not r.get('travelers_prior'):
                r['travelers_prior'] = prior_year_count(archive, r['date'])

        save_tsa_archive(archive, records)
        print(f"     {len(records)} records fetched")
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
    for url in ["https://nasstatus.faa.gov/api/airport-delay-list",
                "https://nasstatus.faa.gov/api/airport-status-list"]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            print(f"     {url} → HTTP {resp.status_code}")
            if resp.status_code == 200 and resp.text.strip():
                data = resp.json()
                if isinstance(data, list) and data:
                    delays = data
                    break
                elif isinstance(data, dict):
                    for key in ('delays', 'Delays', 'GroundDelays', 'programs'):
                        if data.get(key):
                            delays = data[key]
                            break
                    if delays:
                        break
        except Exception as e:
            print(f"     {url} error: {e}")

    print(f"     {len(delays)} delay records")
    return {'last_updated': now_iso(), 'source': 'FAA NAS Status', 'delays': delays}

# ─────────────────────────────────────────
# NWS WEATHER DISRUPTION ALERTS
# ─────────────────────────────────────────
def fetch_weather_alerts():
    print("  → NWS weather disruption alerts...")
    try:
        url = "https://api.weather.gov/alerts/active"
        params = {
            'status': 'actual',
            'message_type': 'alert',
            'severity': 'Extreme,Severe',
            'urgency': 'Immediate,Expected',
            'limit': 100
        }
        resp = requests.get(
            url, params=params,
            headers={**HEADERS, 'Accept': 'application/geo+json'},
            timeout=30
        )
        resp.raise_for_status()
        features = resp.json().get('features', [])

        # Filter for weather event types most relevant to travel disruption
        travel_relevant = {
            'Blizzard Warning', 'Winter Storm Warning', 'Winter Storm Watch',
            'Ice Storm Warning', 'Freezing Rain Advisory', 'Heavy Snow Warning',
            'Tornado Warning', 'Tornado Watch', 'Severe Thunderstorm Warning',
            'Severe Thunderstorm Watch', 'Tropical Storm Warning', 'Tropical Storm Watch',
            'Hurricane Warning', 'Hurricane Watch', 'High Wind Warning', 'High Wind Watch',
            'Wind Advisory', 'Dense Fog Advisory', 'Freezing Fog Advisory',
            'Flash Flood Warning', 'Flood Warning', 'Excessive Heat Warning',
            'Dust Storm Warning', 'Dust Advisory'
        }

        alerts = []
        for f in features:
            p = f.get('properties', {})
            event = p.get('event', '')
            if event not in travel_relevant:
                continue
            alerts.append({
                'event':    event,
                'severity': p.get('severity', ''),
                'urgency':  p.get('urgency', ''),
                'areas':    p.get('areaDesc', ''),
                'headline': p.get('headline', ''),
                'onset':    p.get('onset', ''),
                'expires':  p.get('expires', ''),
            })

        # Sort: Extreme first, then Severe
        severity_order = {'Extreme': 0, 'Severe': 1}
        alerts.sort(key=lambda x: severity_order.get(x['severity'], 9))

        print(f"     {len(alerts)} travel-relevant alerts")
        return {'last_updated': now_iso(), 'source': 'NOAA / National Weather Service', 'alerts': alerts}
    except Exception as e:
        print(f"     ERROR: {e}")
        return {'last_updated': now_iso(), 'error': str(e), 'alerts': []}

# ─────────────────────────────────────────
# STATE DEPT ACTIVE TRAVEL ALERTS
# Event-specific emergency alerts, distinct from country-level advisories
# ─────────────────────────────────────────
def fetch_state_dept_alerts():
    print("  → State Dept active travel alerts...")
    try:
        url = "https://travel.state.gov/content/travel/en/international-travel/emergencies/travel-alerts.html/"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        alerts = []

        # Strategy 1: same <th>/<td> table structure as advisory page
        table = soup.find('table')
        if table:
            for row in table.find_all('tr'):
                th = row.find('th')
                tds = row.find_all('td')
                if not th or not tds:
                    continue
                location = re.sub(r'\d+$', '', th.get_text(strip=True)).strip()
                description = tds[0].get_text(strip=True) if tds else ''
                date = tds[-1].get_text(strip=True) if len(tds) > 1 else ''
                if location:
                    alerts.append({
                        'location': location,
                        'description': description[:400],
                        'date': date
                    })

        # Strategy 2: linked list items (fallback if no table)
        if not alerts:
            content = soup.find('main') or soup.find('div', id='content') or soup.find('article')
            if content:
                for item in content.find_all('li'):
                    a = item.find('a')
                    if not a:
                        continue
                    text = item.get_text(strip=True)
                    if len(text) > 10:
                        alerts.append({
                            'location': a.get_text(strip=True),
                            'description': text[:400],
                            'date': ''
                        })

        print(f"     {len(alerts)} active alerts found")
        return {
            'last_updated': now_iso(),
            'source': 'US Department of State — Active Travel Alerts',
            'alerts': alerts[:30]
        }
    except Exception as e:
        print(f"     ERROR: {e}")
        return {'last_updated': now_iso(), 'error': str(e), 'alerts': []}

# ─────────────────────────────────────────
# ITA / i94 ARRIVALS
# ─────────────────────────────────────────
def fetch_ntto_monthly():
    """
    Fetch monthly international arrivals from NTTO Excel file.
    Source: https://www.trade.gov/travel-and-tourism-research/monthly-tourism-statistics
    Returns 2024 and 2025 monthly totals for YoY chart.
    """
    import io, re, openpyxl

    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"]

    try:
        # Step 1: scrape the landing page to find the latest Excel link
        page = requests.get(
            "https://www.trade.gov/travel-and-tourism-research/monthly-tourism-statistics",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"}
        )
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "lxml")

        excel_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".xlsx" in href.lower() and "monthly" in href.lower():
                excel_url = href if href.startswith("http") else "https://www.trade.gov" + href
                break

        if not excel_url:
            raise ValueError("Could not locate Excel link on NTTO page")

        # Step 2: download and parse
        r = requests.get(excel_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
        ws = wb.active

        data_2024 = {}
        data_2025 = {}

        for row in ws.iter_rows(values_only=True):
            if not row or row[0] is None:
                continue
            cell = str(row[0]).strip()
            # Look for rows labeled like "2024" or "2025"
            if re.match(r'^202[45]$', cell):
                year = int(cell)
                vals = []
                for v in row[1:]:
                    try:
                        vals.append(int(float(str(v).replace(",", ""))))
                    except (ValueError, TypeError):
                        vals.append(None)
                # Align to 12 months
                monthly = dict(zip(MONTHS, vals[:12]))
                if year == 2024:
                    data_2024 = monthly
                elif year == 2025:
                    data_2025 = monthly

        # Build YoY variance where both years have data
        yoy = {}
        for m in MONTHS:
            v24 = data_2024.get(m)
            v25 = data_2025.get(m)
            if v24 and v25 and v24 > 0:
                yoy[m] = round((v25 - v24) / v24 * 100, 1)
            else:
                yoy[m] = None

        return {
            "source": "NTTO Monthly Tourism Statistics",
            "excel_url": excel_url,
            "months": MONTHS,
            "y2024": [data_2024.get(m) for m in MONTHS],
            "y2025": [data_2025.get(m) for m in MONTHS],
            "yoy_pct": [yoy[m] for m in MONTHS],
            "note": "2025 data available with ~3-6 month lag. Null = not yet published."
        }

    except Exception as e:
        print(f"  NTTO monthly fetch failed: {e}")
        # Graceful fallback — return placeholder so dashboard doesn't break
        return {
            "source": "NTTO (unavailable)",
            "excel_url": None,
            "months": MONTHS,
            "y2024": [None]*12,
            "y2025": [None]*12,
            "yoy_pct": [None]*12,
            "note": f"Data temporarily unavailable: {e}"
        }


def load_arrivals():
    """Static 2024 annual i94 data — most recent complete year available.
    2025 annual data won't publish until ~late 2026."""
    return {
        "data_year": 2024,
        "note": "Annual i94 detail data publishes with 12-18 month lag. 2025 annual data expected late 2026.",
        "by_country": {
            "labels": ["Canada","Mexico","UK","Japan","Germany","France","Brazil","South Korea","India","Australia","Italy","China","Netherlands","Spain","Other"],
            "values": [14500000,17200000,4800000,1900000,2100000,1750000,2300000,1600000,2800000,1400000,1150000,1050000,900000,950000,12600000]
        },
        "by_visa": {
            "labels": ["Visa Waiver (ESTA)","B1/B2 Tourist","F1 Student","H1B Work","J1 Exchange","L1 Intracompany","Other Nonimmigrant"],
            "values": [22400000,18600000,1100000,580000,340000,290000,4200000]
        },
        "by_age": {
            "labels": ["0-17","18-24","25-34","35-44","45-54","55-64","65+"],
            "values": [6800000,7200000,11400000,10600000,9800000,8200000,6000000]
        }
    }
    
# ─────────────────────────────────────────
# TRAVEL NEWS RSS FEEDS
# ─────────────────────────────────────────
def fetch_travel_news():
    print("  → Travel news RSS feeds...")
    import feedparser

    feeds = [
        {'name': 'Skift',             'url': 'https://skift.com/feed/'},
        {'name': 'Google News Travel', 'url': 'https://news.google.com/rss/search?q=US+travel+news+flight+disruption+travel+advisory&hl=en-US&gl=US&ceid=US:en'},
        {'name': 'Travel Weekly',      'url': 'https://www.travelweekly.com/rss'},
    ]

    items = []
    for f in feeds:
        try:
            feed = feedparser.parse(f['url'])
            for entry in feed.entries[:8]:
                title = entry.get('title', '').strip()
                if not title:
                    continue
                # Strip HTML tags from summary
                raw_summary = entry.get('summary', '') or ''
                summary = re.sub(r'<[^>]+>', '', raw_summary).strip()[:280]
                items.append({
                    'title':     title,
                    'link':      entry.get('link', ''),
                    'published': entry.get('published', ''),
                    'summary':   summary,
                    'source':    f['name'],
                })
            print(f"     {f['name']}: {len(feed.entries)} entries")
        except Exception as e:
            print(f"     {f['name']} error: {e}")

    print(f"     {len(items)} total news items")
    return {
        'last_updated': now_iso(),
        'sources': [f['name'] for f in feeds],
        'items': items[:30],
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

    with open('data/weather_alerts.json', 'w') as f:
        json.dump(fetch_weather_alerts(), f, indent=2)

    with open('data/state_alerts.json', 'w') as f:
        json.dump(fetch_state_dept_alerts(), f, indent=2)

    with open('data/arrivals.json', 'w') as f:
        json.dump(load_arrivals(), f, indent=2)

    with open('data/news.json', 'w') as f:
        json.dump(fetch_travel_news(), f, indent=2)

    meta = {'last_full_update': now_iso(), 'airports': TOP_15, 'version': '1.4'}
    with open('data/meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

        print("Fetching NTTO monthly arrivals trend...")
    ntto = fetch_ntto_monthly()
    with open("data/arrivals_monthly.json", "w") as f:
        json.dump(ntto, f, indent=2)
    print(f"  Monthly trend saved ({sum(1 for v in ntto['y2025'] if v is not None)} months of 2025 data)")

    print("Done.")
