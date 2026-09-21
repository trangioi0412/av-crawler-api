"""Read-only catalog endpoints backing the Next.js admin UI (manufacturer
dropdown, product browsing). Not required by the sync engine itself.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas import ManufacturerOut, ProductOut
from core.registry import registry
from db.database import get_db
from db.repository import ProductRepository

router = APIRouter(tags=["catalog"])


@router.get("/manufacturers", response_model=list[ManufacturerOut])
def list_manufacturers() -> list[ManufacturerOut]:
    return [
        ManufacturerOut(key=c.key, display_name=c.display_name, base_url=c.base_url)
        for c in registry.list_manufacturers()
    ]


@router.get("/products", response_model=list[ProductOut])
def list_products(
    manufacturer: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[ProductOut]:
    products = ProductRepository(db).list_products(manufacturer=manufacturer, limit=limit, offset=offset)
    return [ProductOut.model_validate(p) for p in products]
