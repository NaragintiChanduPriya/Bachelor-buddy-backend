"""Curated vocabulary for the deterministic synthetic-data generator.

Pure data, no logic. Every brand, business, merchant and platform name here is invented.
Generic dish, grocery and variety names (idli, Sona masoori rice, toor dal) and real Bangalore
area and road names are used as-is. Prices are plain integer rupees (Bangalore, 2026).
"""

from typing import Final, NamedTuple


class MenuTemplate(NamedTuple):
    name: str
    base_price: int  # rupees
    veg: bool
    popular: bool  # a main dish people typically order (never a drink or side)


class GroceryTemplate(NamedTuple):
    name: str
    unit: str  # e.g. "1 kg", "500 g", "1 L", "500 ml", "1 dozen", "1 pc", "1 bunch"
    category: str  # one of GROCERY_CATEGORIES
    kirana_price: int  # neighbourhood-store price for ONE unit, rupees
    bulk_unit: str | None  # e.g. "5 kg bag", "5 L can"; None if no bulk pack
    bulk_multiple: int | None  # units in the bulk pack (2..10); None if no bulk pack
    kind: str  # "staple" | "fresh" | "spice" | "packaged" | "household"


class ProductCategoryVocab(NamedTuple):
    label: str  # display label, e.g. "Formal shoes"
    brands: tuple[str, ...]  # 6-8 invented brand names
    styles: tuple[str, ...]  # 8-12 descriptors
    items: tuple[str, ...]  # 5-8 product noun phrases
    mrp_range: tuple[int, int]  # (min, max) MRP in rupees
    descriptions: tuple[str, ...]  # one-sentence templates using {brand} and {name}
    highlights: tuple[str, ...]  # 10-14 short highlight phrases


class ExpenseTemplate(NamedTuple):
    title: str  # may contain "{eatery}" or "{month}"
    merchant: str | None  # invented merchant, "{eatery}" placeholder, or None
    min_amount: int
    max_amount: int
    source: str  # "manual" | "delivery" | "subscription" | "recurring"


# =============================================================================================
# Food
# =============================================================================================

FOOD_NAME_PREFIXES: Final[tuple[str, ...]] = (
    "Sri",
    "Shree",
    "New",
    "Namma",
    "Hotel",
    "Udupi",
    "Om",
    "Jai",
    "Royal",
    "Nava",
    "Shubham",
)

FOOD_NAME_CORES: Final[tuple[str, ...]] = (
    # deities
    "Ganesh",
    "Annapoorna",
    "Lakshmi",
    "Saraswathi",
    "Manjunatha",
    "Raghavendra",
    "Chamundi",
    "Krishna",
    "Durga",
    "Anjaneya",
    "Ranga",
    "Venkatesha",
    # rivers
    "Kaveri",
    "Tunga",
    "Kapila",
    "Sharavathi",
    "Hemavathi",
    "Netravathi",
    "Kabini",
    "Arkavathi",
    # flowers
    "Mallige",
    "Sampige",
    "Tulasi",
    "Kamala",
    "Kanakambara",
    "Parijata",
    "Sevanthi",
    "Tavare",
    # places
    "Malnad",
    "Hampi",
    "Kodagu",
    "Karavali",
    "Mysuru",
    "Sringeri",
    "Gokarna",
    "Kudremukh",
    # virtues and blessings
    "Shubha",
    "Mangala",
    "Anugraha",
    "Santosh",
    "Prasanna",
    "Vijaya",
    "Akshaya",
    "Amrutha",
    "Nandana",
    "Sneha",
)

FOOD_NAME_SUFFIXES: Final[dict[str, tuple[str, ...]]] = {
    "darshini": (
        "Tiffin Room",
        "Darshini",
        "Upahara",
        "Idli Corner",
        "Tiffins",
        "Veg Corner",
        "Upahara Mandira",
        "Dosa Point",
    ),
    "mess": (
        "Mess",
        "Meals",
        "Bhojanalaya",
        "Oota Mane",
        "Meals Point",
        "Andhra Meals",
        "Home Mess",
    ),
    "tiffin": (
        "Tiffin Service",
        "Dabba Kitchen",
        "Home Meals",
        "Lunch Box",
        "Homely Tiffins",
        "Meal Box",
        "Tiffin Centre",
    ),
    "restaurant": (
        "Family Restaurant",
        "Kitchen",
        "Biryani House",
        "Military Hotel",
        "Restaurant",
        "Spice Kitchen",
        "Dhaba",
        "Family Dining",
    ),
    "cafe": (
        "Cafe",
        "Coffee House",
        "Bakes & Brews",
        "Coffee Bar",
        "Chai Corner",
        "Bakery & Cafe",
        "Iyengar Bakery",
        "Brew Corner",
    ),
}

FOOD_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "darshini": (
        "South Indian",
        "Breakfast",
        "Filter coffee",
        "Pure veg",
        "Quick bites",
        "Budget",
        "Standing counter",
        "Dosa",
        "Idli vada",
    ),
    "mess": (
        "Unlimited rice",
        "Home style",
        "South Indian",
        "Meals",
        "Budget",
        "Lunch",
        "Andhra style",
        "Banana leaf",
    ),
    "tiffin": (
        "Home style",
        "Monthly plans",
        "Lunch delivery",
        "Dinner delivery",
        "Healthy",
        "No onion-garlic option",
        "Office lunch",
        "Budget",
    ),
    "restaurant": (
        "North Indian",
        "Biryani",
        "Late night",
        "Chinese",
        "Family dining",
        "Tandoor",
        "Andhra",
        "Kebabs",
        "Thali",
    ),
    "cafe": (
        "Coffee",
        "Snacks",
        "Bakery",
        "Sandwiches",
        "Work friendly",
        "Desserts",
        "Tea",
        "Late night",
    ),
}

