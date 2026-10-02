"""Regression test: this service's admin sheets (DataCrawler_New_brand,
DataCrawler_System_Config, DataCrawler_Sync_logs) are prefixed because the
shared spreadsheet already has unrelated CMS tabs named plain "New_brand",
"System_Config", and "Sync_Logs" -- both the prefixed names (this service's
own) and the plain ones (the CMS's) must stay out of the syncable
manufacturer list, or either shows up as a fake "brand" in /api/manufacturers.
"""
from __future__ import annotations

from services.admin_sheets import list_brand_sheet_names
from tests.fake_sheets import FakeSpreadsheet


def test_list_brand_sheet_names_excludes_this_services_own_admin_tabs():
    fake = FakeSpreadsheet()
    fake.seed_rows("hdcvt", ["Title"], [])
    fake.seed_rows("DataCrawler_New_brand", ["Slug"], [])
    fake.seed_rows("DataCrawler_System_Config", ["Slug"], [])
    fake.seed_rows("DataCrawler_Sync_logs", ["Job ID"], [])

    assert list_brand_sheet_names(fake) == ["hdcvt"]


def test_list_brand_sheet_names_excludes_preexisting_cms_tabs_of_the_same_concept():
    fake = FakeSpreadsheet()
    fake.seed_rows("hdcvt", ["Title"], [])
    # The CMS's own tabs -- different schema, unrelated to this service, but
    # would otherwise collide by name/concept with the ones above.
    fake.seed_rows("New_brand", ["STT", "Name", "Logo", "Status"], [])
    fake.seed_rows("System_Config", ["Key", "Value"], [])
    fake.seed_rows("Sync_Logs", ["Something", "Else"], [])
    fake.seed_rows("product_new", ["Category"], [])
    fake.seed_rows("product_delete", ["Category"], [])

    assert list_brand_sheet_names(fake) == ["hdcvt"]
