# 屯門市廣場 租盤

仍在放租的屯門市廣場單位，彙整 28Hse、美聯物業、中原地產。頁面讀 `data/listings.json`，圖片在 `images/`。

網站：https://burnxwallpaper.github.io/tuen-mun-plaza-rentals/

## 開啟

GitHub Pages 由 `main` 根目錄發布。打開上面的網址即可。

本機預覽（`file://` 會擋住 `fetch`）：

```bash
python -m http.server 8080
```

然後開 http://localhost:8080/

## 資料

`data/listings.json` 是唯一的樓盤檔，形狀是 `{ "meta", "listings" }`。

`meta` 包含：

- `updated_at`：香港時間 ISO（例如 `2026-09-26T00:35:32+08:00`）
- `search_key`：`屯門市廣場`
- `card_count`：畫面上的卡片數（跨來源合併後）
- `source_counts`：各來源出現次數（合併卡上的「同時見於」也計入，所以合計可以大於卡片數）
- `primary_counts`：每張卡主來源的數量

每張卡有圖片、來源連結、租金（港元）、房型，以及來源名稱、標題／地址（有就顯示）。

每條樓盤另有 `published_at`（刊登日期）和 `updated_at`（更新日期），皆為香港時間 ISO。來源沒有該日期時為 `null`，卡片不顯示該行。`scraped_at` 仍是本次抓取時間。中原取搜尋結果的 `publishDate`／`updateDate`；美聯的 `updated_at` 取列表 `update_date`，`published_at` 取樓盤頁 `first_pub_date`；28Hse 取樓盤頁 JSON-LD 的 `datePublished`／`dateModified`。

座數、樓層（高／中／低）、單位字母、房數都齊，而且租金相差不超過 15% 時，會併成一張卡並保留各來源連結。合併卡嘅刊登日取組內最早非空值，更新日取最晚非空值。對不上的盤各自保留。

來源搜尋頁：

- 28Hse：https://www.28hse.com/rent/a3/dg48/c4433
- 美聯：https://www.midland.com.hk/zh-hk/list/rent/屯門市廣場-E-E00091
- 中原：https://hk.centanet.com/findproperty/list/rent/屯門市廣場_3-NXLIIHSSHT

## 更新並推上網站

在專案根目錄：

```bash
python scripts/refresh.py
git add data/listings.json images
git commit -m "Update rental listings"
git push origin main
```

`refresh.py` 只用 Python 3 標準庫。它會重抓三個來源仍在放租的盤、下載缺的圖片，並覆寫 `data/listings.json`。`index.html` 不用改。推上 `main` 後 GitHub Pages 會重新發布。

## 抓取頻率

請隔一段時間再跑，不要連續重抓。

- 美聯、中原分頁之間約停 0.4 秒，最多各抓數頁。
- 圖片每 8 張再停約 0.3 秒；本地已有且大於 1KB 的圖會跳過。
- 28Hse 只抓搜尋結果第一頁。

美聯的訪客 token 來自 `https://www.midland.com.hk/api/token` 的 `Set-Cookie`。若該站改版導致 401，先用瀏覽器打開上面的美聯搜尋頁確認仍有租盤，再對一下 `scripts/refresh.py` 裡的請求。
