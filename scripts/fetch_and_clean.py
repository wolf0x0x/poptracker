# 修改位置或参考文件：scripts/fetch_and_clean.py
import json
import math
import os
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    requests = None

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNC_STATE_FILE = DATA_DIR / "sync_state.json"
CHINA_TZ = ZoneInfo("Asia/Shanghai")


def china_today_date():
    return datetime.now(CHINA_TZ).date()


def china_today_iso():
    return china_today_date().isoformat()

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

# 内置兜底字典
TRACKING_ITEMS = [
    {
        "sku": "LABUBU-MACARON-01",
        "ip": "THE MONSTERS",
        "series": "Tasty Macarons",
        "keywords": "Labubu Macaron Vinyl Face",
        "search_string": '"Labubu" AND ("Macaron" OR "Tasty Macarons") AND ("vinyl face" OR "Pop Mart") -box -card -preorder -custom -fake -replica',
        "negative_keywords": ["box only", "card only", "preorder", "custom", "fake", "replica"],
        "refresh_tier": "hot",
        "retail_price_usd": 17.0,
        "name_zh": "Labubu 马卡龙搪胶脸",
        "name_en": "Labubu The Monsters Tasty Macarons",
        "rarity": "热门常规",
        "rarity_en": "Hot regular",
        "color": "#ff7eb6",
        "image": "",
    }
]

DEMO_MULTIPLIERS = {
    "LABUBU-MACARON-01": 4.35,
    "LABUBU-HAVEASEAT-01": 3.2,
    "SKULLPANDA-INKPLUM-01": 1.85,
    "MOLLY-SPACE-100-01": 2.15,
    "DIMOO-WORLD-01": 1.45,
    "HIRONO-LITTLE-MISCHIEF-01": 1.72,
}

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
    """
    清洗器：标准化不同上游数据源的字段。
    支持对接本地缓存成交样本的各种包装属性（格式兼容层）
    """
    # 优先提取具体数值，强化对于复杂嵌套JSON的包容性
    price = item.get("soldPrice", item.get("computedPrice", item.get("priceWithShipping", item.get("price", item.get("value", 0)))))
    if isinstance(price, dict): 
        price = price.get("value", price.get("amount", 0))
        
    shipping = 0 if item.get("priceWithShipping") else item.get("shippingPrice", item.get("shipping", 0))
    if isinstance(shipping, dict):
        shipping = shipping.get("value", shipping.get("amount", 0))

    currency = item.get("soldCurrency", item.get("currency", "USD"))
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")

    sold_at = item.get("soldAt") or item.get("endedAt") or item.get("date") or item.get("endTime")

    def numeric(value):
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = "".join(char for char in str(value or "0") if char.isdigit() or char in ".-")
        return float(cleaned or 0)

    return {
        "price": numeric(price) + numeric(shipping),
        "currency": str(currency).upper(),
        "soldAt": sold_at,
        "source": item.get("source", "live-api"),
        "title": item.get("title", item.get("name", "")),
    }

DEFAULT_RATES = {
    "USD": 1.0,
    "GBP": float(os.getenv("RATE_GBP", 1.27)),
    "EUR": float(os.getenv("RATE_EUR", 1.08)),
    "CNY": float(os.getenv("RATE_CNY", 0.138)),
    "HKD": float(os.getenv("RATE_HKD", 0.128)),
    "JPY": float(os.getenv("RATE_JPY", 0.0064)),
}

def usd_price(listing):
    return listing["price"] * DEFAULT_RATES.get(listing["currency"], 1.0)

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

def build_api_keyword(item):
    parts = ["Pop Mart", item.get("ip", ""), item.get("series", ""), item.get("keywords", "")]
    seen = set()
    words = []
    for part in parts:
        for token in str(part).replace("·", " ").split():
            clean = token.strip('"()')
            key = clean.lower()
            if clean and key not in seen and clean.upper() not in {"AND", "OR"}:
                seen.add(key)
                words.append(clean)
    return " ".join(words)

def extract_listing_items(response_payload):
    if isinstance(response_payload, list):
        return response_payload
    if not isinstance(response_payload, dict):
        return []
    for key in ("results", "items", "listings", "soldItems", "sold_items", "comps", "data"):
        value = response_payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_listing_items(value)
            if nested:
                return nested
    item = response_payload.get("item")
    if isinstance(item, list):
        return item
    if isinstance(item, dict):
        return [item]
    return []

def fetch_live_listings(item):
    """
    Remote marketplace API calls are disabled in the public repository.
    Production updates are generated by the private local eBay workflow under outputs/.
    """
    print(f"[INFO] Remote market API disabled for {item['sku']}. Use the local eBay cache workflow.")
    return [], "api_disabled"

