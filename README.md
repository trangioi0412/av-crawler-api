# av-crawler-api — Manufacturer Data Sync Engine

A standalone FastAPI service that crawls manufacturer websites, normalizes/validates/deduplicates the results, and persists a manufacturer-independent product catalog.

Copied out of `D:\DataCrawler\backend` (2026-09-21) into its own project so this backend can be developed independently from the DataCrawler prototype and from any frontend that calls it. It currently backs [AV_Catalog](../AV_Catalog)'s `/admin/manufacturer-sync` page (a thin Next.js proxy — see `src/lib/manufacturerSync/api.ts` there) via `MANUFACTURER_SYNC_API_URL`; nothing here is AV_Catalog-specific, so any frontend can call the same `GET/POST /api/...` routes below.

## Running

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
cp .env.example .env
# Then set GOOGLE_SPREADSHEET_ID and drop a service-account key at
# credentials/google-service-account.json -- see "Google Sheets" below.
# There is no database; nothing works until this is set.

uvicorn main:app --reload --port 8000
```

- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `GET http://localhost:8000/docs` → interactive OpenAPI docs (FastAPI default)

## Google Sheets -- the only persistence layer

There is no database. One shared spreadsheet (`GOOGLE_SPREADSHEET_ID`) holds
everything:

- **One tab per manufacturer** (e.g. `hdcvt`, `yealink`) -- the product
  catalog itself. Created automatically on that brand's first successful
  sync. See `services/google_sheets.py` for the column mapping and the
  upsert strategy (matches existing rows by `product (item)`, falling back
  to `Title`).
- **`DataCrawler_New_brand`** -- the "Yeu cau them hang moi" (request a new
  manufacturer) intake queue. One row per submitted request, walking
  `Chờ duyệt -> Duyệt -> Đang cào dữ liệu -> Đã cào xong` (row deleted once
  done) or `-> Lỗi cào dữ liệu` if the sync failed. See
  `services/admin_sheets.py::NewBrandStore`.
- **`DataCrawler_System_Config`** -- durable `brand key -> website` lookup. Written at
  approval time (DataCrawler_New_brand rows are transient; this is what a future
  re-sync of that brand looks up once its DataCrawler_New_brand row is long gone). See
  `SystemConfigStore`.
- **`DataCrawler_Sync_logs`** -- history of sync job runs (job id, manufacturer,
  status, counts). Written only at job start and job end, never per item,
  to stay well under Google Sheets API rate limits -- see
  `services/job_store.py` for the in-memory state that serves *live*
  progress polling (`GET /api/sync/status/{job_id}`) while a job is
  running in this process.

`GET /api/manufacturers` / `POST /api/sync/manufacturer` treat every other
tab in the spreadsheet as a syncable manufacturer (see
`services/admin_sheets.py::RESERVED_SHEET_TITLES` for the exact exclusion
list, and `core/manufacturer_resolution.py` for how a tab name resolves to
either a hand-written code adapter or a `DataCrawler_System_Config`-driven AI adapter).
`POST /api/sync/all` syncs every one of them, one after another.

Setup: download a service-account JSON key from Google Cloud Console, save
it to `credentials/google-service-account.json` (gitignored -- never
commit it), share the target spreadsheet with that service account's
`client_email` as an Editor, and set `GOOGLE_SPREADSHEET_ID` in `.env`.

## Testing

```bash
pytest
```

No network access, no real database, and no real Google Sheets required --
every test gets a `fake_spreadsheet` fixture (`tests/fake_sheets.py`, an
in-memory stand-in for the gspread client) in place of the real one, and
`tests/fixtures/hdcvt_*.html` (real HTML snapshots of hdcvt.com captured
2026-09-18) so adapter tests never hit the live site.

There is no separate "integration test against the real site" suite; that
was instead run manually against the live HDCVT site during development
(see `Known limitations` in the root DataCrawler README this project was
copied out of) and isn't part of `pytest` since it's slow, external, and
not idempotent to run in CI.

## Architecture (this package)

```
core/
  engine.py                    sync_manufacturer_data() — the ONE generic entry point,
                                contains zero manufacturer-specific logic
  manufacturer_resolution.py    key -> (adapter class, config), either a code adapter
                                (registry.py) or a DataCrawler_System_Config-driven AI adapter
  registry.py                   key -> adapter class + config, code adapters self-register
  models/                        RawProduct / CanonicalProduct / ValidationResult / job status
  pipeline/
    normalizer.py                 RawProduct -> CanonicalProduct (trim, absolutize URLs, dedup_key)
    validator.py                  CanonicalProduct -> VALID / WARNING / INVALID
    deduplicator.py               dedup_key -> create / skip-duplicate-in-run (cross-run
                                   create-vs-update is Google Sheets' job now, see below)
    transformer.py                 CanonicalProduct -> dict of sheet-row fields

manufacturers/
  base.py             BaseManufacturerAdapter (crawl/fetch/parse contract)
  hdcvt/               manufacturer adapter #1, hand-written (see below)
  generic_ai/          AI-assisted adapter used for every DataCrawler_System_Config-driven brand

api/
  routes/              health, sync (POST /api/sync/manufacturer, POST /api/sync/all,
                        GET /api/sync/status/{id}), catalog (GET /api/manufacturers,
                        GET /api/products), manufacturer-requests (DataCrawler_New_brand intake),
                        images (POST /api/images/download)

services/
  google_sheets.py     per-manufacturer product tab: GoogleSheetsExporter (upsert by natural key)
  admin_sheets.py       DataCrawler_New_brand / DataCrawler_System_Config / DataCrawler_Sync_logs sheets (SheetRowStore + friends)
  job_store.py           in-memory live job status + durable DataCrawler_Sync_logs writes at start/end
  sheets_client.py        the one function that opens the spreadsheet (gspread auth)
  http_client.py         shared polite HTTP client: rate limiting, retry/backoff,
                          timeout, robots.txt awareness -- one implementation
                          used by every adapter
  image_downloader.py    downloads a manufacturer's "image" column URLs to Data/<manufacturer>/
```