MENU_TEMPLATES: Final[dict[str, tuple[MenuTemplate, ...]]] = {
    "darshini": (
        MenuTemplate("Filter coffee", 20, True, False),
        MenuTemplate("Masala tea", 15, True, False),
        MenuTemplate("Badam milk", 25, True, False),
        MenuTemplate("Idli (2 pcs)", 35, True, True),
        MenuTemplate("Thatte idli", 45, True, False),
        MenuTemplate("Medu vada", 40, True, False),
        MenuTemplate("Idli vada", 50, True, True),
        MenuTemplate("Plain dosa", 55, True, False),
        MenuTemplate("Masala dosa", 70, True, True),
        MenuTemplate("Set dosa", 60, True, False),
        MenuTemplate("Rava dosa", 75, True, False),
        MenuTemplate("Onion rava dosa", 85, True, False),
        MenuTemplate("Benne masala dosa", 90, True, True),
        MenuTemplate("Mysore masala dosa", 85, True, False),
        MenuTemplate("Khara bath", 45, True, False),
        MenuTemplate("Kesari bath", 40, True, False),
        MenuTemplate("Chow chow bath", 60, True, False),
        MenuTemplate("Ven pongal", 50, True, False),
        MenuTemplate("Lemon rice", 45, True, False),
        MenuTemplate("Puliyogare", 50, True, False),
        MenuTemplate("Vangi bath", 55, True, False),
        MenuTemplate("Poori sagu", 60, True, True),
        MenuTemplate("Mangalore buns", 40, True, False),
        MenuTemplate("Bisi bele bath", 60, True, False),
    ),
    "mess_veg": (
        MenuTemplate("Full meals", 130, True, True),
        MenuTemplate("Special meals", 150, True, True),
        MenuTemplate("Mini meals", 85, True, True),
        MenuTemplate("Chapati meals", 95, True, True),
        MenuTemplate("Jolada rotti meals", 110, True, True),
        MenuTemplate("Ragi mudde meals", 100, True, True),
        MenuTemplate("Curd rice", 55, True, False),
        MenuTemplate("Bisi bele bath", 70, True, False),
        MenuTemplate("Lemon rice", 50, True, False),
        MenuTemplate("Tomato rice", 55, True, False),
        MenuTemplate("Ghee rice with dal", 75, True, False),
        MenuTemplate("Sambar rice", 60, True, False),
        MenuTemplate("Rasam rice", 50, True, False),
        MenuTemplate("Puliyogare", 55, True, False),
        MenuTemplate("Vangi bath", 60, True, False),
        MenuTemplate("Vegetable pulao", 80, True, False),
        MenuTemplate("Akki rotti", 60, True, False),
        MenuTemplate("Extra chapati (2 pcs)", 40, True, False),
        MenuTemplate("Holige (2 pcs)", 60, True, False),
        MenuTemplate("Payasa", 40, True, False),
        MenuTemplate("Extra curd", 40, True, False),
    ),
    "mess_nonveg": (
        MenuTemplate("Veg full meals", 120, True, True),
        MenuTemplate("Mini meals", 80, True, False),
        MenuTemplate("Chapati meals", 90, True, False),
        MenuTemplate("Chicken meals", 160, False, True),
        MenuTemplate("Fish meals", 180, False, True),
        MenuTemplate("Egg meals", 130, False, True),
        MenuTemplate("Chicken donne biryani", 170, False, True),
        MenuTemplate("Ragi mudde and nati koli saaru", 150, False, True),
        MenuTemplate("Chicken curry", 120, False, False),
        MenuTemplate("Chicken fry", 140, False, False),
        MenuTemplate("Fish fry", 120, False, False),
        MenuTemplate("Egg curry", 70, False, False),
        MenuTemplate("Egg bhurji", 60, False, False),
        MenuTemplate("Boiled eggs (2 pcs)", 40, False, False),
        MenuTemplate("Chicken kabab", 130, False, False),
        MenuTemplate("Neer dosa with chicken sukka", 150, False, False),
        MenuTemplate("Curd rice", 50, True, False),
        MenuTemplate("Ghee rice", 60, True, False),
        MenuTemplate("Lemon rice", 50, True, False),
        MenuTemplate("Sambar rice", 55, True, False),
        MenuTemplate("Akki rotti", 50, True, False),
        MenuTemplate("Payasa", 40, True, False),
    ),
    "tiffin": (
        MenuTemplate("Veg lunch box", 90, True, True),
        MenuTemplate("Chapati lunch box", 100, True, True),
        MenuTemplate("Mini meals box", 80, True, True),
        MenuTemplate("Dal khichdi", 65, True, True),
        MenuTemplate("Phulka and dal", 75, True, True),
        MenuTemplate("Curd rice box", 55, True, False),
        MenuTemplate("Bisi bele bath box", 70, True, False),
        MenuTemplate("Lemon rice box", 50, True, False),
        MenuTemplate("Ragi mudde meal box", 85, True, False),
        MenuTemplate("Vegetable pulao box", 80, True, False),
        MenuTemplate("Rajma chawal", 95, True, False),
        MenuTemplate("Paneer curry with rice", 120, True, False),
        MenuTemplate("Idli breakfast box", 45, True, False),
        MenuTemplate("Upma breakfast box", 45, True, False),
        # Plans: the generator relies on these exact names and the "Monthly lunch plan" prefix.
        MenuTemplate("Monthly lunch plan (26 meals)", 2600, True, False),
        MenuTemplate("Monthly lunch and dinner plan (52 meals)", 4900, True, False),
        MenuTemplate("Weekly lunch plan (6 meals)", 650, True, False),
    ),
    "restaurant_veg": (
        MenuTemplate("North Indian veg thali", 220, True, True),
        MenuTemplate("South Indian thali", 180, True, True),
        MenuTemplate("Paneer butter masala", 240, True, True),
        MenuTemplate("Kadai paneer", 250, True, False),
        MenuTemplate("Palak paneer", 240, True, False),
        MenuTemplate("Dal tadka", 160, True, False),
        MenuTemplate("Dal makhani", 200, True, False),
        MenuTemplate("Veg kolhapuri", 210, True, False),
        MenuTemplate("Mixed veg curry", 190, True, False),
        MenuTemplate("Chana masala", 180, True, False),
        MenuTemplate("Veg fried rice", 170, True, True),
        MenuTemplate("Veg hakka noodles", 170, True, False),
        MenuTemplate("Gobi manchurian", 160, True, False),
        MenuTemplate("Paneer tikka", 260, True, False),
        MenuTemplate("Butter naan (2 pcs)", 90, True, False),
        MenuTemplate("Tandoori roti (2 pcs)", 80, True, False),
        MenuTemplate("Jeera rice", 140, True, False),
        MenuTemplate("Veg biryani", 200, True, True),
        MenuTemplate("Paneer biryani", 240, True, False),
        MenuTemplate("Mushroom pepper fry", 210, True, False),
        MenuTemplate("Baby corn manchurian", 180, True, False),
        MenuTemplate("Gulab jamun (2 pcs)", 80, True, False),
        MenuTemplate("Fresh lime soda", 80, True, False),
        MenuTemplate("Chole bhature", 150, True, True),
    ),
    "restaurant_nonveg": (
        MenuTemplate("Chicken dum biryani", 260, False, True),
        MenuTemplate("Mutton biryani", 340, False, True),
        MenuTemplate("Egg biryani", 190, False, True),
        MenuTemplate("Butter chicken", 300, False, True),
        MenuTemplate("Chicken fried rice", 210, False, True),
        MenuTemplate("Chicken chettinad", 280, False, False),
        MenuTemplate("Andhra chicken curry", 270, False, False),
        MenuTemplate("Mutton rogan josh", 340, False, False),
        MenuTemplate("Mutton pepper fry", 330, False, False),
        MenuTemplate("Chicken 65", 230, False, False),
        MenuTemplate("Chicken kabab", 220, False, False),
        MenuTemplate("Tandoori chicken (half)", 290, False, False),
        MenuTemplate("Chicken tikka", 280, False, False),
        MenuTemplate("Fish curry", 260, False, False),
        MenuTemplate("Seer fish fry", 320, False, False),
        MenuTemplate("Egg curry", 150, False, False),
        MenuTemplate("Chicken hakka noodles", 220, False, False),
        MenuTemplate("Veg biryani", 180, True, False),
        MenuTemplate("Paneer butter masala", 240, True, False),
        MenuTemplate("Dal fry", 150, True, False),
        MenuTemplate("Veg fried rice", 170, True, False),
        MenuTemplate("Butter naan (2 pcs)", 90, True, False),
        MenuTemplate("Gobi manchurian", 160, True, False),
    ),
    "cafe": (
        MenuTemplate("Filter coffee", 30, True, False),
        MenuTemplate("Masala chai", 40, True, False),
        MenuTemplate("Cappuccino", 140, True, False),
        MenuTemplate("Cafe latte", 150, True, False),
        MenuTemplate("Cold coffee", 160, True, False),
        MenuTemplate("Lemon iced tea", 120, True, False),
        MenuTemplate("Veg sandwich", 90, True, True),
        MenuTemplate("Grilled cheese sandwich", 130, True, True),
        MenuTemplate("Chicken club sandwich", 190, False, True),
        MenuTemplate("Masala noodles", 80, True, True),
        MenuTemplate("Paneer kathi roll", 140, True, True),
        MenuTemplate("Chicken roll", 160, False, False),
        MenuTemplate("Veg puff", 30, True, False),
        MenuTemplate("Egg puff", 35, False, False),
        MenuTemplate("Veg burger", 120, True, False),
        MenuTemplate("Chocolate pastry", 90, True, False),
        MenuTemplate("Pineapple pastry", 70, True, False),
        MenuTemplate("Brownie", 110, True, False),
        MenuTemplate("Butter croissant", 120, True, False),
        MenuTemplate("Bun maska", 50, True, False),
        MenuTemplate("French fries", 110, True, False),
        MenuTemplate("Honey cake", 40, True, False),
        MenuTemplate("Penne arrabbiata", 220, True, False),
    ),
}

