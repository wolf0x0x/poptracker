import json
import math
import os
import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # The script still works with bundled demo data.
    requests = None


DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path=PROJECT_ROOT / ".env"):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()

DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"


def load_dictionary():
    if not DICT_PATH.exists():
        print(f"Warning: Dictionary file not found at {DICT_PATH}")
        return []
    with DICT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


TRACKING_ITEMS = load_dictionary()


def percentile(values, ratio):
    if not values:
        return 0
    pos = (len(values) - 1) * ratio
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return values[int(pos)]
    return values[lower] + (values[upper] - values[lower]) * (pos - lower)


def normalize_listing(item):
    price = item.get(
        "soldPrice",
        item.get("computedPrice", item.get("priceWithShipping", item.get("price", item.get("value", 0)))),
    )
    shipping = 0 if item.get("priceWithShipping") else item.get("shippingPrice", item.get("shipping", 0))
    currency = item.get("currency", "USD")
    sold_at = item.get("soldAt") or item.get("date")

    def numeric(value):
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = "".join(char for char in str(value or "0") if char.isdigit() or char in ".-")
        return float(cleaned or 0)

    return {
        "price": numeric(price) + numeric(shipping),
        "currency": currency,
        "soldAt": sold_at,
        "source": item.get("source", "demo"),
        "title": item.get("title", item.get("name", "")),
    }


def usd_price(listing):
    rates = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08, "CNY": 0.138, "HKD": 0.128, "JPY": 0.0064}
    return listing["price"] * rates.get(listing["currency"], 1.0)


def is_noise_listing(listing, negative_keywords):
    title = str(normalize_listing(listing).get("title", "")).lower()
    return any(keyword.lower() in title for keyword in negative_keywords)


def clean_prices(raw_listings, negative_keywords=None):
    negative_keywords = negative_keywords or []
    prices = []
    for listing in raw_listings:
        if is_noise_listing(listing, negative_keywords):
            continue
        normalized = normalize_listing(listing)
        price = round(usd_price(normalized), 2)
        if price > 1:
            prices.append(price)
    prices.sort()
    if len(prices) < 4:
        return prices

    q1 = percentile(prices, 0.25)
    q3 = percentile(prices, 0.75)
    iqr = q3 - q1
    lower = max(1, q1 - 1.5 * iqr)
    upper = q3 + 1.5 * iqr
    return [price for price in prices if lower <= price <= upper]


def trimmed_median(prices, trim_ratio=0.1):
    if not prices:
        return 0
    prices = sorted(prices)
    trim_count = math.floor(len(prices) * trim_ratio)
    if trim_count and len(prices) - trim_count * 2 >= 3:
        prices = prices[trim_count:-trim_count]
    return statistics.median(prices)


def trend_label(change):
    if change > 8:
        return "breakout", "突破上涨"
    if change < -8:
        return "cooldown", "热度回落"
    return "range", "区间震荡"


def risk_score(retail_price, avg_price, volatility, total_sold):
    premium = max(0, (avg_price - retail_price) / retail_price)
    liquidity_penalty = 0.22 if total_sold < 12 else 0.08 if total_sold < 25 else 0
    volatility_penalty = min(0.42, volatility * 1.15)
    premium_penalty = min(0.3, premium / 8)
    score = 100 * (0.2 + liquidity_penalty + volatility_penalty + premium_penalty)
    return round(min(99, max(8, score)))


def aggregate(raw_listings, retail_price, negative_keywords=None):
    prices = clean_prices(raw_listings, negative_keywords)
    if not prices:
        return None

    avg_price = statistics.fmean(prices)
    median_price = trimmed_median(prices)
    high = max(prices)
    low = min(prices)
    std_dev = statistics.pstdev(prices) if len(prices) > 1 else 0
    volatility = std_dev / avg_price if avg_price else 0
    roi = ((avg_price - retail_price) / retail_price) * 100
    total_sold = len(prices)
    risk = risk_score(retail_price, avg_price, volatility, total_sold)
    return {
        "avgSoldPrice": round(avg_price, 2),
        "medianSoldPrice": round(median_price, 2),
        "fairMarketValue": round(median_price, 2),
        "lowSoldPrice": round(low, 2),
        "highSoldPrice": round(high, 2),
        "totalSold": total_sold,
        "volatility": "High" if volatility > 0.28 else "Medium" if volatility > 0.16 else "Low",
        "volatilityValue": round(volatility, 3),
        "roi": round(roi, 1),
        "riskScore": risk,
        "cleanedSampleSize": len(prices),
        "valuationMethod": "IQR + 10% trimmed median",
    }


