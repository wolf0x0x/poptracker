import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"
ASSET_ROOT = PROJECT_ROOT / "public" / "assets" / "characters"
REPORT_PATH = PROJECT_ROOT / "work" / "bing_character_image_report.json"

HEADER_RE = re.compile(r"^#\s+(.+?)\s+-\s+(.+?)\s+\((\d+)角色\)")
URL_RE = re.compile(r"https://images\.stockx\.com/images/[^\s]+")


def slugify(value):
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "image"


def normalize(value):
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def extension_for(data, content_type=""):
    header = data[:16]
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(bytes.fromhex("ffd8ff")):
        return ".jpg"
    if header.startswith(bytes.fromhex("89504e470d0a1a0a")):
        return ".png"
    if header[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "avif" in content_type:
        return ".avif"
    return ".jpg"


def parse_groups(text):
    groups = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        header = HEADER_RE.match(line)
        if header:
            current = {
                "ip": header.group(1).strip(),
                "series": header.group(2).strip(),
                "expected": int(header.group(3)),
                "characters": [],
            }
            groups.append(current)
            continue
        for url in URL_RE.findall(line):
            if "{角色英文名}" in url or not current:
                continue
            current["characters"].append(character_name_from_stockx_url(url, current))
    return groups


def groups_from_dictionary(items):
    groups = []
    for item in items:
        characters = item.get("characters")
        if not isinstance(characters, list) or not characters:
            continue
        names = []
        for character in characters:
            if isinstance(character, dict) and character.get("name"):
                names.append(str(character["name"]))
        if not names:
            continue
        groups.append({
            "ip": item.get("ip", ""),
            "series": item.get("series") or item.get("name_en") or item.get("sku"),
            "expected": len(names),
            "characters": names,
            "sku": item.get("sku"),
        })
    return groups


def character_name_from_stockx_url(url, group):
    stem = Path(urllib.parse.urlparse(url).path).stem
    stem = re.sub(r"^Pop-Mart-", "", stem)
    stem = re.sub(r"-Figure$", "", stem)
    title = " ".join(part for part in stem.split("-") if part)
    remove = {"pop", "mart", "figure"}
    for part in [*group["ip"].split(), *group["series"].replace("%", "100").split()]:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "", part).lower()
        if cleaned:
            remove.add(cleaned)
    words = []
    for word in title.split():
        cleaned = re.sub(r"[^A-Za-z0-9]+", "", word).lower()
        if cleaned not in remove:
            words.append(word)
    return " ".join(words) or title


def match_group_to_item(group, items):
    if group.get("sku"):
        for item in items:
            if item.get("sku") == group["sku"]:
                return item
    group_series = normalize(group["series"])
    group_ip = normalize(group["ip"])
    best = None
    best_score = -1
    for item in items:
        series = normalize(item.get("series", ""))
        name_en = normalize(item.get("name_en", ""))
        ip = normalize(item.get("ip", ""))
        score = 0
        if group_series == series:
            score += 10
        elif group_series and (group_series in series or series in group_series):
            score += 6
        elif group_series and group_series in name_en:
            score += 5
        if group_ip and (group_ip in ip or ip in group_ip or group_ip in name_en):
            score += 3
        if score > best_score:
            best = item
            best_score = score
    return best if best_score >= 5 else None


def bing_image_search(query, key, market="en-US"):
    params = urllib.parse.urlencode({
        "q": query,
        "count": 8,
        "imageType": "Photo",
        "safeSearch": "Moderate",
        "mkt": market,
    })
    request = urllib.request.Request(
        f"https://api.bing.microsoft.com/v7.0/images/search?{params}",
        headers={"Ocp-Apim-Subscription-Key": key},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("value", [])


def download_image(url, target_without_ext):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    if len(data) < 5000:
        raise ValueError("image too small")
    ext = extension_for(data, content_type)
    target = target_without_ext.with_suffix(ext)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def merge_character(item, index, character_name, local_path):
    existing = item.get("characters") if isinstance(item.get("characters"), list) else []
    if index < len(existing) and isinstance(existing[index], dict):
        character = dict(existing[index])
    else:
        character = {
            "name": character_name,
            "rarity": "角色款",
            "color": item.get("color", "#6b38d4"),
        }
    character.setdefault("name", character_name)
    character.setdefault("rarity", "角色款")
    character.setdefault("color", item.get("color", "#6b38d4"))
    character["image"] = "/" + str(local_path.relative_to(PROJECT_ROOT / "public"))
    return character


def main():
    parser = argparse.ArgumentParser(description="Search Bing Images for Pop Mart character images and import them locally.")
    parser.add_argument("source", help="Text file containing grouped character names or StockX URL list.")
    parser.add_argument("--limit", type=int, help="Limit number of groups while testing.")
    parser.add_argument("--market", default=os.getenv("BING_IMAGE_MARKET", "en-US"))
    args = parser.parse_args()

    key = os.getenv("BING_IMAGE_SEARCH_KEY")
    if not key:
        raise SystemExit("Missing BING_IMAGE_SEARCH_KEY environment variable")

    items = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    groups = parse_groups(Path(args.source).read_text(encoding="utf-8"))
    if not groups:
        groups = groups_from_dictionary(items)
    if args.limit:
        groups = groups[: args.limit]

    report = {"matched": [], "missing_groups": [], "downloaded": [], "failed": []}
    for group in groups:
        item = match_group_to_item(group, items)
        if not item:
            report["missing_groups"].append(group)
            continue
        sku = item["sku"]
        characters = []
        for index, character_name in enumerate(group["characters"]):
            query = f"Pop Mart {item.get('name_en') or group['series']} {character_name} Figure"
            try:
                results = bing_image_search(query, key, args.market)
                if not results:
                    raise ValueError("no image results")
                last_error = None
                local_path = None
                for result in results:
                    url = result.get("contentUrl") or result.get("thumbnailUrl")
                    if not url:
                        continue
                    try:
                        local_path = download_image(url, ASSET_ROOT / sku / f"{index + 1:02d}-{slugify(character_name)}")
                        break
                    except Exception as exc:
                        last_error = str(exc)
                if not local_path:
                    raise ValueError(last_error or "no downloadable image")
                characters.append(merge_character(item, index, character_name, local_path))
                report["downloaded"].append({"sku": sku, "character": character_name, "query": query, "image": "/" + str(local_path.relative_to(PROJECT_ROOT / "public"))})
            except Exception as exc:
                report["failed"].append({"sku": sku, "character": character_name, "query": query, "error": str(exc)})
            time.sleep(0.25)
        if characters:
            item["characters"] = characters
            item["image"] = characters[0]["image"]
        report["matched"].append({"sku": sku, "series": item.get("series"), "characters": len(group["characters"]), "downloaded": len(characters)})

    DICT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Matched groups: {len(report['matched'])}")
    print(f"Downloaded: {len(report['downloaded'])}")
    print(f"Failed: {len(report['failed'])}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