FOOD_DESCRIPTIONS: Final[dict[str, tuple[str, ...]]] = {
    "darshini": (
        "A busy standing-counter darshini near {area} serving crisp dosas, soft idlis and strong "
        "filter coffee from six in the morning.",
        "Quick, clean and cheap: office-goers in {area} grab a plate of idli vada and a coffee "
        "here before the morning rush.",
        "Family-run tiffin room known for its ghee-roasted benne dosa and a coconut chutney that "
        "usually runs out by eleven.",
        "Self-service darshini with token billing, steel tumblers of coffee and a different rice "
        "bath on the board every day.",
        "A small neighbourhood favourite in {area} where the masala dosa comes hot off the griddle "
        "in under five minutes.",
        "Breakfast and evening tiffin only, with crisp vadas, khara bath, kesari bath and coffee "
        "brewed fresh every hour.",
    ),
    "mess": (
        "Banana-leaf meals with unlimited rice, sambar, rasam and two palyas, served to a full "
        "house of bachelors every afternoon in {area}.",
        "A no-frills mess near {area} where the lunch menu changes daily and the curd rice is "
        "always generous.",
        "Home-style Karnataka meals cooked by one family, with ragi mudde on Wednesdays and holige "
        "on festival days.",
        "Andhra-style meals with fiery pappu, gongura pickle and unlimited rice; keep water handy, "
        "the spice is real.",
        "Popular with students and office-goers in {area} for its filling mini meals and quick "
        "service between noon and three.",
        "Simple, clean mess with steel plates, a fixed weekday menu and a Sunday special that "
        "sells out early.",
    ),
    "tiffin": (
        "Home cooks in {area} packing fresh lunch boxes every weekday, with rice, sambar, a palya, "
        "chapatis and curd.",
        "Monthly tiffin plans for working bachelors, delivered in steel dabbas by half past eleven "
        "and collected the next day.",
        "Light, low-oil home meals with the weekly menu shared every Sunday evening; skip a day "
        "with a single message.",
        "A husband-and-wife kitchen near {area} that cooks like home: soft phulkas, dal, seasonal "
        "sabzi and a small sweet on Fridays.",
        "Flexible lunch and dinner plans with no-onion, no-garlic options and pause-anytime "
        "billing for travel weeks.",
        "Reliable office lunch delivery to tech parks around {area}, with a fixed price and a menu "
        "that rotates every week.",
    ),
    "restaurant": (
        "A lively family restaurant in {area} known for its dum biryani, tandoori platters and "
        "late North Indian dinners.",
        "Spacious air-conditioned dining with a long North Indian and Chinese menu, popular for "
        "weekend family lunches.",
        "Generous thalis, rich gravies and crisp butter naan, served fast to the after-work crowd "
        "from the tech parks in {area}.",
        "Casual dining spot with Andhra and North Indian dishes, quick takeaway and a dessert "
        "counter near the billing desk.",
        "A reliable dinner place in {area} with consistent portions, fair prices and a tandoor "
        "that keeps going until eleven.",
        "Busy on weekends and calm on weekdays, with fried rice, noodles and curries that travel "
        "well for takeaway.",
    ),
    "cafe": (
        "A cosy coffee house in {area} with strong filter coffee, fresh puffs and enough plug "
        "points for a working afternoon.",
        "Neighbourhood bakery-cafe baking honey cake, buns and veg puffs every morning, with "
        "sandwiches and cold coffee all day.",
        "Small, bright cafe popular with remote workers for its cappuccino, grilled sandwiches and "
        "quiet corner tables.",
        "Late-evening hangout near {area} serving masala noodles, rolls and chai to students after "
        "classes.",
        "Bakes and brews under one roof: croissants, brownies, iced teas and a hand-written "
        "specials board by the door.",
        "A tiny cafe outside a tech park in {area}, known for quick espresso, bun maska and "
        "friendly staff who remember your order.",
    ),
}


# =============================================================================================
# Groceries
# =============================================================================================

_GRAINS: Final[str] = "Rice, flour & dal"
_OILS: Final[str] = "Oil, ghee & sugar"
_SPICES: Final[str] = "Spices & masala"
_BREWS: Final[str] = "Coffee & tea"
_DAIRY: Final[str] = "Dairy & batter"
_VEG: Final[str] = "Vegetables"
_FRUIT: Final[str] = "Fruit"
_BAKERY: Final[str] = "Bakery & breakfast"
_SNACKS: Final[str] = "Snacks"
_HOME: Final[str] = "Household & toiletries"

GROCERY_CATEGORIES: Final[tuple[str, ...]] = (
    _GRAINS,
    _OILS,
    _SPICES,
    _BREWS,
    _DAIRY,
    _VEG,
    _FRUIT,
    _BAKERY,
    _SNACKS,
    _HOME,
)

