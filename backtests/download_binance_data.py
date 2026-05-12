"""
download_binance_data.py  (v2 — CSV 版)
=========================================
从 Binance Vision 下载 SOLUSDT 永续 1H K 线,保存为单一 CSV。
"""

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

SYMBOL = "SOLUSDT"
INTERVAL = "1h"
START = date(2024, 1, 1)
END = date(2025, 1, 1)

PROJECT_ROOT = Path.home() / "hermes_ai"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_CSV = DATA_DIR / f"{SYMBOL}_2024_1h.csv"

URL_TEMPLATE = (
    "https://data.binance.vision/data/futures/um/monthly/klines/"
    "{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"
)


def download_month(year: int, month: int) -> pd.DataFrame:
    url = URL_TEMPLATE.format(symbol=SYMBOL, interval=INTERVAL, year=year, month=month)
    print(f"  正在下载: {year}-{month:02d}...")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(
                f, header=None,
                names=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades",
                    "taker_buy_base", "taker_buy_quote", "ignore",
                ],
            )
    return df


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    cur = START
    while cur < END:
        try:
            frames.append(download_month(cur.year, cur.month))
        except Exception as e:
            print(f"  ⚠️ {cur.year}-{cur.month:02d} 跳过: {e}")
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    df = pd.concat(frames, ignore_index=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ 数据下载完成: {OUTPUT_CSV}")
    print(f"   共 {len(df)} 根 K 线")


if __name__ == "__main__":
    main()