def demo_listings(item):
    today = china_today_date()
    random.seed(item["sku"])
    multiplier = DEMO_MULTIPLIERS.get(item["sku"], random.uniform(1.4, 3.6))
    base = item["retail_price_usd"] * multiplier
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
    today = china_today_date()
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
    today = china_today_iso()
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

def load_existing_detail(file_path):
    if not file_path.exists():
        return None
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None

def load_sync_state(today):
    month = today[:7]
    default = {
        "month": month,
        "monthlyQuota": int(os.getenv("LOCAL_MARKET_MONTHLY_QUOTA", "50")),
        "requestsUsed": 0,
        "dailyRequests": {},
        "skuStatus": {},
    }
    if not SYNC_STATE_FILE.exists():
        return default
    try:
        with SYNC_STATE_FILE.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except Exception:
        return default
    if state.get("month") != month:
        return default
    state.setdefault("monthlyQuota", default["monthlyQuota"])
    state.setdefault("requestsUsed", 0)
    state.setdefault("dailyRequests", {})
    state.setdefault("skuStatus", {})
    return state

def save_sync_state(state):
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    with SYNC_STATE_FILE.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)

def daily_request_budget(state, today):
    monthly_quota = int(os.getenv("LOCAL_MARKET_MONTHLY_QUOTA", str(state.get("monthlyQuota", 50))))
    daily_budget = int(os.getenv("LOCAL_MARKET_DAILY_BUDGET", "1"))
    run_budget = int(os.getenv("LOCAL_MARKET_RUN_BUDGET", str(daily_budget)))
    used_month = int(state.get("requestsUsed", 0))
    used_today = int(state.get("dailyRequests", {}).get(today, 0))
    remaining_month = max(0, monthly_quota - used_month)
    remaining_today = max(0, daily_budget - used_today)
    return max(0, min(run_budget, remaining_today, remaining_month)), monthly_quota, remaining_month

def mark_api_request(state, sku, today, status):
    if status not in {"live", "rate_limited", "empty_response", "api_error"}:
        return
    state["requestsUsed"] = int(state.get("requestsUsed", 0)) + 1
    daily = state.setdefault("dailyRequests", {})
    daily[today] = int(daily.get(today, 0)) + 1
    sku_status = state.setdefault("skuStatus", {}).setdefault(sku, {})
    sku_status["lastAttemptAt"] = today
    sku_status["lastStatus"] = status
    if status == "live":
        sku_status["lastLiveAt"] = today

def normalize_tracking_item(raw_item):
    item = {}
    item["sku"] = raw_item.get("sku", raw_item.get("SKU"))
    if not item["sku"]:
        return None

    item["ip"] = raw_item.get("ip", raw_item.get("IP", "POP MART"))
    item["series"] = raw_item.get("series", raw_item.get("Series", "Unknown Series"))
    item["keywords"] = raw_item.get("keywords", raw_item.get("Keywords", ""))
    item["search_string"] = raw_item.get("search_string", raw_item.get("searchString", ""))
    if not item["search_string"]:
        item["search_string"] = f'"{item["ip"]}" AND "{item["series"]}" -box -card -preorder'

    item["negative_keywords"] = raw_item.get("negative_keywords", raw_item.get("negativeKeywords", ["box only", "card only"]))
    item["refresh_tier"] = raw_item.get("refresh_tier", raw_item.get("refreshTier", "weekly"))

    retail_val = raw_item.get("retail_price_usd", raw_item.get("retailPrice", raw_item.get("retail_price", 15.0)))
    item["retail_price_usd"] = float(retail_val)

    item["name_zh"] = raw_item.get("name_zh", raw_item.get("nameZh", raw_item.get("name_cn", item["series"])))
    item["name_en"] = raw_item.get("name_en", raw_item.get("nameEn", item["series"]))
    item["rarity"] = raw_item.get("rarity", raw_item.get("rarity_zh", raw_item.get("rarityZh", "常规款")))
    item["rarity_en"] = raw_item.get("rarity_en", raw_item.get("rarityEn", "Regular"))
    item["color"] = raw_item.get("color", "#6b38d4")
    item["image"] = raw_item.get("image", "")
    if "characters" in raw_item:
        item["characters"] = raw_item["characters"]
    return item