GROCERY_ITEMS: Final[tuple[GroceryTemplate, ...]] = (
    # --- The demo user's monthly list is built from these 22 names. Keep them first. ---
    GroceryTemplate("Sona masoori rice", "1 kg", _GRAINS, 72, "5 kg bag", 5, "staple"),
    GroceryTemplate("Toor dal", "1 kg", _GRAINS, 168, "2 kg pack", 2, "staple"),
    GroceryTemplate("Ragi flour", "1 kg", _GRAINS, 70, "5 kg bag", 5, "staple"),
    GroceryTemplate("Bombay rava", "500 g", _GRAINS, 34, "1 kg pack", 2, "staple"),
    GroceryTemplate("Sunflower oil", "1 L", _OILS, 160, "5 L can", 5, "staple"),
    GroceryTemplate("Coconut oil", "500 ml", _OILS, 210, "2 L jar", 4, "staple"),
    GroceryTemplate("Sugar", "1 kg", _OILS, 48, "5 kg bag", 5, "staple"),
    GroceryTemplate("Sambar powder", "100 g", _SPICES, 55, None, None, "spice"),
    GroceryTemplate("Filter coffee powder", "250 g", _BREWS, 180, "1 kg pack", 4, "packaged"),
    GroceryTemplate("Fresh curd", "500 g", _DAIRY, 34, None, None, "fresh"),
    GroceryTemplate("Idli & dosa batter", "1 kg", _DAIRY, 80, None, None, "fresh"),
    GroceryTemplate("Onion", "1 kg", _VEG, 40, None, None, "fresh"),
    GroceryTemplate("Tomato", "1 kg", _VEG, 32, None, None, "fresh"),
    GroceryTemplate("Potato", "1 kg", _VEG, 40, None, None, "fresh"),
    GroceryTemplate("Curry leaves", "1 bunch", _VEG, 10, None, None, "fresh"),
    GroceryTemplate("Coriander leaves", "1 bunch", _VEG, 15, None, None, "fresh"),
    GroceryTemplate("Yelakki bananas", "1 dozen", _FRUIT, 72, None, None, "fresh"),
    GroceryTemplate("Marie biscuits", "250 g", _SNACKS, 40, None, None, "packaged"),
    GroceryTemplate("Instant noodles", "280 g", _SNACKS, 60, None, None, "packaged"),
    GroceryTemplate("Bath soap", "125 g", _HOME, 45, "pack of 4", 4, "household"),
    GroceryTemplate("Toothpaste", "150 g", _HOME, 100, "pack of 2", 2, "household"),
    GroceryTemplate("Dishwash liquid", "500 ml", _HOME, 115, "2 L refill", 4, "household"),
    # --- Rice, flour & dal ---
    GroceryTemplate("Ponni boiled rice", "1 kg", _GRAINS, 64, "10 kg bag", 10, "staple"),
    GroceryTemplate("Basmati rice", "1 kg", _GRAINS, 140, "5 kg bag", 5, "staple"),
    GroceryTemplate("Idli rice", "1 kg", _GRAINS, 58, "5 kg bag", 5, "staple"),
    GroceryTemplate("Moong dal", "500 g", _GRAINS, 78, "2 kg pack", 4, "staple"),
    GroceryTemplate("Urad dal", "500 g", _GRAINS, 82, "2 kg pack", 4, "staple"),
    GroceryTemplate("Chana dal", "500 g", _GRAINS, 56, "2 kg pack", 4, "staple"),
    GroceryTemplate("Masoor dal", "500 g", _GRAINS, 62, "2 kg pack", 4, "staple"),
    GroceryTemplate("Whole wheat atta", "1 kg", _GRAINS, 58, "5 kg bag", 5, "staple"),
    GroceryTemplate("Idli rava", "500 g", _GRAINS, 36, "1 kg pack", 2, "staple"),
    GroceryTemplate("Thick poha", "500 g", _GRAINS, 42, "1 kg pack", 2, "staple"),
    GroceryTemplate("Besan (gram flour)", "500 g", _GRAINS, 62, "1 kg pack", 2, "staple"),
    GroceryTemplate("Rice flour", "500 g", _GRAINS, 36, "1 kg pack", 2, "staple"),
    # --- Oil, ghee & sugar ---
    GroceryTemplate("Groundnut oil", "1 L", _OILS, 195, "5 L can", 5, "staple"),
    GroceryTemplate("Gingelly oil", "500 ml", _OILS, 180, "1 L bottle", 2, "staple"),
    GroceryTemplate("Rice bran oil", "1 L", _OILS, 165, "5 L can", 5, "staple"),
    GroceryTemplate("Mustard oil", "1 L", _OILS, 185, None, None, "staple"),
    GroceryTemplate("Cold-pressed groundnut oil", "1 L", _OILS, 320, None, None, "staple"),
    GroceryTemplate("Cow ghee", "500 ml", _OILS, 340, "1 L tin", 2, "staple"),
    GroceryTemplate("Jaggery", "1 kg", _OILS, 80, None, None, "staple"),
    GroceryTemplate("Jaggery powder", "500 g", _OILS, 60, None, None, "staple"),
    GroceryTemplate("Iodised salt", "1 kg", _OILS, 28, None, None, "staple"),
    GroceryTemplate("Rock salt", "500 g", _OILS, 40, None, None, "staple"),
    GroceryTemplate("Brown sugar", "500 g", _OILS, 70, None, None, "staple"),
    GroceryTemplate("Rock sugar", "250 g", _OILS, 45, None, None, "staple"),
    GroceryTemplate("Honey", "250 g", _OILS, 140, None, None, "packaged"),
    # --- Spices & masala ---
    GroceryTemplate("Rasam powder", "100 g", _SPICES, 50, None, None, "spice"),
    GroceryTemplate("Turmeric powder", "100 g", _SPICES, 36, None, None, "spice"),
    GroceryTemplate("Red chilli powder", "100 g", _SPICES, 48, None, None, "spice"),
    GroceryTemplate("Coriander powder", "100 g", _SPICES, 34, None, None, "spice"),
    GroceryTemplate("Garam masala", "50 g", _SPICES, 50, None, None, "spice"),
    GroceryTemplate("Mustard seeds", "100 g", _SPICES, 22, None, None, "spice"),
    GroceryTemplate("Cumin seeds", "100 g", _SPICES, 68, None, None, "spice"),
    GroceryTemplate("Black pepper", "50 g", _SPICES, 62, None, None, "spice"),
    GroceryTemplate("Byadgi dry chillies", "100 g", _SPICES, 52, None, None, "spice"),
    GroceryTemplate("Tamarind", "250 g", _SPICES, 58, None, None, "spice"),
    GroceryTemplate("Asafoetida", "50 g", _SPICES, 78, None, None, "spice"),
    GroceryTemplate("Chicken masala", "100 g", _SPICES, 72, None, None, "spice"),
    GroceryTemplate("Bisi bele bath powder", "100 g", _SPICES, 68, None, None, "spice"),
    GroceryTemplate("Puliyogare powder", "100 g", _SPICES, 58, None, None, "spice"),
    GroceryTemplate("Fenugreek seeds", "100 g", _SPICES, 26, None, None, "spice"),
    # --- Coffee & tea ---
    GroceryTemplate("Pure coffee powder", "250 g", _BREWS, 220, "1 kg pack", 4, "packaged"),
    GroceryTemplate("Instant coffee", "100 g", _BREWS, 290, None, None, "packaged"),
    GroceryTemplate("Tea powder", "250 g", _BREWS, 135, "1 kg pack", 4, "packaged"),
    GroceryTemplate("Assam tea leaves", "250 g", _BREWS, 165, "1 kg pack", 4, "packaged"),
    GroceryTemplate("Green tea bags", "25 bags", _BREWS, 165, None, None, "packaged"),
    GroceryTemplate("Lemon tea bags", "25 bags", _BREWS, 145, None, None, "packaged"),
    GroceryTemplate("Tulsi tea bags", "25 bags", _BREWS, 150, None, None, "packaged"),
    GroceryTemplate("Chai masala", "50 g", _BREWS, 55, None, None, "packaged"),
    GroceryTemplate("Malt health drink", "500 g", _BREWS, 265, None, None, "packaged"),
    GroceryTemplate("Drinking chocolate", "200 g", _BREWS, 185, None, None, "packaged"),
    GroceryTemplate("Badam milk mix", "200 g", _BREWS, 145, None, None, "packaged"),
    GroceryTemplate("Cold coffee premix", "200 g", _BREWS, 175, None, None, "packaged"),
    GroceryTemplate("Tea premix sachets", "10 sachets", _BREWS, 95, None, None, "packaged"),
    GroceryTemplate("Ragi malt mix", "500 g", _BREWS, 155, None, None, "packaged"),
    GroceryTemplate("Coffee dip bags", "10 bags", _BREWS, 125, None, None, "packaged"),
    # --- Dairy & batter ---
    GroceryTemplate("Toned milk", "500 ml", _DAIRY, 28, None, None, "fresh"),
    GroceryTemplate("Full cream milk", "500 ml", _DAIRY, 36, None, None, "fresh"),
    GroceryTemplate("Double toned milk", "500 ml", _DAIRY, 26, None, None, "fresh"),
    GroceryTemplate("Buttermilk", "500 ml", _DAIRY, 20, None, None, "fresh"),
    GroceryTemplate("Set curd cup", "200 g", _DAIRY, 22, None, None, "fresh"),
    GroceryTemplate("Ragi dosa batter", "1 kg", _DAIRY, 95, None, None, "fresh"),
    GroceryTemplate("Adai batter", "500 g", _DAIRY, 60, None, None, "fresh"),
    GroceryTemplate("Paneer", "200 g", _DAIRY, 95, None, None, "fresh"),
    GroceryTemplate("Butter", "100 g", _DAIRY, 62, None, None, "fresh"),
    GroceryTemplate("Cheese slices", "200 g", _DAIRY, 150, None, None, "fresh"),
    GroceryTemplate("Eggs", "1 dozen", _DAIRY, 84, None, None, "fresh"),
    GroceryTemplate("Fresh cream", "200 ml", _DAIRY, 72, None, None, "fresh"),
    GroceryTemplate("Sweet lassi", "200 ml", _DAIRY, 25, None, None, "fresh"),
    GroceryTemplate("Flavoured milk", "200 ml", _DAIRY, 32, None, None, "fresh"),
    # --- Vegetables ---
    GroceryTemplate("Green chillies", "250 g", _VEG, 20, None, None, "fresh"),
    GroceryTemplate("Ginger", "250 g", _VEG, 35, None, None, "fresh"),
    GroceryTemplate("Garlic", "250 g", _VEG, 70, None, None, "fresh"),
    GroceryTemplate("Carrot", "500 g", _VEG, 32, None, None, "fresh"),
    GroceryTemplate("Beans", "500 g", _VEG, 40, None, None, "fresh"),
    GroceryTemplate("Capsicum", "500 g", _VEG, 45, None, None, "fresh"),
    GroceryTemplate("Brinjal", "500 g", _VEG, 30, None, None, "fresh"),
    GroceryTemplate("Cabbage", "1 pc", _VEG, 30, None, None, "fresh"),
    GroceryTemplate("Drumsticks", "250 g", _VEG, 30, None, None, "fresh"),
    GroceryTemplate("Palak", "1 bunch", _VEG, 20, None, None, "fresh"),
    GroceryTemplate("Lemons", "4 pcs", _VEG, 24, None, None, "fresh"),
    # --- Fruit ---
    GroceryTemplate("Robusta bananas", "1 dozen", _FRUIT, 50, None, None, "fresh"),
    GroceryTemplate("Shimla apples", "1 kg", _FRUIT, 180, None, None, "fresh"),
    GroceryTemplate("Papaya", "1 pc", _FRUIT, 55, None, None, "fresh"),
    GroceryTemplate("Pomegranate", "500 g", _FRUIT, 95, None, None, "fresh"),
    GroceryTemplate("Watermelon", "1 pc", _FRUIT, 70, None, None, "fresh"),
    GroceryTemplate("Mosambi", "1 kg", _FRUIT, 80, None, None, "fresh"),
    GroceryTemplate("Nagpur oranges", "1 kg", _FRUIT, 110, None, None, "fresh"),
    GroceryTemplate("Guava", "500 g", _FRUIT, 45, None, None, "fresh"),
    GroceryTemplate("Green grapes", "500 g", _FRUIT, 65, None, None, "fresh"),
    GroceryTemplate("Pineapple", "1 pc", _FRUIT, 60, None, None, "fresh"),
    GroceryTemplate("Sapota", "500 g", _FRUIT, 50, None, None, "fresh"),
    GroceryTemplate("Badami mangoes", "1 kg", _FRUIT, 160, None, None, "fresh"),
    GroceryTemplate("Tender coconut", "1 pc", _FRUIT, 50, None, None, "fresh"),
    GroceryTemplate("Coconut", "1 pc", _FRUIT, 40, None, None, "fresh"),
    GroceryTemplate("Pears", "500 g", _FRUIT, 90, None, None, "fresh"),
    # --- Bakery & breakfast ---
    GroceryTemplate("Sandwich bread", "400 g", _BAKERY, 45, None, None, "fresh"),
    GroceryTemplate("Brown bread", "400 g", _BAKERY, 55, None, None, "fresh"),
    GroceryTemplate("Pav buns", "6 pcs", _BAKERY, 35, None, None, "fresh"),
    GroceryTemplate("Plain tea cake", "250 g", _BAKERY, 70, None, None, "fresh"),
    GroceryTemplate("Malabar parotta", "5 pcs", _BAKERY, 75, None, None, "fresh"),
    GroceryTemplate("Ready chapatis", "10 pcs", _BAKERY, 90, None, None, "fresh"),
    GroceryTemplate("Rusk", "300 g", _BAKERY, 60, None, None, "packaged"),
    GroceryTemplate("Corn flakes", "500 g", _BAKERY, 195, None, None, "packaged"),
    GroceryTemplate("Rolled oats", "1 kg", _BAKERY, 195, None, None, "packaged"),
    GroceryTemplate("Muesli", "500 g", _BAKERY, 270, None, None, "packaged"),
    GroceryTemplate("Ragi flakes", "500 g", _BAKERY, 125, None, None, "packaged"),
    GroceryTemplate("Peanut butter", "350 g", _BAKERY, 185, None, None, "packaged"),
    GroceryTemplate("Mixed fruit jam", "200 g", _BAKERY, 90, None, None, "packaged"),
    GroceryTemplate("Rava idli mix", "500 g", _BAKERY, 115, None, None, "packaged"),
    GroceryTemplate("Instant upma mix", "200 g", _BAKERY, 75, None, None, "packaged"),
    GroceryTemplate("Vermicelli", "400 g", _BAKERY, 50, None, None, "packaged"),
    # --- Snacks ---
    GroceryTemplate("Glucose biscuits", "250 g", _SNACKS, 30, None, None, "packaged"),
    GroceryTemplate("Cream biscuits", "150 g", _SNACKS, 35, None, None, "packaged"),
    GroceryTemplate("Masala peanuts", "200 g", _SNACKS, 50, None, None, "packaged"),
    GroceryTemplate("Banana chips", "200 g", _SNACKS, 85, None, None, "packaged"),
    GroceryTemplate("Potato chips", "100 g", _SNACKS, 45, None, None, "packaged"),
    GroceryTemplate("Spicy mixture", "200 g", _SNACKS, 60, None, None, "packaged"),
    GroceryTemplate("Khara boondi", "200 g", _SNACKS, 55, None, None, "packaged"),
    GroceryTemplate("Rice chakli", "200 g", _SNACKS, 70, None, None, "packaged"),
    GroceryTemplate("Nippattu", "200 g", _SNACKS, 65, None, None, "packaged"),
    GroceryTemplate("Kodubale", "200 g", _SNACKS, 70, None, None, "packaged"),
    GroceryTemplate("Roasted chana", "200 g", _SNACKS, 45, None, None, "packaged"),
    GroceryTemplate("Roasted makhana", "100 g", _SNACKS, 125, None, None, "packaged"),
    GroceryTemplate("Milk chocolate bar", "50 g", _SNACKS, 50, None, None, "packaged"),
    GroceryTemplate("Cashews", "250 g", _SNACKS, 260, None, None, "packaged"),
    # --- Household & toiletries ---
    GroceryTemplate("Detergent powder", "1 kg", _HOME, 125, "4 kg bag", 4, "household"),
    GroceryTemplate("Liquid detergent", "1 L", _HOME, 215, "2 L refill", 2, "household"),
    GroceryTemplate("Dishwash bar", "300 g", _HOME, 32, "pack of 3", 3, "household"),
    GroceryTemplate("Floor cleaner", "1 L", _HOME, 195, "2 L can", 2, "household"),
    GroceryTemplate("Toilet cleaner", "500 ml", _HOME, 110, "pack of 3", 3, "household"),
    GroceryTemplate("Shampoo", "180 ml", _HOME, 175, None, None, "household"),
    GroceryTemplate("Toothbrush", "1 pc", _HOME, 40, "pack of 4", 4, "household"),
    GroceryTemplate("Garbage bags", "30 pcs", _HOME, 95, None, None, "household"),
    GroceryTemplate("Mosquito repellent refill", "1 pc", _HOME, 85, None, None, "household"),
    GroceryTemplate("Hand wash", "200 ml", _HOME, 99, None, None, "household"),
    GroceryTemplate("Scrub sponge", "3 pcs", _HOME, 50, None, None, "household"),
    GroceryTemplate("Shaving cream", "70 g", _HOME, 95, None, None, "household"),
    GroceryTemplate("Deodorant", "150 ml", _HOME, 210, None, None, "household"),
)


