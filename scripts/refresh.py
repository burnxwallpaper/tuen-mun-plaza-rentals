"""Refresh active rental listings for 屯門市廣場 + 屯門時代廣場 into data/listings.json.

Sources: Midland Realty (美聯物業) and Centaline (中原地產) only. Stdlib only.
index.html fetches data/listings.json; this script does not rewrite the page
or data/bookmarks.json.

Cards with unknown rent, non-positive rent, or rent above RENT_CAP_HKD are
omitted. A card above the cap is kept only when it matches a key in
data/bookmarks.json, so the page can still show it under the 書籤 filter.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "images"
DATA_PATH = ROOT / "data" / "listings.json"
BOOKMARKS_PATH = ROOT / "data" / "bookmarks.json"
# Keep a listing when its displayed rent is known and at most this many HKD.
RENT_CAP_HKD = 14001
HKT = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SCRAPED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Canonical estates tracked by this page.
ESTATES: list[dict[str, Any]] = [
    {
        "id": "tuen-mun-plaza",
        "name": "屯門市廣場",
        "short": "市廣場",
        "exclude_block_8": True,
        "midland_est_id": "E00091",
        "midland_list_url": (
            "https://www.midland.com.hk/zh-hk/list/rent/"
            "%E5%B1%AF%E9%96%80%E5%B8%82%E5%BB%A3%E5%A0%B4-E-E00091"
        ),
        "centanet_id": "3-NXLIIHSSHT",
        "centanet_list_url": (
            "https://hk.centanet.com/findproperty/list/rent/"
            "%E5%B1%AF%E9%96%80%E5%B8%82%E5%BB%A3%E5%A0%B4_3-NXLIIHSSHT"
        ),
    },
    {
        "id": "trend-plaza",
        "name": "屯門時代廣場",
        "short": "時代廣場",
        "exclude_block_8": False,
        "midland_est_id": "E00496",
        "midland_list_url": (
            "https://www.midland.com.hk/zh-hk/list/rent/"
            "%E6%99%82%E4%BB%A3%E5%BB%A3%E5%A0%B4-E-E00496"
        ),
        "centanet_id": "2-BGKEBPYEPS",
        "centanet_list_url": (
            "https://hk.centanet.com/findproperty/list/rent/"
            "%E6%99%82%E4%BB%A3%E5%BB%A3%E5%A0%B4_2-BGKEBPYEPS"
        ),
    },
]


def fetch(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
    req_headers = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read()
            cookie = resp.headers.get("Set-Cookie") or ""
            return resp.status, body, cookie
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Set-Cookie") or ""


def fetch_with_retries(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 4,
    pause: float = 1.5,
) -> tuple[int, bytes, str]:
    last = (0, b"", "")
    for attempt in range(1, attempts + 1):
        try:
            status, body, cookie = fetch(url, data=data, headers=headers)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"fetch retry {attempt}/{attempts} {exc}", flush=True)
            if attempt == attempts:
                raise
            time.sleep(pause * attempt)
            continue
        last = (status, body, cookie)
        if status in {429, 500, 502, 503, 504} and attempt < attempts:
            print(f"fetch HTTP {status} retry {attempt}/{attempts}", flush=True)
            time.sleep(pause * attempt)
            continue
        return last
    return last


CN_ROOMS = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5}


def room_from_text(raw: str | None) -> tuple[int | None, str]:
    if not raw:
        return None, "未列明"
    if "分間" in raw:
        return None, "分間房"
    if "開放式" in raw or "studio" in raw.lower():
        return 0, "開放式"
    digit = re.search(r"(\d+)\s*房", raw)
    if digit:
        count = int(digit.group(1))
        return count, f"{count}房"
    word = re.search(r"([一二兩三四])房", raw)
    if word:
        count = CN_ROOMS[word.group(1)]
        return count, f"{count}房"
    return None, "未列明"


def room_label(bedrooms: int | None, raw: str | None = None) -> str:
    if raw and "分間" in raw:
        return "分間房"
    if bedrooms is not None and bedrooms > 0:
        return f"{bedrooms}房"
    _count, label = room_from_text(raw)
    return label


def money(value: int | None) -> str:
    if value is None:
        return "租金未列明"
    return f"HK${value:,}"

def saleable_sqft(value: object) -> int | None:
    """Prefer integer 實用面積 in sq ft; ignore zero/invalid."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if value <= 0 or value != value:
            return None
        return int(round(value))
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        number = int(digits)
        return number if number > 0 else None
    return None