def select_items_for_live(items, state, today, budget):
    if budget <= 0:
        return set()
    sku_status = state.get("skuStatus", {})

    def sort_key(item):
        status = sku_status.get(item["sku"], {})
        tier_rank = 0 if item.get("refresh_tier") == "hot" else 1
        last_live = status.get("lastLiveAt") or status.get("lastAttemptAt") or "0000-00-00"
        existing = load_existing_detail(DATA_DIR / f"{item['sku']}.json") or {}
        data_source = existing.get("dataSource") or existing.get("marketData", {}).get("dataSource") or "demo"
        source_rank = 0 if data_source != "live" else 1
        return (source_rank, tier_rank, last_live, item["sku"])

    return {item["sku"] for item in sorted(items, key=sort_key)[:budget]}

def index_item_from_detail(detail):
    market = detail.get("marketData", {})
    return {
        "sku": detail["sku"],
        "ip": detail["ip"],
        "series": detail["series"],
        "name_zh": detail.get("name_zh", detail.get("series", "")),
        "name_en": detail.get("name_en", detail.get("series", "")),
        "rarity_zh": detail.get("rarity_zh", "常规款"),
        "rarity_en": detail.get("rarity_en", "Regular"),
        "color": detail.get("color", "#6b38d4"),
        "image": detail.get("image", ""),
        "searchString": detail.get("searchString", ""),
        "refreshTier": detail.get("refreshTier", "weekly"),
        "affiliateUrl": detail.get("affiliateUrl", ""),
        "retailPrice": detail.get("retailPrice", 0),
        "avgSoldPrice": market.get("fairMarketValue", market.get("medianSoldPrice", 0)),
        "medianSoldPrice": market.get("medianSoldPrice", market.get("fairMarketValue", 0)),
        "fairMarketValue": market.get("fairMarketValue", 0),
        "valuationMethod": market.get("valuationMethod", ""),
        "priceChange7d": market.get("priceChange7d", "+0.0%"),
        "roi": market.get("roi", 0),
        "riskScore": market.get("riskScore", 50),
        "totalSold": market.get("totalSold", 0),
        "signal_zh": market.get("signal_zh", "持有跟踪"),
        "signal_en": market.get("signal_en", "Track / hold"),
        "dataSource": market.get("dataSource", detail.get("dataSource", "demo")),
        "priceHistory": detail.get("priceHistory", []),
        "story": detail.get("story"),
        "characters": detail.get("characters"),
        "lastUpdated": detail.get("lastUpdated"),
    }

def detail_is_live(detail):
    if not detail:
        return False
    market = detail.get("marketData", {})
    return detail.get("dataSource") == "live" or market.get("dataSource") == "live"

def generate_default_story(item, today):
    ip = item.get("ip", "Pop Mart")
    series = item.get("series", item.get("name_en", ""))
    name = item.get("name_zh") or item.get("name_en", "")
    return {
        "year": today[:4],
        "tagline": f"{ip} {series} 极具升值潜力的二级市场标的。",
        "intro": f"作为 {ip} 矩阵的重要成员，{name} (系列: {series}) 在二级交易市场表现出极高的换手率与价格稳定性。",
        "philosophy": "该系列完美融合了当代街头艺术与盲盒收藏的独特性，色彩配置更具空间张力。",
        "detail": "当前 FMV（公允价值）由预清洗管线自动生成，使用三倍标准差和 IQR 算法剥离空卡/预售噪声，还原真实的潮玩资产价值。",
    }