# =============================================================================================
# Products
# =============================================================================================

PRODUCT_CATEGORIES: Final[dict[str, ProductCategoryVocab]] = {
    "shirts": ProductCategoryVocab(
        label="Shirts",
        brands=(
            "Urbanthread",
            "Weftwise",
            "Cotton Kite",
            "Collarcraft",
            "Kapas Row",
            "Tailor & Tide",
            "Loomline",
        ),
        styles=(
            "Classic",
            "Slim-fit",
            "Regular-fit",
            "Oxford weave",
            "Linen-blend",
            "Wrinkle-free",
            "Breathable",
            "Button-down",
            "Mandarin-collar",
            "Checked",
            "Striped",
            "Solid",
        ),
        items=(
            "Cotton Formal Shirt",
            "Linen Casual Shirt",
            "Oxford Button-Down Shirt",
            "Checked Flannel Shirt",
            "Striped Office Shirt",
            "Mandarin Collar Shirt",
            "Denim Casual Shirt",
            "Printed Half-Sleeve Shirt",
        ),
        mrp_range=(799, 2499),
        descriptions=(
            "The {brand} {name} is cut from soft, breathable cotton that stays crisp through a "
            "long office day and a crowded metro ride.",
            "{brand} pairs a clean collar with easy-care fabric in the {name}, so it goes from "
            "wash to wear with very little ironing.",
            "A versatile {name} from {brand} that works with chinos for client meetings and with "
            "jeans for weekend plans.",
            "{brand} finishes the {name} with reinforced seams, a curved hem and colours that "
            "hold up wash after wash.",
            "Light enough for Bangalore afternoons, the {brand} {name} keeps its shape from the "
            "first standup to the last call.",
        ),
        highlights=(
            "100% cotton fabric",
            "Machine washable",
            "Wrinkle-resistant finish",
            "Breathable weave",
            "Reinforced stitching",
            "Colourfast dyes",
            "Curved hem",
            "Full sleeves",
            "Spare button included",
            "Pre-shrunk fabric",
            "Easy to iron",
            "Office and casual wear",
        ),
    ),
    "jeans": ProductCategoryVocab(
        label="Jeans",
        brands=(
            "Rivet & Rye",
            "Bluegrain",
            "Selvage Street",
            "Copperline Denim",
            "Hustle Blue",
            "Ridgefold",
            "Denwala",
        ),
        styles=(
            "Slim-fit",
            "Straight-fit",
            "Tapered",
            "Relaxed",
            "Stretch",
            "Mid-rise",
            "Dark wash",
            "Light wash",
            "Distressed",
            "Clean-look",
            "Raw denim",
        ),
        items=(
            "Slim Fit Stretch Jeans",
            "Straight Fit Classic Jeans",
            "Tapered Fit Dark Wash Jeans",
            "Relaxed Fit Carpenter Jeans",
            "Light Wash Everyday Jeans",
            "Raw Denim Selvedge Jeans",
            "Stretch Comfort Jeans",
        ),
        mrp_range=(1299, 3499),
        descriptions=(
            "The {brand} {name} uses cotton-rich stretch denim that moves with you on a "
            "two-wheeler and still looks sharp at work.",
            "{brand} cuts the {name} with a modern fit, sturdy rivets and a wash that fades "
            "evenly over time.",
            "A dependable {name} from {brand}, built with double-stitched seams and deep pockets "
            "for a phone, wallet and keys.",
            "Soft from the first wear, the {brand} {name} pairs easily with a tee for weekends or "
            "a shirt for Fridays at work.",
        ),
        highlights=(
            "Cotton-rich stretch denim",
            "Five-pocket design",
            "Metal button closure",
            "Zip fly",
            "Fade-resistant wash",
            "Reinforced belt loops",
            "Comfort waistband",
            "Machine washable",
            "All-day flexibility",
            "Mid-rise waist",
            "Durable double stitching",
        ),
    ),
    "formalShoes": ProductCategoryVocab(
        label="Formal shoes",
        brands=(
            "Stridewell",
            "Oxbury",
            "Ferro Lane",
            "Cobbler & Crest",
            "Brogueline",
            "Heelward",
            "Lastmark",
        ),
        styles=(
            "Classic",
            "Polished",
            "Cushioned",
            "Lightweight",
            "Slip-resistant",
            "Water-resistant",
            "Hand-finished",
            "Lace-up",
            "Slip-on",
            "Burnished",
            "Padded-collar",
        ),
        items=(
            "Oxford Leather Formal Shoes",
            "Derby Formal Shoes",
            "Brogue Lace-Up Shoes",
            "Monk Strap Formal Shoes",
            "Leather Loafers",
            "Cap Toe Oxford Shoes",
            "Chelsea Formal Boots",
        ),
        mrp_range=(1499, 4999),
        descriptions=(
            "The {brand} {name} combines a polished upper with a cushioned insole that stays "
            "comfortable through long office days.",
            "{brand} builds the {name} on an anti-slip rubber sole, so wet monsoon footpaths are "
            "less of a worry.",
            "Smart enough for interviews and client visits, the {name} from {brand} takes a "
            "shine well and holds its shape.",
            "A lightweight {name} by {brand} with a breathable lining and a padded collar for "
            "comfortable all-day wear.",
        ),
        highlights=(
            "Genuine leather upper",
            "Cushioned insole",
            "Anti-slip rubber sole",
            "Breathable lining",
            "Lightweight build",
            "Stitched welt look",
            "Padded heel collar",
            "Polish-ready finish",
            "Shock-absorbing heel",
            "Office-ready design",
            "Easy lace-up fit",
        ),
    ),
    "backpacks": ProductCategoryVocab(
        label="Backpacks",
        brands=(
            "Packwell",
            "Trailcase",
            "Ruckline",
            "Hauler & Hike",
            "Satchel Street",
            "Rangeway",
            "Carryall Works",
        ),
        styles=(
            "Laptop",
            "Water-resistant",
            "Anti-theft",
            "Lightweight",
            "Expandable",
            "Minimal",
            "Commuter",
            "Roll-top",
            "Padded",
            "Travel",
        ),
        items=(
            "Laptop Backpack 30L",
            "Anti-Theft Office Backpack",
            "Everyday Commuter Backpack",
            "Travel Backpack 40L",
            "Roll-Top Daypack",
            "Slim Laptop Sleeve Backpack",
            "Hiking Daypack 25L",
        ),
        mrp_range=(999, 3999),
        descriptions=(
            "The {brand} {name} keeps a laptop, charger and lunch box organised, with padded "
            "straps for the daily commute.",
            "{brand} designed the {name} with water-resistant fabric and a hidden pocket for "
            "your phone and wallet on crowded buses.",
            "A sturdy {name} from {brand} that slides easily under an office desk and handles "
            "weekend trips just as well.",
            "Light on the shoulders and roomy inside, the {brand} {name} has a breathable back "
            "panel for warm afternoons.",
        ),
        highlights=(
            "Fits 15.6-inch laptop",
            "Water-resistant fabric",
            "Padded shoulder straps",
            "Hidden anti-theft pocket",
            "USB charging port",
            "Breathable back panel",
            "Rain cover included",
            "Bottle side pockets",
            "Luggage trolley strap",
            "Multiple organiser pockets",
            "Lightweight frame",
            "Durable lockable zips",
        ),
    ),
    "earphones": ProductCategoryVocab(
        label="Earphones",
        brands=(
            "Tunely",
            "Bassline Audio",
            "Hum & Hertz",
            "Decibelle",
            "Pulsetone",
            "Notewise",
            "Wavecrest",
        ),
        styles=(
            "Wireless",
            "True wireless",
            "Neckband",
            "Wired",
            "Noise-cancelling",
            "Low-latency",
            "Sweat-resistant",
            "Bass-boosted",
            "Lightweight",
            "Dual-device",
        ),
        items=(
            "True Wireless Earbuds",
            "Bluetooth Neckband Earphones",
            "Wired In-Ear Earphones with Mic",
            "Noise Cancelling Earbuds",
            "Sports Wireless Earbuds",
            "Gaming Earbuds",
            "Open-Ear Wireless Earphones",
        ),
        mrp_range=(799, 4999),
        descriptions=(
            "The {brand} {name} delivers punchy bass, clear calls and enough battery to last a "
            "full week of commutes.",
            "{brand} tuned the {name} for long work calls, with noise-reducing mics and a snug, "
            "lightweight fit.",
            "A pocket-friendly {name} from {brand} with fast charging, touch controls and quick "
            "pairing with your phone and laptop.",
            "Sweat-resistant and secure, the {brand} {name} stays put through gym sessions and "
            "evening runs around the lake.",
        ),
        highlights=(
            "Up to 40 hours playback",
            "Fast charging in 10 minutes",
            "Active noise cancellation",
            "Clear calls with ENC",
            "IPX5 sweat resistance",
            "Low-latency gaming mode",
            "Bluetooth 5.4 connectivity",
            "Touch controls",
            "Dual-device pairing",
            "Deep bass drivers",
            "Type-C charging",
            "Ergonomic snug fit",
            "Voice assistant support",
        ),
    ),
    "watches": ProductCategoryVocab(
        label="Watches",
        brands=(
            "Tickwell",
            "Meridian Hours",
            "Dialcraft",
            "Chrono Kite",
            "Hourline",
            "Quartzwood",
            "Brass Hour",
        ),
        styles=(
            "Analog",
            "Digital",
            "Chronograph",
            "Minimalist",
            "Stainless steel",
            "Leather strap",
            "Sporty",
            "Smart",
            "Water-resistant",
            "Classic dial",
            "Mesh strap",
        ),
        items=(
            "Analog Leather Strap Watch",
            "Chronograph Steel Watch",
            "Minimalist Mesh Strap Watch",
            "Digital Sports Watch",
            "Smart Fitness Watch",
            "Classic Day-Date Watch",
            "Skeleton Dial Watch",
        ),
        mrp_range=(999, 7999),
        descriptions=(
            "The {brand} {name} pairs a clean dial with a sturdy case, an easy match for both "
            "office shirts and weekend tees.",
            "{brand} finishes the {name} with scratch-resistant glass and a comfortable strap "
            "made for everyday wear.",
            "A dependable {name} from {brand} that keeps accurate time and shrugs off rain, sweat "
            "and the occasional splash.",
            "Understated and well built, the {brand} {name} makes a thoughtful first good watch "
            "for a new job.",
        ),
        highlights=(
            "Water-resistant to 50 m",
            "Scratch-resistant mineral glass",
            "Precise quartz movement",
            "Genuine leather strap",
            "Stainless steel case",
            "Luminous hands",
            "Day and date display",
            "Up to 10-day battery",
            "Heart-rate and SpO2 tracking",
            "Quick-release strap",
            "Two-year warranty",
            "Lightweight case",
        ),
    ),
    "raincoats": ProductCategoryVocab(
        label="Raincoats",
        brands=(
            "Monsoon Mate",
            "Drizzle Guard",
            "Rainward",
            "Puddleproof",
            "Cloudburst Co.",
            "Varsha Gear",
            "Stormstitch",
        ),
        styles=(
            "Hooded",
            "Two-piece",
            "Long",
            "Packable",
            "Reflective",
            "Breathable",
            "Heavy-duty",
            "Lightweight",
            "Biker",
            "Reversible",
        ),
        items=(
            "Two-Piece Rain Suit",
            "Hooded Long Raincoat",
            "Packable Rain Jacket",
            "Biker Rain Suit with Pant",
            "Reflective Rain Poncho",
            "Windcheater Rain Jacket",
        ),
        mrp_range=(699, 2499),
        descriptions=(
            "The {brand} {name} keeps you and your office clothes dry through heavy Bangalore "
            "downpours on a two-wheeler.",
            "{brand} seals every seam of the {name} and adds reflective strips for safer rides on "
            "dark, wet evenings.",
            "A packable {name} from {brand} that folds into its own pouch and lives under the "
            "scooter seat all monsoon.",
            "Light, breathable and quick to dry, the {brand} {name} does not trap heat on muggy "
            "June afternoons.",
        ),
        highlights=(
            "Fully taped waterproof seams",
            "Adjustable hood",
            "Reflective strips",
            "Carry pouch included",
            "Elastic cuffs",
            "Breathable mesh lining",
            "Quick-dry fabric",
            "Pant with elastic waist",
            "Fits over office wear",
            "Zip and button closure",
            "Windproof outer shell",
        ),
    ),
    "helmets": ProductCategoryVocab(
        label="Helmets",
        brands=(
            "Kavach Gear",
            "Shieldline",
            "Crestguard",
            "Roadhelm",
            "Halo Ride",
            "Domeforge",
            "Ironcrown",
        ),
        styles=(
            "Full-face",
            "Open-face",
            "Flip-up",
            "ISI-certified",
            "Matte",
            "Glossy",
            "Ventilated",
            "Lightweight",
            "Dual-visor",
            "Anti-fog",
        ),
        items=(
            "Full Face Helmet",
            "Open Face Helmet",
            "Flip-Up Modular Helmet",
            "Dual Visor Full Face Helmet",
            "Half Face City Helmet",
            "Off-Road Motocross Helmet",
        ),
        mrp_range=(999, 3999),
        descriptions=(
            "The {brand} {name} combines an ISI-certified shell with a scratch-resistant visor "
            "for safe daily city rides.",
            "{brand} lines the {name} with a removable, washable liner and front vents that keep "
            "you cool in traffic.",
            "A lightweight {name} from {brand} with a quick-release buckle and an anti-fog visor "
            "for rainy mornings.",
            "Built for long commutes, the {brand} {name} balances protection, ventilation and "
            "comfort without feeling heavy.",
        ),
        highlights=(
            "ISI certified",
            "Scratch-resistant visor",
            "Anti-fog visor",
            "Removable washable lining",
            "Quick-release buckle",
            "Multi-density EPS liner",
            "Front and rear air vents",
            "Lightweight ABS shell",
            "Speaker pockets for intercom",
            "Aerodynamic shell design",
            "Reflective rear decal",
        ),
    ),
}