def rent_per_sqft(rent: int | None, area: int | None) -> float | None:
    if not isinstance(rent, int) or rent <= 0:
        return None
    if not isinstance(area, int) or area <= 0:
        return None
    return round(rent / area, 1)




def as_rent(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if value <= 0 or value != value:
            return None
        rounded = int(round(value))
        return rounded if abs(value - rounded) < 1e-6 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        number = int(digits)
        return number if number > 0 else None
    return None


def normalize_dt(value: object) -> str | None:
    """ISO datetime in Hong Kong time. Offset-less source values are treated as HKT."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HKT)
    return parsed.astimezone(HKT).replace(microsecond=0).isoformat()


def pick_bound(values: list[object], *, latest: bool) -> str | None:
    present = [value for value in values if isinstance(value, str) and value]
    if not present:
        return None
    return max(present) if latest else min(present)


def published_at_midland(url: str) -> str | None:
    status, body, _ = fetch(url, headers={"Accept-Language": "zh-HK"})
    if status != 200 or not body:
        return None
    text = body.decode("utf-8", "replace")
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    props = payload.get("props")
    if not isinstance(props, dict):
        return None
    page_props = props.get("pageProps")
    if not isinstance(page_props, dict):
        return None
    detail = page_props.get("propertyDetail")
    if not isinstance(detail, dict):
        return None
    return normalize_dt(detail.get("first_pub_date"))


def midland_token() -> str:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request("https://www.midland.com.hk/api/token", headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=45) as resp:
            cookie = resp.headers.get("Set-Cookie") or ""
            status = resp.status
    except urllib.error.HTTPError as exc:
        cookie = exc.headers.get("Set-Cookie") or ""
        status = exc.code
    match = re.search(r"token=([^;]+)", cookie)
    if not match:
        raise RuntimeError(f"Midland token missing (HTTP {status})")
    return urllib.parse.unquote(match.group(1))


def parse_midland(estate: dict[str, Any]) -> list[dict]:
    estate_name = str(estate["name"])
    token = midland_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Referer": "https://www.midland.com.hk/",
    }
    listings: list[dict] = []
    page = 1
    total = None
    while page <= 8:
        url = (
            "https://data.midland.com.hk/search/v2/properties?"
            + urllib.parse.urlencode(
                {
                    "ad": "true",
                    "lang": "zh-hk",
                    "currency": "HKD",
                    "unit": "feet",
                    "search_behavior": "normal",
                    "est_ids": str(estate["midland_est_id"]),
                    "tx_type": "L",
                    "limit": "24",
                    "page": str(page),
                }
            )
        )
        status, body, _ = fetch_with_retries(url, headers=headers)
        if status != 200:
            if listings:
                print(f"midland stop early HTTP {status} page {page}; keeping {len(listings)}", flush=True)
                break
            raise RuntimeError(f"Midland HTTP {status} page {page} ({estate_name})")
        payload = json.loads(body.decode("utf-8"))
        total = payload.get("count", total)
        rows = payload.get("result") or []
        if not rows:
            break
        for row in rows:
            if "L" not in (row.get("tx_type") or []) and row.get("rent") in (None, 0):
                continue
            rent = as_rent(row.get("rent"))
            if rent is None:
                continue
            api_estate = (row.get("estate") or {}).get("name") or estate_name
            phase = (row.get("phase") or {}).get("name") or ""
            building = (row.get("building") or {}).get("name") or ""
            floor = (row.get("floor_level") or {}).get("name") or ""
            flat = row.get("flat") or ""
            address = " ".join(part for part in [phase, building, floor, f"{flat}室" if flat else ""] if part)
            photos = row.get("outlook_photos") or []
            image = ""
            if photos and isinstance(photos[0], dict):
                image = photos[0].get("wan_doc_path") or ""
            if not image:
                image = row.get("outlook_wan_doc_path") or ""
            bedrooms = row.get("bedroom") if isinstance(row.get("bedroom"), int) else None
            detail_url = row.get("url_desc") or ""
            published_at = None
            if detail_url:
                try:
                    published_at = published_at_midland(detail_url)
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    print(f"midland date {row.get('serial_no')}: {exc}", flush=True)
                time.sleep(0.2)
            area = saleable_sqft(row.get("net_area"))
            listings.append(
                {
                    "source": "midland",
                    "source_name": "美聯物業",
                    "estate": estate_name,
                    "listing_id": row.get("serial_no") or "",
                    "title": f"{api_estate} {address}".strip(),
                    "address": address,
                    "rent_hkd": rent,
                    "area_sqft": area,
                    "rent_per_sqft": rent_per_sqft(rent, area),
                    "room_type": room_label(bedrooms),
                    "bedrooms": bedrooms,
                    "image_remote": image,
                    "url": detail_url,
                    "published_at": published_at,
                    "updated_at": normalize_dt(row.get("update_date")),
                    "scraped_at": SCRAPED_AT,
                }
            )
            if len(listings) % 10 == 0:
                print(f"midland {estate_name} dates {len(listings)}", flush=True)
        if total is not None and page * 24 >= int(total):
            break
        page += 1
        time.sleep(0.4)
    return listings


def parse_centanet(estate: dict[str, Any]) -> list[dict]:
    estate_name = str(estate["name"])
    listings: list[dict] = []
    offset = 0
    size = 24
    total = None
    while offset < 200:
        body = {
            "postType": "Rent",
            "sort": "Ranking",
            "order": "Ascending",
            "size": size,
            "displayTextStyle": "WebResultList",
            "offset": offset,
            "pageSource": "search",
            "hmas": [],
            "mtrs": [],
            "primarySchoolNets": [],
            "markets": [],
            "universities": [],
            "bigestAndEstate": [str(estate["centanet_id"])],
            "phaseAndEstate": [],
        }
        status, raw, _ = fetch_with_retries(
            "https://hk.centanet.com/findproperty/api/Post/Search",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://hk.centanet.com",
                "Referer": "https://hk.centanet.com/findproperty/list/rent/",
            },
        )
        if status != 200:
            if listings:
                print(f"centanet stop early HTTP {status} offset {offset}; keeping {len(listings)}", flush=True)
                break
            raise RuntimeError(f"Centaline HTTP {status} offset {offset} ({estate_name})")
        payload = json.loads(raw.decode("utf-8"))
        total = payload.get("count", total)
        rows = payload.get("data") or []
        if not rows:
            break
        for row in rows:
            rent = as_rent(row.get("rentPrice"))
            if rent is None:
                price_info = row.get("priceInfo") or {}
                rent = as_rent(price_info.get("rent"))
            if rent is None:
                continue
            display = (row.get("displayText") or {}).get("addr") or {}
            line1 = display.get("line1") or estate_name
            line2 = display.get("line2") or ""
            bedrooms = row.get("bedroomCount") if isinstance(row.get("bedroomCount"), int) else None
            picture = row.get("picture") or {}
            image = picture.get("thumbnailPath") or row.get("thumbnail") or ""
            detail = row.get("detailUrl") or ""
            if detail and "theme=" not in detail:
                detail = detail + ("&" if "?" in detail else "?") + "theme=rent"
            area = saleable_sqft(row.get("nSize"))
            if area is None:
                area_info = row.get("areaInfo") or {}
                if isinstance(area_info, dict):
                    area = saleable_sqft(area_info.get("nSize"))
            title_tail = line1
            for label in (estate_name, "時代廣場", "屯門市廣場"):
                title_tail = title_tail.replace(label, "").strip()
            listings.append(
                {
                    "source": "centanet",
                    "source_name": "中原地產",
                    "estate": estate_name,
                    "listing_id": row.get("refNo") or row.get("id") or "",
                    "title": line1,
                    "address": " ".join(part for part in [title_tail, line2] if part),
                    "rent_hkd": rent,
                    "area_sqft": area,
                    "rent_per_sqft": rent_per_sqft(rent, area),
                    "room_type": room_label(bedrooms, line2),
                    "bedrooms": bedrooms,
                    "image_remote": image,
                    "url": detail,
                    "published_at": normalize_dt(row.get("publishDate")),
                    "updated_at": normalize_dt(row.get("updateDate")),
                    "scraped_at": SCRAPED_AT,
                }
            )
        offset += size
        if total is not None and offset >= int(total):
            break
        time.sleep(0.4)
    return listings


BLOCK_8_RE = re.compile(
    r"(?<!\d)8\s*座|第\s*8\s*座|第八\s*座|Block\s*0*8\b",
    re.IGNORECASE,
)


def is_block_8(listing: dict) -> bool:
    """True when title/address clearly refers to 8座 (not 18座 etc.)."""
    blob = f"{listing.get('title') or ''} {listing.get('address') or ''}"
    return bool(BLOCK_8_RE.search(blob))


def exclude_tmtp_block_8(listings: list[dict]) -> tuple[list[dict], int]:
    """Drop 8座 only for 屯門市廣場. Trend Plaza keeps all blocks."""
    kept: list[dict] = []
    removed = 0
    for listing in listings:
        if listing.get("estate") == "屯門市廣場" and is_block_8(listing):
            removed += 1
            continue
        kept.append(listing)
    return kept, removed


def unit_key(listing: dict) -> str | None:
    text = f"{listing.get('title') or ''} {listing.get('address') or ''}"
    block = re.search(r"(\d+)\s*座", text) or re.search(r"([A-Ea-e])\s*座", text)
    flat = re.search(r"([A-Za-z])\s*室", text)
    floor = re.search(r"(極高層|高層|中層|低層)", text)
    if not block or not flat or not floor:
        return None
    bedrooms = listing.get("bedrooms")
    if not isinstance(bedrooms, int):
        return None
    estate = listing.get("estate") or ""
    return (
        f"{estate}|{block.group(1).upper()}|{floor.group(1)}|"
        f"{flat.group(1).upper()}|{bedrooms}"
    )


def dedupe(listings: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for listing in listings:
        key = unit_key(listing)
        if key is None:
            loose.append(listing)
            continue
        groups.setdefault(key, []).append(listing)
    merged: list[dict] = []
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        rents = [item["rent_hkd"] for item in group if isinstance(item.get("rent_hkd"), int)]
        if not rents:
            merged.extend(group)
            continue
        low, high = min(rents), max(rents)
        if high > low * 1.15:
            merged.extend(group)
            continue
        primary = dict(group[0])
        primary["published_at"] = pick_bound(
            [item.get("published_at") for item in group], latest=False
        )
        primary["updated_at"] = pick_bound(
            [item.get("updated_at") for item in group], latest=True
        )
        if not isinstance(primary.get("area_sqft"), int) or primary.get("area_sqft") <= 0:
            for item in group[1:]:
                area = item.get("area_sqft")
                if isinstance(area, int) and area > 0:
                    primary["area_sqft"] = area
                    primary["rent_per_sqft"] = rent_per_sqft(primary.get("rent_hkd"), area)
                    break
        else:
            primary["rent_per_sqft"] = rent_per_sqft(
                primary.get("rent_hkd"), primary.get("area_sqft")
            )
        primary["also_listed"] = [
            {
                "source": item["source"],
                "source_name": item["source_name"],
                "listing_id": item["listing_id"],
                "url": item["url"],
                "rent_hkd": item["rent_hkd"],
            }
            for item in group[1:]
        ]
        primary["dedupe_key"] = key
        merged.append(primary)
    merged.extend(loose)
    merged.sort(key=lambda item: (item.get("rent_hkd") is None, item.get("rent_hkd") or 0, item["source"]))
    return merged


def cache_images(listings: list[dict]) -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    for index, listing in enumerate(listings, start=1):
        remote = listing.get("image_remote") or ""
        listing_id = re.sub(r"[^A-Za-z0-9_-]", "", listing.get("listing_id") or str(index))
        filename = f"{listing['source']}-{listing_id}.jpg"
        dest = IMAGES / filename
        listing["image"] = f"images/{filename}"
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        if not remote:
            listing["image"] = ""
            continue
        status, body, _ = fetch(remote, headers={"Referer": listing.get("url") or ""})
        if status == 200 and len(body) > 500:
            dest.write_bytes(body)
        else:
            listing["image"] = ""
        if index % 8 == 0:
            time.sleep(0.3)


def appearance_counts(listings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for listing in listings:
        name = str(listing.get("source_name") or "")
        counts[name] = counts.get(name, 0) + 1
        for extra in listing.get("also_listed") or []:
            extra_name = str(extra.get("source_name") or "")
            counts[extra_name] = counts.get(extra_name, 0) + 1
    return counts


def primary_counts(listings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for listing in listings:
        name = str(listing.get("source_name") or "")
        counts[name] = counts.get(name, 0) + 1
    return counts


def estate_counts(listings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for listing in listings:
        name = str(listing.get("estate") or "未列明")
        counts[name] = counts.get(name, 0) + 1
    return counts


def positive_rent(listing: dict) -> int | None:
    rent = listing.get("rent_hkd")
    if isinstance(rent, bool) or not isinstance(rent, int) or rent <= 0:
        return None
    return rent


def normalize_url(url: object) -> str:
    """Listing URL without query or fragment. Host is lowercased; path is decoded."""
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""
    parts = urllib.parse.urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.split("#", 1)[0].split("?", 1)[0]
    path = urllib.parse.unquote(parts.path).rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def centanet_ref(source: object, listing_id: object, url: object) -> str:
    href = url if isinstance(url, str) else ""
    is_centanet = source == "centanet" or "centanet.com" in href.lower()
    if not is_centanet:
        return ""
    if isinstance(listing_id, str) and re.fullmatch(r"[A-Za-z]{2,4}\d{3,}", listing_id.strip()):
        return listing_id.strip().upper()
    decoded = urllib.parse.unquote(href)
    match = re.search(r"_([A-Za-z]{2,4}\d{3,})(?:[/?#]|$)", decoded)
    if match:
        return match.group(1).upper()
    return ""


def listing_bookmark_keys(listing: dict) -> set[str]:
    """Keys that can match data/bookmarks.json for this card, including merged sources."""
    keys: set[str] = set()

    def add(source: object, listing_id: object, url: object) -> None:
        ref = centanet_ref(source, listing_id, url)
        if ref:
            keys.add(ref)
        norm = normalize_url(url)
        if norm:
            keys.add(norm)

    add(listing.get("source"), listing.get("listing_id"), listing.get("url"))
    for extra in listing.get("also_listed") or []:
        if isinstance(extra, dict):
            add(extra.get("source"), extra.get("listing_id"), extra.get("url"))
    return keys


def normalize_bookmark_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z]{2,4}\d{3,}", text):
        return text.upper()
    if text.lower().startswith("http://") or text.lower().startswith("https://"):
        return normalize_url(text)
    return text


def load_bookmark_keys() -> set[str]:
    """Repo defaults only. Visitor localStorage overlays are applied in the browser."""
    if not BOOKMARKS_PATH.exists():
        return set()
    try:
        payload = json.loads(BOOKMARKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw = payload.get("keys") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return set()
    return {key for item in raw if (key := normalize_bookmark_key(item))}


def apply_rent_cap(
    listings: list[dict], bookmark_keys: set[str] | None = None
) -> tuple[list[dict], dict[str, int]]:
    """Drop unknown rents and rents above RENT_CAP_HKD.

    Bookmarked over-cap cards stay in the file so index.html can show them
    under 書籤 only. Unknown rent is always dropped.
    """
    if bookmark_keys is None:
        bookmark_keys = load_bookmark_keys()
    kept: list[dict] = []
    stats = {"over_cap": 0, "unknown_rent": 0, "kept_bookmarked_over_cap": 0}
    for listing in listings:
        rent = positive_rent(listing)
        if rent is None:
            stats["unknown_rent"] += 1
            continue
        if rent <= RENT_CAP_HKD:
            kept.append(listing)
            continue
        if listing_bookmark_keys(listing) & bookmark_keys:
            stats["kept_bookmarked_over_cap"] += 1
            kept.append(listing)
            continue
        stats["over_cap"] += 1
    return kept, stats


def write_data(
    listings: list[dict],
    *,
    excluded_over_cap: int = 0,
    excluded_unknown_rent: int = 0,
) -> None:
    payload = {
        "meta": {
            "updated_at": datetime.now(HKT).replace(microsecond=0).isoformat(),
            "search_key": "／".join(str(item["name"]) for item in ESTATES),
            "card_count": len(listings),
            "rent_cap_hkd": RENT_CAP_HKD,
            "excluded_over_cap": excluded_over_cap,
            "excluded_unknown_rent": excluded_unknown_rent,
            "estate_counts": estate_counts(listings),
            "source_counts": appearance_counts(listings),
            "primary_counts": primary_counts(listings),
            "estates": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "short": item["short"],
                    "exclude_block_8": bool(item.get("exclude_block_8")),
                }
                for item in ESTATES
            ],
            "sources": [
                {
                    "id": "midland",
                    "name": "美聯物業",
                    "url": ESTATES[0]["midland_list_url"],
                },
                {
                    "id": "centanet",
                    "name": "中原地產",
                    "url": ESTATES[0]["centanet_list_url"],
                },
            ],
        },
        "listings": listings,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    errors: list[str] = []
    collected: list[dict] = []
    parsers = (
        ("midland", parse_midland),
        ("centanet", parse_centanet),
    )
    for estate in ESTATES:
        estate_name = str(estate["name"])
        for source_name, parser in parsers:
            label = f"{source_name}/{estate_name}"
            try:
                rows = parser(estate)
                print(f"{label}: {len(rows)}")
                collected.extend(rows)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                print(f"{label} FAILED: {exc}")
    collected, removed_block8 = exclude_tmtp_block_8(collected)
    print(f"excluded TMTP block 8: {removed_block8}", flush=True)
    listings = dedupe(collected)
    listings, removed_after = exclude_tmtp_block_8(listings)
    if removed_after:
        print(f"excluded TMTP block 8 after dedupe: {removed_after}", flush=True)
    listings, cap_stats = apply_rent_cap(listings)
    print(
        f"rent cap {RENT_CAP_HKD}: dropped over {cap_stats['over_cap']}, "
        f"dropped unknown {cap_stats['unknown_rent']}, "
        f"kept bookmarked over {cap_stats['kept_bookmarked_over_cap']}",
        flush=True,
    )
    cache_images(listings)
    write_data(
        listings,
        excluded_over_cap=cap_stats["over_cap"],
        excluded_unknown_rent=cap_stats["unknown_rent"],
    )
    print(
        f"cards {len(listings)} errors {errors} "
        f"tmtp_block8_removed {removed_block8 + removed_after}"
    )
    print(f"estate_counts {estate_counts(listings)}", flush=True)
    for source in ("midland", "centanet"):
        rows = [item for item in listings if item.get("source") == source]
        published = sum(1 for item in rows if item.get("published_at"))
        updated = sum(1 for item in rows if item.get("updated_at"))
        with_area = sum(
            1 for item in rows if isinstance(item.get("area_sqft"), int) and item["area_sqft"] > 0
        )
        print(f"dates {source}: {published} published_at, {updated} updated_at, {len(rows)} cards")
        print(f"area {source}: {with_area}/{len(rows)} with area_sqft")


if __name__ == "__main__":
    main()
