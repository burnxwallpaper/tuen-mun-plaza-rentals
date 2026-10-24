"""Refresh active rental listings for 屯門市廣場 + 屯門時代廣場 into data/listings.json.

Sources: 28hse, Midland Realty, Centaline, Ricacorp (利嘉閣). Stdlib only.
index.html fetches data/listings.json; this script does not rewrite the page.
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
        "hse28_url": "https://www.28hse.com/rent/a3/dg48/c4433",
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
        "ricacorp_url": (
            "https://www.ricacorp.com/zh-hk/property/list/rent/"
            "%E5%B1%AF%E9%96%80%E5%B8%82%E5%BB%A3%E5%A0%B4-bigest-"
            "%E5%B1%AF%E9%96%80%E5%B8%82%E4%B8%AD%E5%BF%83-hma-hk"
        ),
    },
    {
        "id": "trend-plaza",
        "name": "屯門時代廣場",
        "short": "時代廣場",
        "exclude_block_8": False,
        "hse28_url": "https://www.28hse.com/rent/a3/dg48/c4458",
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
        "ricacorp_url": (
            "https://www.ricacorp.com/zh-hk/property/list/rent/"
            + urllib.parse.quote("時代廣場-estate-屯門市中心-hma-hk")
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


def dates_28hse(url: str) -> tuple[str | None, str | None]:
    status, body, _ = fetch(url, headers={"Accept-Language": "zh-HK"})
    if status != 200 or not body:
        return None, None
    text = body.decode("utf-8", "replace")
    published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', text)
    updated = re.search(r'"dateModified"\s*:\s*"([^"]+)"', text)
    return (
        normalize_dt(published.group(1) if published else None),
        normalize_dt(updated.group(1) if updated else None),
    )


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


def parse_28hse(estate: dict[str, Any]) -> list[dict]:
    estate_name = str(estate["name"])
    status, body, _ = fetch(str(estate["hse28_url"]))
    if status != 200:
        raise RuntimeError(f"28hse HTTP {status} ({estate_name})")
    text = body.decode("utf-8", errors="replace")
    count_match = re.search(r"共有\s*(\d+)\s*個放租樓盤", text)
    declared = int(count_match.group(1)) if count_match else None
    parts = text.split('<div class="item property_item "')[1:]
    listings: list[dict] = []
    for part in parts:
        url_match = re.search(r'href="(https://www\.28hse\.com/rent/apartment/property-(\d+))"', part)
        if not url_match:
            continue
        img_match = re.search(r'https://i\d\.28hse\.com/[^"\s]+', part)
        rent_match = re.search(r"租\s*\$\s*([\d,]+)\s*元", part)
        plain = re.sub(r"<[^>]+>", "\n", part)
        lines = [re.sub(r"\s+", " ", line).strip() for line in plain.splitlines()]
        lines = [line for line in lines if line and line not in {"|", ">"}]
        address = next((line for line in lines if re.search(r"\d+座", line)), "")
        skip = re.compile(r"^(租\s*\$[\d,]+\s*元|\d+|置頂|黃金|屯門|屯門市廣場|私人屋苑|信和|美聯物業|實用面積:.*|@[\d.]+\s*元)$")
        candidates = [line for line in lines if not skip.match(line) and "平方" not in line]
        room_only = re.compile(r"^\d+\s*房(\s*,\s*\d+\s*浴室)?$")
        titled = [
            line
            for line in candidates
            if ("房" in line or "盤" in line or "租" in line) and not room_only.match(line)
        ]
        title = (titled[0] if titled else "") or f"{estate_name} {address}".strip()
        bedrooms, room = room_from_text(" ".join(lines))
        image = img_match.group(0) if img_match else ""
        if image.endswith("_thumb.jpg"):
            image = image.replace("_thumb.jpg", "_large.jpg")
        rent = int(rent_match.group(1).replace(",", "")) if rent_match else None
        area_match = re.search(r"實用面積\s*[:：]?\s*([\d,]+)\s*呎", plain)
        if not area_match:
            area_match = re.search(r"實用面積\s*[:：]?\s*([\d,]+)\s*呎", part)
        area = saleable_sqft(area_match.group(1) if area_match else None)
        detail_url = url_match.group(1)
        published_at = None
        updated_at = None
        try:
            published_at, updated_at = dates_28hse(detail_url)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"28hse date {url_match.group(2)}: {exc}", flush=True)
        time.sleep(0.25)
        listings.append(
            {
                "source": "28hse",
                "source_name": "28Hse",
                "estate": estate_name,
                "listing_id": url_match.group(2),
                "title": title or f"{estate_name} {address}".strip(),
                "address": address,
                "rent_hkd": rent,
                "area_sqft": area,
                "rent_per_sqft": rent_per_sqft(rent, area),
                "room_type": room,
                "bedrooms": bedrooms,
                "image_remote": image,
                "url": detail_url,
                "published_at": published_at,
                "updated_at": updated_at,
                "scraped_at": SCRAPED_AT,
            }
        )
    if declared is not None and len(listings) != declared:
        print(f"28hse {estate_name} declared {declared}, parsed {len(listings)}")
    return listings


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


def _rica_transfer_state(html: str) -> dict | None:
    match = re.search(r"(\{&q;LAZYIMGUNIVERSAL_SERVERKEY_logo-icon.*)", html, re.S)
    if not match:
        return None
    decoded = (
        match.group(1)
        .replace("&q;", '"')
        .replace("&a;", "&")
        .replace("&s;", "'")
        .replace("&l;", "<")
        .replace("&g;", ">")
    )
    try:
        payload, _end = json.JSONDecoder().raw_decode(decoded)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _rica_ad_dates(html: str) -> dict[str, str]:
    """Map postNo -> published_at (HKT) from 廣告日期 on the list page."""
    out: dict[str, str] = {}
    pattern = re.compile(
        r"廣告日期</span><span[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</span>.*?"
        r"物業編號</span><span[^>]*>\s*([A-Z]{2}\d{8})",
        re.S,
    )
    for match in pattern.finditer(html):
        day, month, year = match.group(1).split("/")
        out[match.group(2)] = normalize_dt(f"{year}-{month}-{day}T00:00:00+08:00")
    return out


def _rica_ms_to_iso(value: object) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        try:
            return (
                datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                .astimezone(HKT)
                .replace(microsecond=0)
                .isoformat()
            )
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _rica_flat(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    match = re.search(r"([A-Za-z])\s*$", raw.strip()) or re.search(r"Flat\s*([A-Za-z])", raw, re.I)
    if match:
        return f"{match.group(1).upper()}室"
    return raw.strip()


def parse_ricacorp(estate: dict[str, Any]) -> list[dict]:
    """Scrape Ricacorp SSR transfer-state for one estate."""
    estate_name = str(estate["name"])
    list_url = str(estate["ricacorp_url"])
    status, body, _ = fetch_with_retries(
        list_url,
        headers={"Accept-Language": "zh-HK", "Accept": "text/html"},
    )
    if status != 200 or not body:
        raise RuntimeError(f"Ricacorp HTTP {status} ({estate_name})")
    html = body.decode("utf-8", "replace")
    state = _rica_transfer_state(html)
    if not state:
        raise RuntimeError("Ricacorp transfer-state missing")
    rows = state.get("POSTS") or []
    if not isinstance(rows, list):
        raise RuntimeError("Ricacorp POSTS missing")
    total = state.get("POSTSTOTAL")
    ad_dates = _rica_ad_dates(html)
    listings: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rent = row.get("marketPrice")
        if not isinstance(rent, int) or rent <= 0:
            continue
        # agreementType 5 = rent on Ricacorp; skip sale if mixed
        agreement = str(row.get("agreementType") or "")
        if agreement and agreement not in {"5", "rent", "Rent"}:
            # still accept when marketPrice present and alias ends with -5-hk
            alias = str(row.get("aliasV4") or row.get("alias") or "")
            if "-5-hk" not in alias and "-5-" not in alias:
                continue
        post_no = str(row.get("postNo") or row.get("id") or "")
        if not post_no:
            continue
        display = (
            row.get("displayTextHk")
            or row.get("displayText")
            or estate_name
        )
        floor = str(row.get("floorZoneText") or "").strip()
        flat = _rica_flat(row.get("flatZoneTextEn"))
        loc = row.get("publicLocationNamesHk") or []
        building = ""
        phase = ""
        if isinstance(loc, list) and loc:
            for part in loc:
                if not isinstance(part, str):
                    continue
                if re.search(r"(?:\d+|[A-Za-z])\s*座", part):
                    building = part.strip()
                phase_match = re.search(r"(\d+\s*期)", part)
                if phase_match:
                    phase = phase_match.group(1)
        address = " ".join(
            part for part in [phase, building or "", floor, flat] if part
        ).strip()
        if not address:
            address = str(display)
            for label in (estate_name, "時代廣場", "屯門市廣場"):
                address = address.replace(label, "")
            address = address.strip()
        bedrooms = row.get("room") if isinstance(row.get("room"), int) else None
        area = saleable_sqft(row.get("saleableArea"))
        alias = str(row.get("aliasV4") or row.get("alias") or "")
        detail_url = (
            f"https://www.ricacorp.com/zh-hk/property/detail/{urllib.parse.quote(alias, safe='-._~')}"
            if alias
            else list_url
        )
        image = (
            row.get("thumbnailDesktop")
            or row.get("thumbnail")
            or row.get("thumbnailMobile")
            or ""
        )
        if isinstance(image, str) and " " in image:
            image = image.split()[0]
        listings.append(
            {
                "source": "ricacorp",
                "source_name": "利嘉閣",
                "estate": estate_name,
                "listing_id": post_no,
                "title": str(display).strip() or estate_name,
                "address": address,
                "rent_hkd": rent,
                "area_sqft": area,
                "rent_per_sqft": rent_per_sqft(rent, area),
                "room_type": room_label(bedrooms),
                "bedrooms": bedrooms,
                "image_remote": image if isinstance(image, str) else "",
                "url": detail_url,
                "published_at": ad_dates.get(post_no),
                "updated_at": _rica_ms_to_iso(row.get("overallDateModified")),
                "scraped_at": SCRAPED_AT,
            }
        )
    if total is not None and int(total) != len(rows):
        print(f"ricacorp {estate_name} declared {total}, rows {len(rows)}", flush=True)
    if state.get("POSTSHASMORE"):
        print(f"ricacorp {estate_name} has more pages; only first SSR page scraped", flush=True)
    return listings


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


def write_data(listings: list[dict]) -> None:
    payload = {
        "meta": {
            "updated_at": datetime.now(HKT).replace(microsecond=0).isoformat(),
            "search_key": "／".join(str(item["name"]) for item in ESTATES),
            "card_count": len(listings),
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
                    "id": "28hse",
                    "name": "28Hse",
                    "url": ESTATES[0]["hse28_url"],
                },
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
                {
                    "id": "ricacorp",
                    "name": "利嘉閣",
                    "url": ESTATES[0]["ricacorp_url"],
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
        ("28hse", parse_28hse),
        ("midland", parse_midland),
        ("centanet", parse_centanet),
        ("ricacorp", parse_ricacorp),
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
    cache_images(listings)
    write_data(listings)
    print(
        f"cards {len(listings)} errors {errors} "
        f"tmtp_block8_removed {removed_block8 + removed_after}"
    )
    print(f"estate_counts {estate_counts(listings)}", flush=True)
    for source in ("28hse", "midland", "centanet", "ricacorp"):
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
