import argparse
import hashlib
import json
import mimetypes
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"
ASSET_DIR = PROJECT_ROOT / "public" / "assets" / "sku"
REPORT_DIR = PROJECT_ROOT / "work"
REPORT_PATH = REPORT_DIR / "popmart_image_sync_report.json"

API_BASE = "https://prod-intl-api.popmart.com"
SEARCH_PATH = "/shop/v1/search"
AUTH_SALT = "W_ak^moHpMla"
CLIENT_KEY = "rmdxjisjk7gwykcix"

IMAGE_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
IMAGE_KEYS = ("image", "img", "pic", "cover", "banner", "logo", "url")
OFFICIAL_HOST_HINTS = (
    "popmart.com",
    "prod-out-res.popmart.com",
    "cdn-global",
    "us-static.popmart.com",
    "eu-static.popmart.com",
)


def compact_json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def md5(value):
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def sorted_payload(data, method):
    cleaned = {}
    for key in sorted(data):
        value = data[key]
        if method == "get" and value not in ("", None):
            cleaned[key] = str(value)
        elif method == "post":
            cleaned[key] = value
    return cleaned


def sign_payload(payload, timestamp, method="post"):
    return md5(compact_json(sorted_payload(payload, method)) + AUTH_SALT + str(timestamp))


def signed_headers(country="SG", namespace="eurasian", project_id="eude", referer_term="Labubu"):
    timestamp = int(time.time())
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.popmart.com",
        "Referer": f"https://www.popmart.com/sg/search/{urllib.parse.quote(referer_term)}",
        "X-Project-ID": project_id,
        "X-Device-OS-Type": "web",
        "ClientKey": CLIENT_KEY,
        "X-Sign": f"{md5(str(timestamp) + ',' + CLIENT_KEY)},{timestamp}",
        "Country": country,
        "X-Client-Country": country,
        "X-Client-Namespace": namespace,
        "Language": "en",
        "tz": "Asia/Shanghai",
        "TD-Session-Key": "",
        "Td-Session-Path": SEARCH_PATH,
        "Td-Session-Query": "",
        "Td-Session-Sign": "",
    }


def search_payload(term, page_size=20):
    payload = {
        "pageSize": page_size,
        "page": 1,
        "strategy": "",
        "term": term,
    }
    timestamp = int(time.time())
    payload["s"] = sign_payload(payload, timestamp, "post")
    payload["t"] = timestamp
    return payload


def request_json(url, payload, term):
    data = compact_json(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=signed_headers(referer_term=term),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", "ignore")
            return json.loads(raw), None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "ignore")
        return None, {
            "type": "http_error",
            "status": error.code,
            "body": body[:500],
        }
    except Exception as error:
        return None, {
            "type": "request_error",
            "message": str(error),
        }


def item_terms(item):
    parts = [
        item.get("name_en"),
        item.get("series"),
        item.get("ip"),
        item.get("keywords"),
    ]
    seen = set()
    terms = []
    for part in parts:
        if not part:
            continue
        value = " ".join(str(part).replace("THE MONSTERS", "Labubu").split())
        value = value.replace('"', "")
        if value and value.lower() not in seen:
            terms.append(value)
            seen.add(value.lower())
    return terms


def flatten_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from flatten_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten_strings(item)


def looks_like_image_url(value):
    lower = value.lower().split("?")[0]
    return (
        any(host in lower for host in OFFICIAL_HOST_HINTS)
        and (
            lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif"))
            or "/image" in lower
            or "/images" in lower
            or "oss" in lower
            or "res.popmart" in lower
        )
    )


