import argparse
import json
import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"
ASSET_ROOT = PROJECT_ROOT / "public" / "assets" / "stockx"


def slugify(value):
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "character"


def image_extension(path):
    header = path.read_bytes()[:16]
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(bytes.fromhex("ffd8ff")):
        return ".jpg"
    if header.startswith(bytes.fromhex("89504e470d0a1a0a")):
        return ".png"
    if header[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    return path.suffix.lower()


def parse_filename(path):
    stem = path.stem
    match = re.match(r"^([A-Z0-9]+(?:-[A-Z0-9]+)+)_(.+)$", stem)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def existing_character(item, index, char_name):
    characters = item.get("characters")
    if isinstance(characters, list) and index < len(characters) and isinstance(characters[index], dict):
        result = dict(characters[index])
    else:
        result = {}
    result.setdefault("name", char_name.replace("-", " "))
    result.setdefault("rarity", "角色款")
    result.setdefault("color", item.get("color", "#6b38d4"))
    return result


def main():
    parser = argparse.ArgumentParser(description="Import externally downloaded StockX character images.")
    parser.add_argument("source_dir", help="Folder containing files named SKU_Character.jpg/png/webp/avif.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.exists():
        raise SystemExit(f"Source folder does not exist: {source_dir}")

    with DICT_PATH.open("r", encoding="utf-8") as handle:
        items = json.load(handle)
    by_sku = {item["sku"]: item for item in items}

    grouped = {}
    skipped = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file():
            continue
        sku, char_name = parse_filename(path)
        if not sku or sku not in by_sku:
            skipped.append(str(path))
            continue
        grouped.setdefault(sku, []).append((char_name, path))

    imported = []
    for sku, records in grouped.items():
        item = by_sku[sku]
        characters = []
        for index, (char_name, src) in enumerate(records):
            ext = image_extension(src)
            target_dir = ASSET_ROOT / sku
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{index + 1:02d}-{slugify(char_name)}{ext}"
            shutil.copyfile(src, target)
            character = existing_character(item, index, char_name)
            character["image"] = "/" + str(target.relative_to(PROJECT_ROOT / "public"))
            characters.append(character)
            imported.append({"sku": sku, "character": char_name, "image": character["image"]})
        if characters:
            item["characters"] = characters
            item["image"] = characters[0]["image"]

    with DICT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    report = {
        "source_dir": str(source_dir),
        "imported": imported,
        "skipped": skipped,
        "sku_count": len(grouped),
        "image_count": len(imported),
    }
    report_path = PROJECT_ROOT / "work" / "downloaded_character_image_import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Imported images: {len(imported)}")
    print(f"Matched SKUs: {len(grouped)}")
    print(f"Skipped files: {len(skipped)}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
