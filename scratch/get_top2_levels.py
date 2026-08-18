import sys
import os
sys.path.append(os.getcwd())

import pandas as pd
from xauusd_event_finder import fetch_latest_data, compute_all_levels

df_daily, df_1m = fetch_latest_data()
current_price = float(df_1m.iloc[-1]['Close'])
levels = compute_all_levels(df_daily)

# Separate into resistances (above) and supports (below)
resistances = [l for l in levels if l['price'] > current_price]
supports = [l for l in levels if l['price'] < current_price]

# Sort resistances ascending (closest to current price)
resistances.sort(key=lambda l: l['price'])
# Sort supports descending (closest to current price)
supports.sort(key=lambda l: l['price'], reverse=True)

print(f"Current Spot Gold Price: ${current_price:,.2f} USD\n")

print("=== 2 NEAREST RESISTANCE LEVELS (ABOVE CURRENT PRICE) ===")
for i, r in enumerate(resistances[:2], 1):
    gap_pct = (r['price'] - current_price) / current_price * 100
    print(f"R{i}: ${r['price']:,.2f} | Timeframe: {r['timeframe']} ({r['name']}) | Gap: +{gap_pct:.2f}%")

print("\n=== 2 NEAREST SUPPORT LEVELS (BELOW CURRENT PRICE) ===")
for i, s in enumerate(supports[:2], 1):
    gap_pct = (current_price - s['price']) / current_price * 100
    print(f"S{i}: ${s['price']:,.2f} | Timeframe: {s['timeframe']} ({s['name']}) | Gap: -{gap_pct:.2f}%")