# =============================================================================================
# Homes
# =============================================================================================

PG_NAME_CORES: Final[tuple[str, ...]] = (
    "Green Leaf",
    "Sri Sai",
    "Comfort Nest",
    "Sunrise",
    "Lakeview",
    "Sri Balaji",
    "Silver Oak",
    "Blue Bell",
    "Sri Venkateshwara",
    "Happy Home",
    "Golden Nest",
    "Sri Manjunatha",
    "Coconut Grove",
    "Lotus",
    "Paradise",
    "Classic",
    "Elite",
    "Tulip",
    "Maple",
    "Sai Krupa",
    "Sri Lakshmi",
    "Harmony",
    "Orchid",
    "Gokul",
)

PG_NAME_SUFFIXES: Final[tuple[str, ...]] = (
    "PG for Men",
    "Gents PG",
    "Men's PG",
    "Ladies PG",
    "Co-ed PG",
    "Residency",
    "Stay",
    "Comforts",
)

COLIVING_BRANDS: Final[tuple[str, ...]] = (
    "NestNook",
    "Habitat Commons",
    "Kinship Living",
    "Roomly",
    "Hive & Hearth",
    "Bunkhaus",
    "Sojourn Spaces",
    "Livewell Lofts",
    "UrbanDen Living",
    "Haven House",
    "Threshold Co-living",
    "Courtyard Collective",
)

