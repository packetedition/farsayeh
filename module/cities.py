"""Preset Iranian cities used by the wind rose tab.

Coordinates are city-centre WGS84 values with four decimals. The list is the
single source of truth for both the Python API and the browser dropdown.
"""

CITIES = [
    {"id": "tehran", "name_fa": "تهران", "name_en": "Tehran", "lat": 35.6892, "lon": 51.3890},
    {"id": "mashhad", "name_fa": "مشهد", "name_en": "Mashhad", "lat": 36.2605, "lon": 59.6168},
    {"id": "isfahan", "name_fa": "اصفهان", "name_en": "Isfahan", "lat": 32.6546, "lon": 51.6680},
    {"id": "tabriz", "name_fa": "تبریز", "name_en": "Tabriz", "lat": 38.0800, "lon": 46.2919},
    {"id": "shiraz", "name_fa": "شیراز", "name_en": "Shiraz", "lat": 29.5918, "lon": 52.5837},
    {"id": "ahvaz", "name_fa": "اهواز", "name_en": "Ahvaz", "lat": 31.3183, "lon": 48.6706},
    {"id": "qom", "name_fa": "قم", "name_en": "Qom", "lat": 34.6399, "lon": 50.8759},
    {"id": "kermanshah", "name_fa": "کرمانشاه", "name_en": "Kermanshah", "lat": 34.3277, "lon": 47.0778},
    {"id": "urmia", "name_fa": "ارومیه", "name_en": "Urmia", "lat": 37.5527, "lon": 45.0760},
    {"id": "rasht", "name_fa": "رشت", "name_en": "Rasht", "lat": 37.2808, "lon": 49.5832},
    {"id": "bandar-abbas", "name_fa": "بندرعباس", "name_en": "Bandar Abbas", "lat": 27.1865, "lon": 56.2808},
    {"id": "zahedan", "name_fa": "زاهدان", "name_en": "Zahedan", "lat": 29.4963, "lon": 60.8629},
    {"id": "yazd", "name_fa": "یزد", "name_en": "Yazd", "lat": 31.8974, "lon": 54.3569},
    {"id": "kerman", "name_fa": "کرمان", "name_en": "Kerman", "lat": 30.2839, "lon": 57.0834},
    {"id": "bushehr", "name_fa": "بوشهر", "name_en": "Bushehr", "lat": 28.9234, "lon": 50.8203},
]

CITY_BY_ID = {city["id"]: city for city in CITIES}