def fetch_live_listings(item):
    api_key = os.getenv("SOLDCOMPS_API_KEY")
    if not api_key or requests is None:
        return []

    url = os.getenv(
        "SOLDCOMPS_ENDPOINT",
        f"https://api.apify.com/v2/acts/caffein.dev~ebay-sold-listings/run-sync-get-dataset-items?token={api_key}",
    )
    keyword = item.get("search_string") or f"Pop Mart {item['ip']} {item['series']} {item['keywords']} blind box loose"
    payload = {"keyword": keyword, "count": 20, "daysToScrape": 30}
    try:
        if os.getenv("SOLDCOMPS_ENDPOINT"):
            response = requests.post(url, json={**payload, "apiKey": api_key}, timeout=30)
        else:
            response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        response_payload = response.json()
        if isinstance(response_payload, list):
            return response_payload
        return response_payload.get("results", response_payload.get("items", []))
    except Exception as exc:
        print(f"Live fetch failed for {item['sku']}: {exc}")
        return []


def demo_listings(item):
    today = datetime.now(timezone.utc).date()
    multiplier = item.get("demo_multiplier", 2.0)
    base = item["retail_price_usd"] * multiplier
    random.seed(item["sku"])
    listings = []
    for idx in range(42):
        age = random.randint(0, 28)
        cycle = math.sin((idx / 41) * math.pi * 2) * 0.08
        noise = random.uniform(-0.18, 0.2)
        price = base * (1 + cycle + noise)
        listings.append(
            {
                "soldPrice": round(price, 2),
                "shippingPrice": round(random.uniform(0, 8), 2),
                "currency": random.choice(["USD", "USD", "USD", "GBP", "EUR"]),
                "soldAt": (today - timedelta(days=age)).isoformat(),
                "source": "demo-secondary-market",
            }
        )
    listings.extend(
        [
            {"soldPrice": 0.99, "shippingPrice": 0, "currency": "USD", "source": "outlier"},
            {"soldPrice": base * 9, "shippingPrice": 25, "currency": "USD", "source": "bundle-outlier"},
        ]
    )
    return listings


def build_history(sku, avg_price):
    today = datetime.now(timezone.utc).date()
    random.seed(f"history-{sku}")
    points = []
    for days_ago in range(29, -1, -1):
        phase = (29 - days_ago) / 29
        drift = (phase - 0.5) * random.uniform(-0.12, 0.16)
        wave = math.sin(phase * math.pi * 2) * random.uniform(0.03, 0.08)
        noise = random.uniform(-0.025, 0.025)
        points.append(
            {
                "date": (today - timedelta(days=days_ago)).isoformat(),
                "avg": round(avg_price * (1 + drift + wave + noise), 2),
            }
        )
    points[-1]["avg"] = round(avg_price, 2)
    return points


def merge_price_history(file_path, avg_price):
    today = datetime.now(timezone.utc).date().isoformat()
    if file_path.exists():
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                old_history = json.load(handle).get("priceHistory", [])
        except Exception:
            old_history = []
    else:
        old_history = build_history(file_path.stem, avg_price)

    history = [point for point in old_history if point.get("date") != today]
    history.append({"date": today, "avg": round(avg_price, 2)})
    return history[-90:]


