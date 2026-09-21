# av-crawler-api — Manufacturer Data Sync Engine

A standalone FastAPI service that crawls manufacturer websites, normalizes/validates/deduplicates the results, and persists a manufacturer-independent product catalog.

Copied out of `D:\DataCrawler\backend` (2026-09-21) into its own project so this backend can be developed independently from the DataCrawler prototype and from any frontend that calls it. It currently backs [AV_Catalog](../AV_Catalog)'s `/admin/manufacturer-sync` page (a thin Next.js proxy — see `src/lib/manufacturerSync/api.ts` there) via `MANUFACTURER_SYNC_API_URL`; nothing here is AV_Catalog-specific, so any frontend can call the same `GET/POST /api/...` routes below.

## Running

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
cp .env.example .env            # defaults work out of the box (SQLite)

uvicorn main:app --reload --port 8000
```

- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `GET http://localhost:8000/docs` → interactive OpenAPI docs (FastAPI default)

The SQLite database file is created automatically at `./data/sync.db` on first run.

## Google Sheets export (optional)

Every successfully-persisted product is also exported to a per-manufacturer
tab (e.g. `hdcvt`) in a shared Google Sheet, if `GOOGLE_SPREADSHEET_ID` is
set in `.env`. This is a best-effort supplementary sink: SQLite remains the
source of truth for sync job status and deduplication, and a Sheets failure
is logged but never fails the sync job. See `services/google_sheets.py` for
the column mapping and upsert strategy (matches existing rows by
`product (item)`, falling back to `Title`).

Setup: download a service-account JSON key from Google Cloud Console, save
it to `credentials/google-service-account.json` (gitignored -- never
commit it), share the target spreadsheet with that service account's
`client_email` as an Editor, and set `GOOGLE_SPREADSHEET_ID` in `.env`.

## Testing

```bash
pytest
```

34 tests, no network access and no real database required — see `tests/conftest.py` (points `DATABASE_URL` at a throwaway SQLite file before anything else imports) and `tests/fixtures/hdcvt_*.html` (real HTML snapshots of hdcvt.com captured 2026-09-18, used so adapter tests never hit the live site).

There is no separate "integration test against the real site" suite; that was instead run manually against the live HDCVT site during development (see `Known limitations` in the root README) and isn't part of `pytest` since it's slow, external, and not idempotent to run in CI.

## Architecture (this package)

```
core/
  engine.py          sync_manufacturer_data() — the ONE generic entry point,
                      contains zero manufacturer-specific logic
  registry.py         key -> adapter class + config, adapters self-register
  models/              RawProduct / CanonicalProduct / ValidationResult / job status
  pipeline/
    normalizer.py       RawProduct -> CanonicalProduct (trim, absolutize URLs, dedup_key)
    validator.py         CanonicalProduct -> VALID / WARNING / INVALID
    deduplicator.py      dedup_key -> create / update / skip-duplicate-in-run
    transformer.py       CanonicalProduct -> dict of DB columns

manufacturers/
  base.py             BaseManufacturerAdapter (crawl/fetch/parse contract)
  hdcvt/               manufacturer adapter #1 (see below)

db/
  models.py           SQLAlchemy models: Product, SyncJob
  repository.py        all DB access goes through here

api/
  routes/              health, sync (POST /api/sync/manufacturer, GET /api/sync/status/{id}),
                        catalog (GET /api/manufacturers, GET /api/products)

services/
  http_client.py       shared polite HTTP client: rate limiting, retry/backoff,
                        timeout, robots.txt awareness -- one implementation
                        used by every adapter
```

## Adding a new manufacturer

No changes to `core/`, `db/`, or `api/` are required. Steps:

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