def generate_default_characters(item):
    base_styles = ["经典核心款", "幻影午夜款", "流光原色款", "复古复刻款", "马戏巡游款", "异色隐藏款", "假日限定款", "典藏尊享款"]
    base_rarities = ["常规款", "常规款", "常规款", "常规款", "常规款", "概率稀缺", "主题款", "高热度"]
    ip_prefix = item.get("ip", "").split(" ")[0]
    series_prefix = item.get("series", "").split(" ")[0]
    chars = []
    for i in range(8):
        color = "#191c1d" if i == 5 else item.get("color", "#6b38d4")
        chars.append({"name": f"{ip_prefix} {series_prefix}·{base_styles[i]}", "rarity": base_rarities[i], "color": color})
    return chars

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
    today = china_today_iso()
    index = []
    sync_state = load_sync_state(today)
    request_budget, monthly_quota, remaining_month = daily_request_budget(sync_state, today)
    live_required = os.getenv("LIVE_DATA_REQUIRED", "").lower() in {"1", "true", "yes"}
    allow_demo = os.getenv("ALLOW_DEMO_DATA", "true").lower() not in {"0", "false", "no"}
    preserved = []
    failures = []

    dict_path = PROJECT_ROOT / "sku_dictionary.json"
    global TRACKING_ITEMS
    if dict_path.exists():
        try:
            with dict_path.open("r", encoding="utf-8") as handle:
                ext_data = json.load(handle)
                if isinstance(ext_data, list):
                    TRACKING_ITEMS = ext_data
                elif isinstance(ext_data, dict) and "items" in ext_data:
                    TRACKING_ITEMS = ext_data["items"]
                print(f"[SUCCESS] Loaded {len(TRACKING_ITEMS)} tracking SKU assets from {dict_path}")
        except Exception as e:
            print(f"[WARNING] Failed to load external dictionary: {e}. Fallback to internal items.")

    item_pairs = []
    for raw_item in TRACKING_ITEMS:
        if not isinstance(raw_item, dict):
            continue
        item = normalize_tracking_item(raw_item)
        if item:
            item_pairs.append((item, raw_item))
    normalized_items = [item for item, _ in item_pairs]
    selected_skus = select_items_for_live(normalized_items, sync_state, today, request_budget)
    sync_state["monthlyQuota"] = monthly_quota
    print(
        f"[QUOTA] month={sync_state['month']} used={sync_state.get('requestsUsed', 0)}/"
        f"{monthly_quota} remaining={remaining_month} daily_budget={request_budget} selected={len(selected_skus)}"
    )

    quota_stopped = False
    for item, raw_item in item_pairs:
        file_path = DATA_DIR / f"{item['sku']}.json"

        if quota_stopped or item["sku"] not in selected_skus:
            existing = load_existing_detail(file_path)
            if existing:
                index.append(index_item_from_detail(existing))
                continue
            if live_required and not allow_demo:
                failures.append(f"{item['sku']}:not_selected_no_existing_data")
                continue

        # 生产环境不再静默回滚到 demo。若 live 失败，只保留旧 live 数据。
        raw, source_status = fetch_live_listings(item)
        mark_api_request(sync_state, item["sku"], today, source_status)
        data_source = "live" if source_status == "live" and raw else "demo"
        if not raw:
            existing = load_existing_detail(file_path)
            if source_status == "rate_limited" and existing:
                index.append(index_item_from_detail(existing))
                print(f"[QUOTA] Preserved existing market data for {item['sku']} after remote API rate limit.")
                print("[STOP] Remote API rate limit reached. Stop remaining SKU requests to protect quota.")
                quota_stopped = True
                continue
            if live_required and detail_is_live(existing):
                preserved.append(item["sku"])
                index.append(index_item_from_detail(existing))
                print(f"[STALE] Preserved existing market data for {item['sku']} after {source_status}.")
                continue
            if live_required and not allow_demo:
                failures.append(f"{item['sku']}:{source_status}")
                if source_status == "rate_limited":
                    print("[STOP] Remote API rate limit reached. Stop remaining SKU requests to protect quota.")
                    break
                continue
            raw = demo_listings(item)
            data_source = "demo"
            
        metrics = aggregate(raw, item["retail_price_usd"], item.get("negative_keywords", []))
        if not metrics:
            continue
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
            "searchString": item["search_string"],
            "negativeKeywords": item["negative_keywords"],
            "refreshTier": item["refresh_tier"],
            "refreshIntervalHours": 24 if item["refresh_tier"] == "hot" else 168,
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
                "dataSource": data_source,
            },
            "priceHistory": history,
            "dataSource": data_source,
            "sources": ["remote-market-api"] if data_source == "live" else ["demo-secondary-market"],
            "story": raw_item.get("story") or generate_default_story(item, today),
            "characters": raw_item.get("characters") or generate_default_characters(item),
            "notes_zh": "价格为商品历史成交聚合结果，不构成投资建议。请综合手续费判断。",
            "notes_en": "Prices are API-aggregated metrics, not financial advice. Validate parameters before trading.",
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
                "searchString": item["search_string"],
                "refreshTier": item["refresh_tier"],
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
                "dataSource": data_source,
                "priceHistory": history,
                "story": raw_item.get("story") or generate_default_story(item, today),
                "characters": raw_item.get("characters") or generate_default_characters(item),
                "lastUpdated": today,
            }
        )

    with (DATA_DIR / "index.json").open("w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
    save_sync_state(sync_state)

    print(f"Generated {len(index)} tracked Pop Mart assets in {DATA_DIR}")
    if preserved:
        print(f"[STALE] Preserved {len(preserved)} SKU files because live fetch failed: {', '.join(preserved)}")
    if failures:
        raise SystemExit(f"Live data required, but no live or preserved data for: {', '.join(failures)}")

if __name__ == "__main__":
    main()
