"""LunexEconom construction catalog, v0.1.

Read-only definitions for future specializations. They are NOT enabled for construction
or production until migration, balancing and server-authoritative validation land.
Existing building kinds and economics must remain unchanged.
"""

CATALOG_VERSION = 1

TRADE_SPECIALIZATIONS = (
    ("grocery", "Продуктовый магазин", "Продукты", "retail"),
    ("supermarket", "Супермаркет", "Продукты", "retail"),
    ("hypermarket", "Гипермаркет", "Продукты", "retail"),
    ("butcher", "Мясной магазин", "Продукты", "retail"),
    ("fish", "Рыбный магазин", "Продукты", "retail"),
    ("bakery", "Пекарня-магазин", "Продукты", "retail"),
    ("produce", "Овощной магазин", "Продукты", "retail"),
    ("confectionery", "Кондитерский магазин", "Продукты", "retail"),
    ("clothing", "Магазин одежды", "Одежда и спорт", "retail"),
    ("shoes", "Обувной магазин", "Одежда и спорт", "retail"),
    ("sports", "Спортивный магазин", "Одежда и спорт", "retail"),
    ("children", "Детский магазин", "Одежда и спорт", "retail"),
    ("jewelry", "Ювелирный магазин", "Одежда и спорт", "retail"),
    ("electronics", "Магазин электроники", "Электроника и транспорт", "retail"),
    ("appliances", "Магазин бытовой техники", "Электроника и транспорт", "retail"),
    ("car_dealer", "Автосалон", "Электроника и транспорт", "retail"),
    ("auto_parts", "Магазин автозапчастей", "Электроника и транспорт", "retail"),
    ("motorcycle", "Мотосалон", "Электроника и транспорт", "retail"),
    ("agro_machinery", "Салон сельхозтехники", "Электроника и транспорт", "retail"),
    ("furniture", "Мебельный магазин", "Дом и строительство", "retail"),
    ("building_materials", "Магазин стройматериалов", "Дом и строительство", "retail"),
    ("plumbing", "Магазин сантехники", "Дом и строительство", "retail"),
    ("hardware", "Хозяйственный магазин", "Дом и строительство", "retail"),
    ("garden", "Садовый центр", "Дом и строительство", "retail"),
    ("pharmacy", "Аптека", "Здоровье и досуг", "retail"),
    ("books", "Книжный магазин", "Здоровье и досуг", "retail"),
    ("pet", "Зоомагазин", "Здоровье и досуг", "retail"),
    ("cosmetics", "Магазин косметики", "Здоровье и досуг", "retail"),
    ("outdoor", "Магазин товаров для отдыха", "Здоровье и досуг", "retail"),
    ("food_wholesale", "Продовольственная оптовая база", "Опт", "wholesale"),
    ("building_wholesale", "Оптовая база стройматериалов", "Опт", "wholesale"),
    ("fuel_wholesale", "Топливная оптовая база", "Опт", "wholesale"),
    ("agro_wholesale", "База агроснабжения", "Опт", "wholesale"),
)

FUTURE_CATEGORIES = (
    "crop_farming", "livestock", "agro_storage", "extraction",
    "food_industry", "heavy_industry", "light_industry", "materials",
    "research", "logistics", "commercial_property", "municipal",
)


def view():
    """Public metadata only: no fictional prices, sizes or build permissions."""
    import economy
    base = [
        {"kind": kind, "build_cost": price, "enabled": True}
        for kind, price in economy.BUILD_COST.items()
    ]
    trade = [
        {"id": slug, "name": name, "category": category, "role": role,
         "base_kind": "shop", "enabled": False}
        for slug, name, category, role in TRADE_SPECIALIZATIONS
    ]
    return {"version": CATALOG_VERSION, "base_buildings": base,
            "trade_specializations": trade,
            "future_categories": list(FUTURE_CATEGORIES),
            "note": "Specializations are design-only and cannot yet be built."}