FLAT_NAME_PATTERNS: Final[tuple[str, ...]] = (
    "Private room in {bhk}BHK, {locality}",
    "Shared room in {bhk}BHK, {locality}",
    "Room in a {bhk}BHK near {locality}",
    "Furnished room in {bhk}BHK flat, {locality}",
    "Flatmate wanted for {bhk}BHK in {locality}",
    "Bachelor-friendly room in {bhk}BHK, {locality}",
    "Room with balcony in {bhk}BHK, {locality}",
)

LOCALITIES: Final[dict[str, tuple[str, ...]]] = {
    "area_hsr": ("Sector 1", "Sector 2", "Sector 6", "27th Main", "Agara"),
    "area_koramangala": ("1st Block", "4th Block", "5th Block", "6th Block", "80 Feet Road"),
    "area_btm": ("BTM 1st Stage", "BTM 2nd Stage", "16th Main", "Tavarekere", "Madiwala"),
    "area_bellandur": (
        "Bellandur Gate",
        "Kariyammana Agrahara",
        "Devarabeesanahalli",
        "Ambalipura",
        "Green Glen Layout",
    ),
    "area_marathahalli": (
        "Munnekollal",
        "Kundalahalli Gate",
        "Marathahalli Bridge",
        "Chinnappanahalli",
        "Outer Ring Road",
    ),
    "area_whitefield": ("ITPL Main Road", "Hoodi", "Brookefield", "Kundalahalli", "Varthur Road"),
    "area_ecity": (
        "Electronic City Phase 1",
        "Electronic City Phase 2",
        "Neeladri Nagar",
        "Doddathogur",
        "Hosa Road",
    ),
    "area_indiranagar": (
        "HAL 2nd Stage",
        "100 Feet Road",
        "12th Main",
        "CMH Road",
        "Defence Colony",
    ),
    "area_jayanagar": ("4th Block", "9th Block", "4th T Block", "11th Main", "South End Circle"),
    "area_kadubeesanahalli": ("Panathur Main Road", "Kadubeesanahalli Main Road", "Balagere"),
    "area_sarjapur": (
        "Sarjapur Road",
        "Kaikondrahalli",
        "Dommasandra",
        "Doddakannelli",
        "Carmelaram",
    ),
    "area_domlur": ("Domlur Layout", "Domlur 2nd Stage", "Old Airport Road", "Kodihalli"),
    "area_jpnagar": (
        "JP Nagar 1st Phase",
        "JP Nagar 2nd Phase",
        "JP Nagar 6th Phase",
        "24th Main",
        "Puttenahalli",
    ),
    "area_mahadevapura": (
        "Doddanekundi",
        "Garudacharpalya",
        "Mahadevapura Main Road",
        "Kaggadasapura",
    ),
    "area_bommanahalli": (
        "Hosur Road",
        "Begur Road",
        "Hongasandra",
        "Garvebhavipalya",
        "Mangammanapalya",
    ),
}

PG_AMENITIES: Final[tuple[str, ...]] = (
    "Wi-Fi",
    "Meals included",
    "Housekeeping",
    "Laundry",
    "Hot water",
    "Power backup",
    "RO drinking water",
    "CCTV",
    "Attached bathroom",
    "Washing machine",
    "Two-wheeler parking",
    "Refrigerator",
    "TV in common area",
)

COLIVING_AMENITIES: Final[tuple[str, ...]] = (
    "High-speed Wi-Fi",
    "Fully furnished rooms",
    "Daily housekeeping",
    "Weekly linen change",
    "Community events",
    "Gym access",
    "Rooftop lounge",
    "Work desk and chair",
    "App-based service requests",
    "Biometric entry",
    "Power backup",
    "Meal plans available",
    "Laundry service",
    "Gaming zone",
)

FLAT_AMENITIES: Final[tuple[str, ...]] = (
    "Semi-furnished",
    "Fully furnished",
    "Modular kitchen",
    "Balcony",
    "Covered parking",
    "Lift",
    "24x7 security",
    "Power backup",
    "Washing machine",
    "Refrigerator",
    "Gas pipeline",
    "Gated community",
    "Part-time cook",
)

HOME_DESCRIPTIONS: Final[dict[str, tuple[str, ...]]] = {
    "pg": (
        "A clean, well-run PG in {area} with daily housekeeping, home-style food and a short walk "
        "to the main road.",
        "Popular with working bachelors, this PG in {area} offers furnished rooms, fast Wi-Fi and "
        "hot water round the clock.",
        "A quiet residential lane in {area}, friendly owners, tasty South Indian food and strict "
        "but fair house rules.",
        "Budget-friendly PG with sharing options, washing machine access and quick buses from "
        "{area} to the tech parks.",
        "Spacious rooms with good ventilation, a lift and power backup, run by a family that lives "
        "on the ground floor.",
        "Simple, safe and close to everything in {area}: groceries, darshinis and the bus stop are "
        "all within five minutes.",
    ),
    "coliving": (
        "A design-forward co-living space in {area} with fully furnished rooms, a shared kitchen "
        "and a lively community.",
        "Move-in ready rooms with work desks, fast Wi-Fi and weekly housekeeping, a short ride "
        "from the tech corridor in {area}.",
        "Community dinners, a rooftop lounge and app-based service requests make settling into "
        "{area} much easier.",
        "Private rooms with shared common areas, a small gym and flexible stays, ideal for people "
        "new to Bangalore.",
        "Professionally managed co-living with transparent pricing, no brokerage and everything "
        "included in one monthly bill.",
        "Bright, modern rooms in {area} with a games area, laundry service and housemates who "
        "mostly work in tech.",
    ),
    "sharedFlat": (
        "A friendly flat in {area} shared with two working professionals, with a fully equipped "
        "kitchen and a sunny balcony.",
        "Spacious room in a gated apartment in {area} with a lift, power backup and covered "
        "parking for a two-wheeler.",
        "Looking for a tidy, easy-going flatmate; the flat has a cook on weekdays and Wi-Fi "
        "already set up.",
        "Semi-furnished room in a quiet society, close to the feeder bus and a five-minute walk "
        "from the {area} market.",
        "Shared flat with split bills, a washing machine, a refrigerator and a reasonable landlord "
        "who fixes things quickly.",
        "Bachelor-friendly flat in {area} with separate bathrooms, a gas pipeline and a security "
        "guard at the gate all day.",
    ),
}

