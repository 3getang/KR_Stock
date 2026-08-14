"""
GitHub Actions에서 주기적으로(5분마다) 실행되는 스크립트.
Yahoo Finance에서 국내 종목 시세를 가져와 Firebase Realtime Database에 저장한다.
공유 웹사이트(kr_stocks_live.html)는 이 Firebase 데이터를 실시간으로 읽어서 보여준다.

GitHub Actions의 스케줄은 최소 5분 간격까지만 지원하므로, 한 번 실행될 때
내부적으로 60초 간격으로 5번(=약 5분) 반복 조회해서 실질적으로 1분 간격
갱신 효과를 낸다.
"""

import time
from datetime import datetime

import requests

FIREBASE_DB_URL = "https://stock-3567c-default-rtdb.firebaseio.com"

STOCKS = [
    {"ticker": "005930.KS", "name": "삼성전자"},
    {"ticker": "000720.KS", "name": "현대건설"},
    {"ticker": "161890.KS", "name": "한국콜마"},
    {"ticker": "200880.KS", "name": "서연이화"},
]

HEADERS = {"User-Agent": "Mozilla/5.0"}
PERIOD_DAYS = [("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)]


def find_close_on_or_before(timestamps, closes, target_ts):
    result = None
    for t, c in zip(timestamps, closes):
        if c is None:
            continue
        if t <= target_ts:
            result = c
        else:
            break
    if result is None:
        for c in closes:
            if c is not None:
                result = c
                break
    return result


def fetch_stock(ticker: str, name: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    resp = requests.get(url, params={"range": "1y", "interval": "1d"}, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []

    price = meta["regularMarketPrice"]
    gmtoffset = meta.get("gmtoffset", 0)
    now_ts = time.time()

    def local_date(ts):
        return datetime.utcfromtimestamp(ts + gmtoffset).date()

    valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    prev_close = None
    if valid:
        last_t, last_c = valid[-1]
        if local_date(last_t) == local_date(now_ts):
            if len(valid) >= 2:
                prev_close = valid[-2][1]
        else:
            prev_close = last_c

    changes = {}
    if prev_close:
        d1 = price - prev_close
        changes["1d"] = {"abs": d1, "pct": d1 / prev_close * 100}
    else:
        changes["1d"] = {"abs": None, "pct": None}

    for key, days in PERIOD_DAYS:
        base = find_close_on_or_before(timestamps, closes, now_ts - days * 86400)
        if base:
            diff = price - base
            changes[key] = {"abs": diff, "pct": diff / base * 100}
        else:
            changes[key] = {"abs": None, "pct": None}

    return {
        "ticker": ticker,
        "name": name,
        "price": price,
        "currency": meta.get("currency", "KRW"),
        "changes": changes,
    }


def update_once():
    stocks_data = {}
    for s in STOCKS:
        try:
            data = fetch_stock(s["ticker"], s["name"])
            key = s["ticker"].replace(".", "_")
            stocks_data[key] = data
            print(f"OK  {s['ticker']} {s['name']} price={data['price']}")
        except Exception as e:
            print(f"FAIL {s['ticker']}: {e}")

    payload = {
        "updatedAt": int(time.time() * 1000),
        "stocks": stocks_data,
    }

    r = requests.put(f"{FIREBASE_DB_URL}/prices.json", json=payload, timeout=15)
    r.raise_for_status()
    print("Firebase 저장 완료:", r.status_code)


def main():
    ITERATIONS = 5
    INTERVAL_SEC = 60

    for i in range(ITERATIONS):
        print(f"--- {i + 1}/{ITERATIONS}회차 ---")
        update_once()
        if i < ITERATIONS - 1:
            time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
    
