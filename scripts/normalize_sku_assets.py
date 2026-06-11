import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PROJECT_ROOT / "public" / "assets" / "sku"
DICT_PATH = PROJECT_ROOT / "sku_dictionary.json"


def extension_for(path):
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


def main():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    renamed = []
    for path in sorted(ASSET_DIR.iterdir()):
        if not path.is_file():
            continue
        target = path.with_suffix(extension_for(path))
        if target == path:
            continue
        if target.exists():
            target.unlink()
        path.rename(target)
        renamed.append((path.name, target.name))

    files = {path.stem.upper(): path.name for path in ASSET_DIR.iterdir() if path.is_file()}
    with DICT_PATH.open("r", encoding="utf-8") as handle:
        items = json.load(handle)

    missing = []
    updated = 0
    for item in items:
        sku = str(item.get("sku", "")).upper()
        filename = files.get(sku)
        if not filename:
            missing.append(item.get("sku"))
            continue
        item["image"] = f"/assets/sku/{filename}"
        updated += 1

    with DICT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Renamed {len(renamed)} assets")
    print(f"Updated {updated} dictionary image fields")
    if missing:
        print("Missing:", ", ".join(missing))


if __name__ == "__main__":
    main()