## Downloading product images locally

`POST /api/images/download?manufacturer=hdcvt` reads that manufacturer's
sheet tab and downloads every URL in its "image" column
(`CanonicalProduct.image_urls`, one per line -- see `services/google_sheets.py`)
into `Data/<manufacturer>/` at the project root. Filenames are built from
each row's `Title` by `core/image_naming.py`: every whitespace-separated
word is title-cased and joined with "_", and every image after a
product's first gets Windows Explorer's own duplicate-file suffix --
e.g. `Sdvoe_(_1_0_G_).jpg`, then `Sdvoe_(_1_0_G_)_(1).jpg` for its second
image. Re-running is cheap: a file already on disk under its deterministic
name is left alone instead of re-downloaded.

## Adding a new manufacturer

Two ways to onboard a brand:

- **Through the admin UI** ("Yeu cau them hang moi" -> preview -> approve):
  no code at all, uses the generic AI-assisted adapter. See the DataCrawler_New_brand
  lifecycle above.
- **Hand-written code adapter** (for a brand that needs real, verified
  selectors instead of AI extraction, like HDCVT): no changes to `core/`
  or `api/` are required. Steps:

1. **Inspect the real site first.** Fetch a category/listing page and a product detail page, find the actual selectors or a sitemap/API. Do not guess.
2. Create `manufacturers/<name>/config.py`:
   ```python
   from manufacturers.base import ManufacturerConfig

   YEALINK_CONFIG = ManufacturerConfig(
       key="yealink",
       display_name="Yealink",
       base_url="https://www.yealink.com",
       request_delay_seconds=1.5,
   )
   ```
3. Create `manufacturers/<name>/adapter.py`:
   ```python
   from manufacturers.base import BaseManufacturerAdapter
   from core.models.product import RawProduct

   class YealinkAdapter(BaseManufacturerAdapter):
       def discover_product_urls(self):
           ...  # yield absolute product URLs

       def fetch_product(self, url: str) -> str:
           return self.http.get_text(url)

       def parse(self, raw_content: str, source_url: str) -> RawProduct:
           ...  # BeautifulSoup (or similar) -> RawProduct with canonical field names
   ```
4. Create `manufacturers/<name>/__init__.py`:
   ```python
   from core.registry import registry
   from manufacturers.yealink.adapter import YealinkAdapter
   from manufacturers.yealink.config import YEALINK_CONFIG

   registry.register(YEALINK_CONFIG.key, YealinkAdapter, YEALINK_CONFIG)
   ```
5. Add one import line to `manufacturers/__init__.py`:
   ```python
   from manufacturers import yealink  # noqa: F401
   ```
6. Add fixture-based tests under `tests/adapters/test_yealink_adapter.py` (save real HTML/JSON to `tests/fixtures/`, never hit the live site in unit tests).

That's it — `sync_manufacturer_data(manufacturer="yealink")`, `POST /api/sync/manufacturer {"manufacturer": "yealink"}`, and the Next.js dropdown all work immediately, with no other file touched.

## HDCVT adapter notes

Verified against the live site on 2026-09-18 (`manufacturers/hdcvt/config.py` has the full notes):

- Product discovery uses `/sitemap.xml` (an official, structured endpoint) rather than scraping the nav or paginating category pages. Product-detail URLs match `/<slug>/<digits>.html`; the site's "Notice"/"IndustryNews" (news) and "Medical"/"game"/"Command"/"VideoConference" (solution landing pages) sections reuse that same shape but aren't products, so they're excluded by slug.
- Pages are static server-rendered HTML — plain `requests` + BeautifulSoup, no browser automation needed.
- robots.txt returns a redirect to the homepage (i.e. there is no real robots.txt), so crawling is unrestricted; `respect_robots_txt=True` is left on regardless so the client fails safe if that ever changes.
- Specifications come from a free-form WYSIWYG HTML table with decorative rowspan/colspan header cells (`"Specifications"`/`"Technical"`); the parser skips those and keeps every other row as a key/value pair.
- Not every product has a model/SKU on the page (e.g. some cable variants) — those are still persisted, using the Deduplicator's name+URL hash fallback identity, and flagged as a `WARNING` rather than rejected.