def investment_signal(metrics):
    roi = metrics["roi"]
    risk = metrics["riskScore"]
    liquidity = metrics["totalSold"]
    if roi > 160 and risk < 55 and liquidity >= 20:
        return "watch", "重点观察", "Strong watch"
    if risk > 72:
        return "caution", "谨慎追高", "Caution"
    if roi < 45:
        return "value", "低溢价建仓候选", "Low-premium candidate"
    return "hold", "持有跟踪", "Track / hold"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    index = []

    for item in TRACKING_ITEMS:
        raw = fetch_live_listings(item) or demo_listings(item)
        metrics = aggregate(raw, item["retail_price_usd"], item.get("negative_keywords", []))
        if not metrics:
            continue
        file_path = DATA_DIR / f"{item['sku']}.json"
        history = merge_price_history(file_path, metrics["fairMarketValue"])
        change = ((history[-1]["avg"] - history[-8]["avg"]) / history[-8]["avg"]) * 100
        trend_key, trend_zh = trend_label(change)
        signal_key, signal_zh, signal_en = investment_signal(metrics)
        affiliate_url = (
            "https://www.ebay.com/sch/i.html?_nkw="
            + item.get("search_string", item["keywords"]).replace(" ", "+").replace('"', "%22")
        )

        detail = {
            "sku": item["sku"],
            "ip": item["ip"],
            "series": item["series"],
            "name_zh": item["name_zh"],
            "name_en": item["name_en"],
            "rarity_zh": item["rarity"],
            "rarity_en": item["rarity_en"],
            "color": item["color"],
            "image": item.get("image", ""),
            "searchString": item.get("search_string", item["keywords"]),
            "negativeKeywords": item.get("negative_keywords", []),
            "refreshTier": item.get("refresh_tier", "weekly"),
            "refreshIntervalHours": 24 if item.get("refresh_tier") == "hot" else 168,
            "affiliateUrl": affiliate_url,
            "retailPrice": item["retail_price_usd"],
            "lastUpdated": today,
            "marketData": {
                **metrics,
                "priceChange7d": f"{change:+.1f}%",
                "trend": trend_key,
                "trend_zh": trend_zh,
                "signal": signal_key,
                "signal_zh": signal_zh,
                "signal_en": signal_en,
            },
            "priceHistory": history,
            "sources": ["eBay completed sales", "SoldComps-compatible API", "demo fallback"],
            "story": item.get("story"),
            "characters": item.get("characters"),
            "notes_zh": "价格为样例或 API 聚合结果，不构成投资建议。请以真实成交、品相、隐藏款概率和平台手续费综合判断。",
            "notes_en": "Prices are sample or API-aggregated metrics, not financial advice. Validate condition, rarity and fees before trading.",
        }

        with file_path.open("w", encoding="utf-8") as handle:
            json.dump(detail, handle, ensure_ascii=False, indent=2)

        index.append(
            {
                "sku": item["sku"],
                "ip": item["ip"],
                "series": item["series"],
                "name_zh": item["name_zh"],
                "name_en": item["name_en"],
                "rarity_zh": item["rarity"],
                "rarity_en": item["rarity_en"],
                "color": item["color"],
                "image": item.get("image", ""),
                "searchString": item.get("search_string", item["keywords"]),
                "refreshTier": item.get("refresh_tier", "weekly"),
                "affiliateUrl": affiliate_url,
                "retailPrice": item["retail_price_usd"],
                "avgSoldPrice": metrics["fairMarketValue"],
                "medianSoldPrice": metrics["medianSoldPrice"],
                "fairMarketValue": metrics["fairMarketValue"],
                "valuationMethod": metrics["valuationMethod"],
                "priceChange7d": f"{change:+.1f}%",
                "roi": metrics["roi"],
                "riskScore": metrics["riskScore"],
                "totalSold": metrics["totalSold"],
                "signal_zh": signal_zh,
                "signal_en": signal_en,
                "story": item.get("story"),
                "characters": item.get("characters"),
                "lastUpdated": today,
            }
        )

    with (DATA_DIR / "index.json").open("w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)

    print(f"Generated {len(index)} tracked Pop Mart assets in {DATA_DIR}")


if __name__ == "__main__":
    main()
