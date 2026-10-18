#!/usr/bin/env python3
import os
from datetime import datetime, timedelta
import requests

# Konfiguration
TRMNL_WEBHOOK_URL = os.environ.get(
    "TRMNL_WEBHOOK_URL",
    ""
)

BASE_URL = "https://elpriser.org/api/prices?area=dk1&gln=5790000392261&mode=net_inkl_alt&charges=current"

def fetch_prices_for_date(target_date: str):
    """Henter priser for en specifik dato (YYYY-MM-DD)."""
    url = f"{BASE_URL}&date={target_date}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Advarsel: Fejl ved hentning for {target_date}: {e}")
    return None

now = datetime.now()
today_str = now.strftime("%Y-%m-%d")
tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

# 1. Hent data for i dag
today_data = fetch_prices_for_date(today_str)
if not today_data or "prices" not in today_data:
    # Fallback uden eksplicit datofilter
    try:
        res = requests.get(BASE_URL, timeout=10)
        today_data = res.json()
    except Exception as e:
        print(f"Kritisk fejl: Kunne ikke hente elpriser: {e}")
        raise SystemExit(1)

# Hent data for i morgen (hvis frigivet)
tomorrow_data = fetch_prices_for_date(tomorrow_str)

# 2. Saml og parse alle tilgængelige timer
all_records = []

def parse_day_records(day_data, day_date_str):
    records = []
    prices_list = day_data.get("prices", [])
    for item in prices_list:
        h = int(item["hour"])
        p = round(float(item["price"]), 2)
        dt = datetime.strptime(f"{day_date_str} {h:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        records.append({"dt": dt, "hour": h, "price": p})
    return records

all_records.extend(parse_day_records(today_data, today_data.get("date", today_str)))

if tomorrow_data and "prices" in tomorrow_data and tomorrow_data["prices"]:
    all_records.extend(parse_day_records(tomorrow_data, tomorrow_str))

all_records.sort(key=lambda x: x["dt"])

# 3. Filtrer fremtidige timer (fra indeværende time og frem)
now_hour_start = now.replace(minute=0, second=0, microsecond=0)
future_records = [r for r in all_records if r["dt"] >= now_hour_start]

# Nuværende pris
current_price = today_data.get("current_price")
if current_price is None:
    current_hour_rec = next((r for r in all_records if r["dt"] == now_hour_start), None)
    current_price = current_hour_rec["price"] if current_hour_rec else all_records[0]["price"]
current_price = round(float(current_price), 2)

# 4. Find de 3 billigste sammenhængende timer (Sliding window)
best_window = {
    "start": "--:--",
    "end": "--:--",
    "day": "Ikke nok data",
    "avg_price": "0.00"
}
best_start_dt = None
best_end_dt = None

if len(future_records) >= 3:
    lowest_avg = float("inf")
    for i in range(len(future_records) - 2):
        window = future_records[i:i + 3]
        avg = sum(r["price"] for r in window) / 3.0
        if avg < lowest_avg:
            lowest_avg = avg
            best_start_dt = window[0]["dt"]
            best_end_dt = window[2]["dt"]
            
            day_text = "I dag" if best_start_dt.date() == now.date() else "I morgen"
            end_display_hour = (best_end_dt.hour + 1) % 24
            
            best_window = {
                "start": best_start_dt.strftime("%H:00"),
                "end": f"{end_display_hour:02d}:00",
                "day": day_text,
                "avg_price": f"{avg:.2f}"
            }

# 5. Skalering og søjler til diagram
future_prices = [r["price"] for r in future_records] if future_records else [current_price]
min_val = min(future_prices)
max_val = max(future_prices)
price_range = (max_val - min_val) if (max_val - min_val) > 0 else 1.0

chart_bars = []
for r in future_records:
    dt = r["dt"]
    p = r["price"]
    bar_height = int(15 + ((p - min_val) / price_range) * 85)
    
    is_now = (dt == now_hour_start)
    is_charge_hour = False
    if best_start_dt and best_end_dt:
        is_charge_hour = (best_start_dt <= dt <= best_end_dt)
        
    chart_bars.append({
        "hour": f"{r['hour']:02d}",
        "price": f"{p:.2f}",
        "height": bar_height,
        "is_now": is_now,
        "is_charge_hour": is_charge_hour,
        "is_peak": (17 <= r["hour"] <= 20)  # Trefor spidslast
    })

# 6. Dagens tabel (hver 2. time)
today_table = []
for r in all_records:
    if r["dt"].date() == now.date():
        today_table.append({
            "hour": f"{r['hour']:02d}:00",
            "price": f"{r['price']:.2f}",
            "is_now": (r["dt"] == now_hour_start)
        })

# 7. Payload til TRMNL
payload = {
    "merge_variables": {
        "area": "DK1 / Trefor",
        "current_price": f"{current_price:.2f}",
        "min_price": f"{min_val:.2f}",
        "max_price": f"{max_val:.2f}",
        "charge_window": best_window,
        "updated_at": now.strftime("%H:%M"),
        "chart_bars": chart_bars[:30],
        "today_table": today_table[::2]
    }
}

res = requests.post(TRMNL_WEBHOOK_URL, json=payload, timeout=10)
print(f"TRMNL Webhook respons: {res.status_code}")