PG_FOOD_DETAILS: Final[tuple[str, ...]] = (
    "Breakfast and dinner on weekdays, all three meals on Sundays. South Indian veg menu.",
    "Three veg meals a day with chapati at dinner. Non-veg on Wednesdays and Sundays.",
    "Breakfast and dinner included; a packed lunch is available for a small extra charge.",
    "North and South Indian veg menu that rotates weekly. Tea and snacks in the evening.",
    "All meals included. Egg dishes three times a week and chicken curry on Sundays.",
    "Food not included. Shared kitchen with a gas stove, refrigerator and utensils.",
    "Breakfast only, with tea or coffee. Several darshinis and messes nearby.",
)


# =============================================================================================
# Expenses
# =============================================================================================

EXPENSE_TEMPLATES: Final[dict[str, tuple[ExpenseTemplate, ...]]] = {
    "rent": (
        ExpenseTemplate("Rent - {month}", None, 9000, 16000, "recurring"),
        ExpenseTemplate("Rent - {month}", "House owner", 9000, 16000, "recurring"),
        ExpenseTemplate("PG rent - {month}", None, 8000, 14000, "recurring"),
    ),
    "food": (
        ExpenseTemplate("Breakfast - idli vada", "{eatery}", 50, 90, "manual"),
        ExpenseTemplate("Breakfast - masala dosa", "{eatery}", 60, 110, "manual"),
        ExpenseTemplate("Lunch - full meals", "{eatery}", 90, 150, "manual"),
        ExpenseTemplate("Lunch - mini meals", "{eatery}", 70, 110, "manual"),
        ExpenseTemplate("Dinner at {eatery}", "{eatery}", 150, 350, "manual"),
        ExpenseTemplate("Weekend brunch at {eatery}", "{eatery}", 180, 400, "manual"),
        ExpenseTemplate("Coffee and snacks", "{eatery}", 30, 120, "manual"),
        ExpenseTemplate("Evening chai and biscuits", "Corner tea stall", 20, 60, "manual"),
        ExpenseTemplate("Sugarcane juice", "Kabbu Juice Corner", 30, 60, "manual"),
        ExpenseTemplate("Dinner delivery", "FeastDrop", 180, 450, "delivery"),
        ExpenseTemplate("Late-night biryani delivery", "QuickBite", 220, 450, "delivery"),
        ExpenseTemplate("Lunch delivery", "DabbaRun", 180, 350, "delivery"),
        ExpenseTemplate("Weekend dinner delivery", "FeastDrop", 250, 450, "delivery"),
    ),
    "groceries": (
        ExpenseTemplate("ZipCart top-up", "ZipCart", 150, 600, "manual"),
        ExpenseTemplate("Late-night ZipCart order", "ZipCart", 150, 500, "manual"),
        ExpenseTemplate("Vegetables", "Weekly vegetable santhe", 120, 350, "manual"),
        ExpenseTemplate("Milk and curd", "Corner milk booth", 40, 120, "manual"),
        ExpenseTemplate("Kirana run", "Sri Lakshmi Kirana", 100, 450, "manual"),
        ExpenseTemplate("Eggs and bread", "Sri Lakshmi Kirana", 80, 160, "manual"),
        ExpenseTemplate("Fruits", "Corner fruit stall", 60, 250, "manual"),
        ExpenseTemplate("Weekend groceries", "FreshAisle Supermarket", 400, 1500, "manual"),
        ExpenseTemplate("Monthly stock-up", "StockUp Wholesale", 1800, 4500, "manual"),
    ),
    "shopping": (
        ExpenseTemplate("New shirt", "TrendKart", 799, 2499, "manual"),
        ExpenseTemplate("Jeans", "StyleBay", 1299, 3499, "manual"),
        ExpenseTemplate("T-shirts (pack of 3)", "StyleBay", 699, 1499, "manual"),
        ExpenseTemplate("Formal shoes", "TrendKart", 1499, 3999, "manual"),
        ExpenseTemplate("Backpack", "StyleBay", 999, 2999, "manual"),
        ExpenseTemplate("Earphones", "ShopNest", 799, 2999, "manual"),
        ExpenseTemplate("Phone cover and charger", "ShopNest", 300, 1200, "manual"),
        ExpenseTemplate("Kitchen essentials", "ShopNest", 300, 1500, "manual"),
        ExpenseTemplate("Bedsheet and pillow covers", "ShopNest", 500, 1500, "manual"),
    ),
    "travel": (
        ExpenseTemplate("Metro card top-up", "City Metro", 200, 500, "manual"),
        ExpenseTemplate("Auto to office", None, 60, 180, "manual"),
        ExpenseTemplate("Cab ride", "RideQuick", 180, 550, "manual"),
        ExpenseTemplate("Bike taxi to office", "RideQuick", 40, 150, "manual"),
        ExpenseTemplate("Airport cab", "RideQuick", 700, 1200, "manual"),
        ExpenseTemplate("Petrol", "Sri Ganesh Fuels", 300, 800, "manual"),
        ExpenseTemplate("Monthly bus pass", "City Bus", 1050, 1200, "recurring"),
        ExpenseTemplate("Weekend bus to hometown", "RoadLink Travels", 600, 1400, "manual"),
        ExpenseTemplate("Two-wheeler service", "Sri Ganesh Motors", 800, 1800, "manual"),
    ),
    "bills": (
        ExpenseTemplate("Electricity bill - {month}", "Electricity board", 400, 1400, "recurring"),
        ExpenseTemplate("Broadband - {month}", "FiberLink Broadband", 599, 999, "recurring"),
        ExpenseTemplate("Mobile recharge", "Vaani Mobile", 299, 699, "recurring"),
        ExpenseTemplate("StreamBox subscription", "StreamBox", 149, 499, "subscription"),
        ExpenseTemplate("Music streaming", "TuneVault", 59, 119, "subscription"),
        ExpenseTemplate("Cloud storage plan", "SkyLocker", 59, 130, "subscription"),
        ExpenseTemplate("Drinking water cans", "Neeru Water Supply", 150, 300, "recurring"),
        ExpenseTemplate("Cooking gas refill", "Jyothi Gas Agency", 900, 1000, "manual"),
        ExpenseTemplate(
            "Maintenance charges - {month}", "Apartment association", 1000, 2500, "recurring"
        ),
    ),
    "misc": (
        ExpenseTemplate("Haircut", "Trimline Salon", 150, 350, "manual"),
        ExpenseTemplate("Gym membership - {month}", "IronPulse Fitness", 1200, 2500, "recurring"),
        ExpenseTemplate("Movie tickets", "ScreenSeat", 250, 700, "manual"),
        ExpenseTemplate("Pharmacy", "Sri Raghavendra Medicals", 80, 600, "manual"),
        ExpenseTemplate("Doctor consultation", "Sanjeevini Clinic", 300, 800, "manual"),
        ExpenseTemplate("Birthday gift for a friend", "ShopNest", 500, 1500, "manual"),
        ExpenseTemplate("Laundry and ironing", "Pressright Laundry", 150, 500, "manual"),
        ExpenseTemplate("Dry cleaning", "Pressright Laundry", 200, 600, "manual"),
        ExpenseTemplate("Cricket turf booking", "Kickoff Turf", 150, 400, "manual"),
        ExpenseTemplate("Weekend trip share", None, 1000, 3000, "manual"),
    ),
}