def extract_image_urls(value):
    urls = []
    if isinstance(value, str):
        for match in IMAGE_URL_RE.findall(value):
            if looks_like_image_url(match):
                urls.append(match)
    elif isinstance(value, list):
        for item in value:
            urls.extend(extract_image_urls(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(hint in key_lower for hint in IMAGE_KEYS):
                urls.extend(extract_image_urls(item))
            elif isinstance(item, (dict, list)):
                urls.extend(extract_image_urls(item))
    deduped = []
    seen = set()
    for url in urls:
        cleaned = url.replace("\\u002F", "/").replace("\\/", "/")
        if cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped


def score_result(item, result):
    text = " ".join(flatten_strings(result)).lower()
    tokens = []
    for source in (item.get("name_en"), item.get("series"), item.get("ip")):
        for token in re.findall(r"[a-z0-9]+", str(source or "").lower()):
            if len(token) > 2 and token not in {"the", "and", "pop", "mart"}:
                tokens.append(token)
    return sum(1 for token in set(tokens) if token in text)


def candidate_images(item, payload):
    if not payload:
        return []
    results = []
    if isinstance(payload, dict):
        for key in ("list", "items", "records", "spus", "products", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                results.extend(value)
            elif isinstance(value, dict):
                results.extend(candidate_images(item, value))
    elif isinstance(payload, list):
        results.extend(payload)

    if not results:
        return extract_image_urls(payload)

    scored = sorted(
        ((score_result(item, result), result) for result in results),
        key=lambda pair: pair[0],
        reverse=True,
    )
    urls = []
    for score, result in scored:
        if score <= 0 and urls:
            continue
        urls.extend(extract_image_urls(result))
    return list(dict.fromkeys(urls))


def extension_from_response(url, headers):
    content_type = headers.get("Content-Type", "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(content_type) if content_type else None
    if guessed in (".jpe", ".jpeg"):
        return ".jpg"
    if guessed:
        return guessed
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def download_image(url, sku, dry_run=False):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": signed_headers()["User-Agent"],
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://www.popmart.com/",
        },
    )
    if dry_run:
        return None, "dry_run"
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "")
            if not content_type.lower().startswith("image/"):
                return None, f"non_image_content_type:{content_type}"
            ext = extension_from_response(url, response.headers)
            ASSET_DIR.mkdir(parents=True, exist_ok=True)
            path = ASSET_DIR / f"{sku.lower()}{ext}"
            path.write_bytes(data)
            return f"/assets/sku/{path.name}", None
    except Exception as error:
        return None, str(error)


def load_manual_payload(path):
    if not path:
        return None
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sync_images(limit=None, force=False, dry_run=False, manual_json=None):
    with DICT_PATH.open("r", encoding="utf-8") as handle:
        items = json.load(handle)

    manual_payload = load_manual_payload(manual_json)
    report = {
        "downloaded": [],
        "skipped": [],
        "missing": [],
        "errors": [],
    }

    targets = items[:limit] if limit else items
    for item in targets:
        sku = item.get("sku")
        if not sku:
            continue
        if item.get("image") and not force:
            report["skipped"].append({"sku": sku, "reason": "image already set"})
            continue

        payload = manual_payload
        api_error = None
        if payload is None:
            for term in item_terms(item):
                payload, api_error = request_json(API_BASE + SEARCH_PATH, search_payload(term), term)
                if payload:
                    break
                if api_error and api_error.get("status") == 471:
                    break

        urls = candidate_images(item, payload)
        if not urls:
            entry = {"sku": sku, "terms": item_terms(item), "reason": "no official image url found"}
            if api_error:
                entry["api_error"] = api_error
            report["missing"].append(entry)
            continue

        saved = None
        last_error = None
        for url in urls:
            saved, last_error = download_image(url, sku, dry_run=dry_run)
            if saved:
                item["image"] = saved
                report["downloaded"].append({"sku": sku, "image": saved, "source": url})
                break
        if not saved:
            report["errors"].append({"sku": sku, "source": urls[0], "error": last_error})

    if not dry_run:
        with DICT_PATH.open("w", encoding="utf-8") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Fetch official POP MART product images into local assets.")
    parser.add_argument("--limit", type=int, help="Only process the first N SKUs.")
    parser.add_argument("--force", action="store_true", help="Replace existing image fields.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write images or update dictionary.")
    parser.add_argument(
        "--manual-json",
        help="Use an exported POP MART search/detail JSON payload instead of calling the live API.",
    )
    args = parser.parse_args()
    report = sync_images(limit=args.limit, force=args.force, dry_run=args.dry_run, manual_json=args.manual_json)
    print(
        "Downloaded: {downloaded} | Skipped: {skipped} | Missing: {missing} | Errors: {errors}".format(
            downloaded=len(report["downloaded"]),
            skipped=len(report["skipped"]),
            missing=len(report["missing"]),
            errors=len(report["errors"]),
        )
    )
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
