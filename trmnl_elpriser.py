#!/usr/bin/env python3
from datetime import datetime
import requests
import os

# Konfiguration
# Henter fra GitHub Secret eller lokal fallback
TRMNL_WEBHOOK_URL = os.environ.get("TRMNL_WEBHOOK_URL", "https://trmnl.com/api/custom_plugins/<DIT_PLUGIN_UUID>")
AREA = "DK1"
NET_COMPANY = "trefor"

# 1. Hent data fra elpriser.org
url = f"https://elpriser.org/api/prices?area={AREA}&gln={NET_COMPANY}&mode=net_inkl_alt"

try:
    res = requests.get(url, timeout=15)
    res.raise_for_status()
    data = res.json()
except Exception as err:
    print(f"Fejl ved hentning af elpriser: {err}")
    raise SystemExit(1)

records = data.get("schedule", data.get("prices", []))
if not records:
    print("Ingen prisdata modtaget")
    raise SystemExit(0)

now = datetime.now()
now_hour_start = now.replace(minute=0, second=0, microsecond=0)

# 2. Parse og sorter poster
parsed_records = []
for r in records:
    dt = datetime.fromisoformat(r["time"])
    p = round(float(r["price"]), 2)
    parsed_records.append({"dt": dt, "price": p})

parsed_records.sort(key=lambda x: x["dt"])

# Filtrer fremtidige timer (fra nuværende time og frem)
future_records = [r for r in parsed_records if r["dt"] >= now_hour_start]

# 3. Beregn de 3 billigste sammenhængende timer (Sliding Window)
best_window = None
lowest_avg = float("inf")
best_start_dt = None
best_end_dt = None

if len(future_records) >= 3:
    for i in range(len(future_records) - 2):
        window = future_records[i:i + 3]
        avg_price = sum(r["price"] for r in window) / 3.0
        if avg_price < lowest_avg:
            lowest_avg = avg_price
            best_start_dt = window[0]["dt"]
            best_end_dt = window[2]["dt"]
            
            day_label = "I dag" if best_start_dt.date() == now.date() else "I morgen"
            end_hour_display = (best_end_dt.hour + 1) % 24

            best_window = {
                "start": best_start_dt.strftime("%H:00"),
                "end": f"{end_hour_display:02d}:00",
                "day": day_label,
                "avg_price": f"{avg_price:.2f}"
            }
else:
    best_window = {
        "start": "--:--",
        "end": "--:--",
        "day": "Ikke nok data",
        "avg_price": "0.00"
    }

# 4. Skaleringsparametre for søjlediagram
all_future_prices = [r["price"] for r in future_records] if future_records else [0.0]
min_val = min(all_future_prices)
max_val = max(all_future_prices)
price_range = (max_val - min_val) if (max_val - min_val) > 0 else 1.0

# 5. Generer søjler til diagram og dagens tabel
chart_bars = []
current_price = None

for r in future_records:
    dt = r["dt"]
    p = r["price"]
    hour_label = dt.strftime("%H")
    bar_height = int(15 + ((p - min_val) / price_range) * 85)
    
    is_now = (dt.date() == now.date() and dt.hour == now.hour)
    if is_now:
        current_price = p

    # Tjek om timen er en del af de 3 ladetimer
    is_charge_hour = False
    if best_start_dt and best_end_dt:
        is_charge_hour = (best_start_dt <= dt <= best_end_dt)

    chart_bars.append({
        "hour": hour_label,
        "price": f"{p:.2f}",
        "height": bar_height,
        "is_now": is_now,
        "is_charge_hour": is_charge_hour,
        "is_peak": (17 <= dt.hour <= 20)  # Trefor spidslast
    })

today_table = []
for r in parsed_records:
    if r["dt"].date() == now.date():
        today_table.append({
            "hour": r["dt"].strftime("%H:00"),
            "price": f"{r['price']:.2f}",
            "is_now": (r["dt"].hour == now.hour)
        })

# 6. Afsend payload til TRMNL
payload = {
    "merge_variables": {
        "area": f"{AREA} / Trefor",
        "current_price": f"{(current_price if current_price is not None else min_val):.2f}",
        "min_price": f"{min_val:.2f}",
        "max_price": f"{max_val:.2f}",
        "charge_window": best_window,
        "updated_at": now.strftime("%H:%M"),
        "chart_bars": chart_bars[:30],
        "today_table": today_table[::2]
    }
}

response = requests.post(TRMNL_WEBHOOK_URL, json=payload, timeout=10)
print(f"Status: {response.status_code}")
