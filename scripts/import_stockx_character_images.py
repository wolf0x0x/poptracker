import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"
ASSET_ROOT = PROJECT_ROOT / "public" / "assets" / "stockx"

HEADER_RE = re.compile(r"^#\s+(.+?)\s+-\s+(.+?)\s+\((\d+)角色\)")
URL_RE = re.compile(r"https://images\.stockx\.com/images/[^\s]+")


def slugify(value):
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "image"


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
        if not line:
            continue
        header = HEADER_RE.match(line)
        if header:
            current = {
                "ip": header.group(1).strip(),
                "series": header.group(2).strip(),
                "expected": int(header.group(3)),
                "urls": [],
            }
            groups.append(current)
            continue
        for url in URL_RE.findall(line):
            if "{角色英文名}" in url:
                continue
            if current:
                current["urls"].append(url)
    return groups


def match_group_to_item(group, items):
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


def title_from_url(url):
    stem = Path(urllib.request.url2pathname(url.split("?")[0])).stem
    stem = re.sub(r"^Pop-Mart-", "", stem)
    stem = re.sub(r"-Figure$", "", stem)
    parts = [part for part in stem.split("-") if part]
    return " ".join(parts)


def character_name_from_url(url, group):
    title = title_from_url(url)
    prefix_parts = ["Pop Mart"]
    prefix_parts.extend(group["ip"].replace("SWEET BEAN", "Sweet Bean").split())
    prefix_parts.extend(group["series"].replace("%", "100").split())
    title_norm = title.lower()
    remove = []
    for part in prefix_parts:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "", part).lower()
        if cleaned:
            remove.append(cleaned)
    words = []
    for word in title.split():
        cleaned = re.sub(r"[^A-Za-z0-9]+", "", word).lower()
        if cleaned not in remove and cleaned not in {"figure", "mart", "pop"}:
            words.append(word)
    return " ".join(words) or title


def download(url, path_without_ext, force=False):
    for existing in path_without_ext.parent.glob(path_without_ext.name + ".*"):
        if existing.is_file() and not force:
            return existing, "cached"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://stockx.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read()
        ext = extension_for(data, response.headers.get("Content-Type", ""))
    path = path_without_ext.with_suffix(ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, "downloaded"


def merge_group(item, group, downloaded):
    if not downloaded:
        return
    existing = item.get("characters") if isinstance(item.get("characters"), list) else []
    characters = []
    for index, record in enumerate(downloaded):
        base = dict(existing[index]) if index < len(existing) and isinstance(existing[index], dict) else {}
        base.setdefault("name", character_name_from_url(record["url"], group))
        base.setdefault("rarity", "角色款" if index < group["expected"] - 1 else "隐藏/特别款")
        base.setdefault("color", item.get("color", "#6b38d4"))
        base["image"] = record["local"]
        base["source_url"] = record["url"]
        characters.append(base)
    item["characters"] = characters
    if downloaded:
        item["image"] = downloaded[0]["local"]


def main():
    parser = argparse.ArgumentParser(description="Import StockX character images into PopTracker local assets.")
    parser.add_argument("source", help="Text file containing grouped StockX image URLs.")
    parser.add_argument("--force", action="store_true", help="Re-download existing files.")
    args = parser.parse_args()

    text = Path(args.source).read_text(encoding="utf-8")
    groups = parse_groups(text)
    items = json.loads(DICT_PATH.read_text(encoding="utf-8"))

    report = {"groups": len(groups), "matched": [], "missing_groups": [], "download_errors": []}
    for group in groups:
        item = match_group_to_item(group, items)
        if not item:
            report["missing_groups"].append(group)
            continue
        sku = item["sku"]
        downloaded = []
        for index, url in enumerate(group["urls"], start=1):
            name = slugify(title_from_url(url))
            target = ASSET_ROOT / sku / f"{index:02d}-{name}"
            try:
                path, status = download(url, target, force=args.force)
                downloaded.append({"url": url, "local": "/" + str(path.relative_to(PROJECT_ROOT / "public")), "status": status})
                time.sleep(0.08)
            except Exception as exc:
                report["download_errors"].append({"sku": sku, "url": url, "error": str(exc)})
        merge_group(item, group, downloaded)
        report["matched"].append({"sku": sku, "series": item.get("series"), "expected": group["expected"], "urls": len(group["urls"]), "downloaded": len(downloaded)})

    DICT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = PROJECT_ROOT / "work" / "stockx_image_import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Groups: {report['groups']}")
    print(f"Matched: {len(report['matched'])}")
    print(f"Missing groups: {len(report['missing_groups'])}")
    print(f"Download errors: {len(report['download_errors'])}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
