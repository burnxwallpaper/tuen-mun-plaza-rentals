# 屯門市廣場 租盤

仍在放租的屯門市廣場、屯門時代廣場單位，彙整 28Hse、美聯物業、中原地產、利嘉閣。頁面讀 `data/listings.json`，圖片在 `images/`。屯門市廣場會排除全部 8座（第3期）單位；時代廣場不套用此規則。

網站：https://burnxwallpaper.github.io/tuen-mun-plaza-rentals/

## 開啟

GitHub Pages 由 `main` 根目錄發布。打開上面的網址即可。

本機預覽（`file://` 會擋住 `fetch`）：

```bash
python -m http.server 8080
```

然後開 http://localhost:8080/

## 資料

`data/listings.json` 是樓盤檔，形狀是 `{ "meta", "listings" }`。書籤另見 `data/bookmarks.json`，`refresh.py` 唔會覆寫佢。

`meta` 包含：

- `updated_at`：香港時間 ISO（例如 `2026-09-26T00:35:32+08:00`）
- `search_key`：兩個屋苑名稱
- `estate_counts`：各屋苑卡片數
- `card_count`：寫入檔案嘅卡片數（已套租金上限；超出預算但保留嘅書籤都計入）
- `rent_cap_hkd`：租金上限，而家係 14001
- `excluded_over_cap`：今次因為高過上限而冇寫入嘅卡數
- `excluded_unknown_rent`：未知或非正租金而冇寫入嘅卡數
- `source_counts`：各來源出現次數（合併卡上的「同時見於」也計入，所以合計可以大於卡片數）
- `primary_counts`：每張卡主來源的數量

每張卡有圖片、來源連結、租金（港元）、房型，以及來源名稱、標題／地址（有就顯示）。

每條樓盤另有 `published_at`（刊登日期）和 `updated_at`（更新日期），皆為香港時間 ISO。來源沒有該日期時為 `null`，卡片不顯示該行。`scraped_at` 仍是本次抓取時間。中原取搜尋結果的 `publishDate`／`updateDate`；美聯的 `updated_at` 取列表 `update_date`，`published_at` 取樓盤頁 `first_pub_date`；28Hse 取樓盤頁 JSON-LD 的 `datePublished`／`dateModified`；利嘉閣 `published_at` 取列表「廣告日期」，`updated_at` 取 SSR `overallDateModified`。

座數、樓層（高／中／低）、單位字母、房數都齊，而且租金相差不超過 15% 時，會併成一張卡並保留各來源連結。合併卡嘅刊登日取組內最早非空值，更新日取最晚非空值。對不上的盤各自保留。

來源搜尋頁：

- 28Hse：https://www.28hse.com/rent/a3/dg48/c4433
- 美聯：https://www.midland.com.hk/zh-hk/list/rent/屯門市廣場-E-E00091
- 中原：https://hk.centanet.com/findproperty/list/rent/屯門市廣場_3-NXLIIHSSHT
- 利嘉閣：https://www.ricacorp.com/zh-hk/property/list/rent/屯門市廣場-bigest-屯門市中心-hma-hk

時代廣場另有對應搜尋：28Hse `c4458`、美聯 `E00496`、中原 `2-BGKEBPYEPS`、利嘉閣 `時代廣場-estate-屯門市中心-hma-hk`。

## 更新並推上網站

在專案根目錄：

```bash
python scripts/refresh.py
git add data/listings.json images
git commit -m "Update rental listings"
git push origin main
```

`refresh.py` 只用 Python 3 標準庫。它會重抓四個來源仍在放租的盤、排除 8座、下載缺的圖片，並覆寫 `data/listings.json`。推上 `main` 後 GitHub Pages 會重新發布。`data/bookmarks.json` 要一併保留。

## 書籤

`data/bookmarks.json` 的 `keys` 是預設書籤，而家係中原編號 `CEA208`、`CFE131`、`CGH466`、`CIK891`。頁面用 `listing_id` 或網址入面嘅 `_編號` 對卡（包括合併卡嘅「同時見於」），唔睇 `theme` query。其他來源用去掉 query 嘅網址做鍵。

載入時：有效書籤 =（`bookmarks.json` ∪ localStorage `added`）− localStorage `removed`。localStorage 鍵名 `tmtp-bookmarks-v1`，只在撳星之後先寫。未撳過就跟檔案預設，四張卡會即時顯示實心星。之後喺檔案加新編號，只要冇被本機剔走过，都會自動出現。

每張卡有星掣。篩選列有「書籤」，只顯示已加星嘅卡。已經唔喺 `listings.json` 嘅鍵會顯示「已下架書籤」。

## 租金上限

主列表、中位數、屋苑／房數／來源計數只保留已知租金而且 ≤ HK$14,001 嘅卡。未知、0、或高過 14001 嘅盤唔會出現喺主列表。而家呢份資料冇未知租金。

`refresh.py` 寫 `listings.json` 時用同一條規則（`meta.rent_cap_hkd`、`meta.excluded_over_cap`）。如果一個書籤高過上限，因為佢喺 `bookmarks.json`，資料會保留佢，但主列表仍然唔顯示；開「書籤」先見到，並標「超出預算」。CEA208（HK$13,500）、CFE131（HK$13,000）、CGH466（HK$12,500）、CIK891（HK$12,500）都未超過上限。

## 抓取頻率

請隔一段時間再跑，不要連續重抓。

- 美聯、中原分頁之間約停 0.4 秒，最多各抓數頁。
- 圖片每 8 張再停約 0.3 秒；本地已有且大於 1KB 的圖會跳過。
- 28Hse 只抓搜尋結果第一頁。

美聯的訪客 token 來自 `https://www.midland.com.hk/api/token` 的 `Set-Cookie`。若該站改版導致 401，先用瀏覽器打開上面的美聯搜尋頁確認仍有租盤，再對一下 `scripts/refresh.py` 裡的請求。
