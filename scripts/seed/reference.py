"""Curated reference data: Bangalore areas (real approximate coordinates), invented tech parks,
market rent averages, grocery stores, delivery fee rules and bank cards."""

from __future__ import annotations

from typing import Final, NamedTuple


class AreaSeed(NamedTuple):
    id: str
    name: str
    lat: float
    lng: float
    popular: bool
    #: Market PG rent; co-living and shared flats are derived from it.
    pg_rent: int
    #: How many eateries and homes to generate here.
    food_count: int
    home_count: int


AREAS: Final[tuple[AreaSeed, ...]] = (
    AreaSeed("area_hsr", "HSR Layout", 12.9121, 77.6446, True, 11500, 18, 9),
    AreaSeed("area_koramangala", "Koramangala", 12.9352, 77.6245, True, 12500, 14, 8),
    AreaSeed("area_btm", "BTM Layout", 12.9166, 77.6101, True, 9500, 12, 8),
    AreaSeed("area_bellandur", "Bellandur", 12.9304, 77.6784, True, 11000, 18, 9),
    AreaSeed("area_marathahalli", "Marathahalli", 12.9591, 77.6974, True, 10500, 12, 11),
    AreaSeed("area_whitefield", "Whitefield", 12.9698, 77.7499, True, 10000, 10, 9),
    AreaSeed("area_ecity", "Electronic City", 12.8452, 77.6602, True, 8000, 10, 9),
    AreaSeed("area_indiranagar", "Indiranagar", 12.9784, 77.6408, True, 13000, 10, 8),
    AreaSeed("area_jayanagar", "Jayanagar", 12.9299, 77.5826, False, 10000, 8, 8),
    AreaSeed("area_kadubeesanahalli", "Kadubeesanahalli", 12.9421, 77.6975, False, 10500, 12, 8),
    AreaSeed("area_sarjapur", "Sarjapur Road", 12.9009, 77.6874, True, 9500, 10, 8),
    AreaSeed("area_domlur", "Domlur", 12.9610, 77.6387, False, 12000, 7, 8),
    AreaSeed("area_jpnagar", "JP Nagar", 12.9063, 77.5857, False, 9500, 8, 8),
    AreaSeed("area_mahadevapura", "Mahadevapura", 12.9916, 77.7064, False, 9500, 8, 8),
    AreaSeed("area_bommanahalli", "Bommanahalli", 12.9089, 77.6239, False, 8500, 8, 8),
)


class TechParkSeed(NamedTuple):
    id: str
    name: str
    area_id: str
    lat: float
    lng: float


#: Invented names in the real office corridors (Outer Ring Road, Whitefield, Electronic City).
TECH_PARKS: Final[tuple[TechParkSeed, ...]] = (
    TechParkSeed("park_orbit", "Orbit Tech Campus", "area_bellandur", 12.9256, 77.6815),
    TechParkSeed(
        "park_meridian", "Meridian Business Hub", "area_kadubeesanahalli", 12.9436, 77.6964
    ),
    TechParkSeed("park_lumina", "Lumina IT Park", "area_whitefield", 12.9759, 77.7363),
    TechParkSeed("park_southgate", "Southgate Tech Zone", "area_ecity", 12.8399, 77.6639),
    TechParkSeed(
        "park_crestline", "Crestline Corporate Park", "area_marathahalli", 12.9552, 77.7012
    ),
    TechParkSeed("park_banyan", "Banyan Grove Tech Park", "area_mahadevapura", 12.9945, 77.7010),
    TechParkSeed("park_riverstone", "Riverstone Software Park", "area_sarjapur", 12.9045, 77.6960),
    TechParkSeed("park_cobalt", "Cobalt Square", "area_domlur", 12.9585, 77.6420),
)

#: Co-living and shared-flat rents relative to the area's PG rent.
RENT_MULTIPLIERS: Final[dict[str, float]] = {"pg": 1.0, "coliving": 1.4, "sharedFlat": 1.3}


class StoreSeed(NamedTuple):
    id: str
    name: str
    store_type: str
    is_primary: bool


STORES: Final[tuple[StoreSeed, ...]] = (
    StoreSeed("store_zipcart", "ZipCart", "quickCommerce", True),
    StoreSeed("store_swiftcrate", "SwiftCrate", "quickCommerce", False),
    StoreSeed("store_freshaisle", "FreshAisle Supermarket", "supermarket", True),
    StoreSeed("store_dailyharvest", "Daily Harvest Mart", "supermarket", False),
    StoreSeed("store_srilakshmi", "Sri Lakshmi Kirana", "kirana", True),
    StoreSeed("store_manjunatha", "Manjunatha Provision Stores", "kirana", False),
    StoreSeed("store_stockup", "StockUp Wholesale", "onlineBulk", True),
    StoreSeed("store_packright", "PackRight Wholesale", "onlineBulk", False),
)


class DeliveryPlatformSeed(NamedTuple):
    id: str
    name: str
    item_markup_percent: int
    base_delivery_fee: int
    per_km_fee: int
    platform_fee: int
    packaging_fee: int


#: Fee rules for the invented delivery apps. Each marks the dish up and adds its own fees,
#: which is exactly the gap the Food agent points out.
DELIVERY_PLATFORMS: Final[tuple[DeliveryPlatformSeed, ...]] = (
    DeliveryPlatformSeed("dp_feastdrop", "FeastDrop", 18, 35, 8, 12, 20),
    DeliveryPlatformSeed("dp_quickbite", "QuickBite", 22, 29, 10, 15, 25),
    DeliveryPlatformSeed("dp_dabbarun", "DabbaRun", 12, 45, 6, 8, 15),
)
GST_PERCENT: Final = 5

#: Real Indian bank names are fine for card offers; every platform and store is invented.
BANKS: Final[tuple[str, ...]] = ("HDFC", "SBI", "ICICI", "Axis", "Kotak")
CARD_CHOICES: Final[tuple[tuple[str, str, str], ...]] = tuple(
    (f"card_{bank.lower()}_{'cc' if kind == 'credit' else 'dc'}", bank, kind)
    for bank in BANKS
    for kind in ("credit", "debit")
)

SHOPPING_OFFER_PLATFORMS: Final[tuple[str, ...]] = ("ShopNest", "TrendKart", "StyleBay")
FOOD_OFFER_PLATFORMS: Final[tuple[str, ...]] = ("FeastDrop", "QuickBite", "DabbaRun")
GROCERY_OFFER_PLATFORMS: Final[tuple[str, ...]] = (
    "ZipCart",
    "SwiftCrate",
    "StockUp Wholesale",
    "FreshAisle Supermarket",
)
