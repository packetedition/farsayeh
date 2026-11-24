"""Wind rose pipeline: fetch, clean, bin, summarise and render.

The bridge only exposes the three public functions at the bottom. Everything
else is internal so the statistics stay unit-testable without a browser.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

# The HTTP server calls exposed functions from worker threads. Pick a
# non-interactive backend before any figure object is created.
matplotlib.use("Agg", force=True)

import numpy as np
import requests
from matplotlib import colormaps
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Patch

from bridge import expose, image, show
from module.cities import CITIES, CITY_BY_ID

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
WINDROSE_DIR = ASSETS_DIR / "windrose"
CACHE_DIR = ROOT / "cache"

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# ERA5 keeps one homogeneous model for the whole 1940-present archive. The
# default "best_match" switches to the 9 km IFS after 2017, which would mix
# resolutions inside a multi-year wind rose.
MODEL = "era5"

# The archive is published with a delay. Seven days keeps the default range
# safely behind the newest complete ERA5 day.
ARCHIVE_LAG_DAYS = 7

# Only cache ranges that are old enough to be final; ERA5T revisions happen
# near the archive edge.
CACHE_MIN_AGE_DAYS = 30

MIN_DATE = date(1940, 1, 1)
MAX_RANGE_DAYS = 3660  # about ten years, leap days included
COVERAGE_WARN_PCT = 90.0

CALM_THRESHOLD = 0.5
# Lower edges of the six speed classes. The last class is open-ended, so
# np.digitize sends everything >= 10 m/s to index 6.
SPEED_EDGES = np.array([CALM_THRESHOLD, 2.0, 4.0, 6.0, 8.0, 10.0])
SPEED_LABELS = ("0.5-2", "2-4", "4-6", "6-8", "8-10", ">=10 m/s")

N_SECTORS = 16
SECTOR_WIDTH_DEG = 360.0 / N_SECTORS
SECTOR_LABELS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)
SECTOR_LABELS_FA = (
    "شمال", "شمال شمال‌شرقی", "شمال‌شرقی", "شرق شمال‌شرقی",
    "شرق", "شرق جنوب‌شرقی", "جنوب‌شرقی", "جنوب جنوب‌شرقی",
    "جنوب", "جنوب جنوب‌غربی", "جنوب‌غربی", "غرب جنوب‌غربی",
    "غرب", "غرب شمال‌غربی", "شمال‌غربی", "شمال شمال‌غربی",
)

PLOT_DPI = 200
REQUEST_TIMEOUT = (10, 60)  # connect, read
RETRY_ATTEMPTS = 4

_RUN_LOCK = threading.Lock()
_RENDER_LOCK = threading.Lock()

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class RoseError(Exception):
    """User-facing error whose message is already Persian."""


@dataclass
class WindData:
    """Hourly wind series plus the grid point reported by Open-Meteo."""

    times: list
    speeds: np.ndarray
    directions: np.ndarray
    grid_lat: float
    grid_lon: float
    elevation: float | None
    timezone: str | None
    model: str | None


# --------------------------------------------------------------- input helpers
def _normalize_number_text(value: object) -> str:
    """Turn Persian/Arabic-Indic digits and the Arabic decimal separator into ASCII."""
    text = str(value).strip().translate(_DIGITS)
    return text.replace("\u066b", ".").replace("\u066c", "").replace(",", "").replace(" ", "")


def _parse_number(value: object, label_fa: str) -> float:
    """Parse a localized number and raise a Persian error when it is invalid."""
    try:
        number = float(_normalize_number_text(value))
    except (TypeError, ValueError):
        raise RoseError(f"{label_fa} باید یک عدد معتبر باشد.") from None
    if not math.isfinite(number):
        raise RoseError(f"{label_fa} باید یک عدد معتبر باشد.")
    return number


def _parse_date(value: object, label_fa: str) -> date:
    """Parse an ISO date, accepting Persian digits in the input."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_normalize_number_text(value))
    except (TypeError, ValueError):
        raise RoseError(f"{label_fa} معتبر نیست. قالب درست: YYYY-MM-DD") from None


def latest_available(today: date | None = None) -> date:
    """Latest archive date considered complete, given the publication lag."""
    return (today or date.today()) - timedelta(days=ARCHIVE_LAG_DAYS)


def default_range(today: date | None = None) -> tuple[date, date]:
    """Default one-year range ending on the latest complete archive date."""
    end = latest_available(today)
    return end - timedelta(days=364), end


def _validate_request(lat, lon, start_date, end_date, today=None):
    """Validate coordinates and dates; return normalized values."""
    lat = _parse_number(lat, "عرض جغرافیایی")
    lon = _parse_number(lon, "طول جغرافیایی")
    if not -90.0 <= lat <= 90.0:
        raise RoseError("عرض جغرافیایی باید بین -90 و 90 باشد.")
    if not -180.0 <= lon <= 180.0:
        raise RoseError("طول جغرافیایی باید بین -180 و 180 باشد.")

    start = _parse_date(start_date, "تاریخ شروع")
    end = _parse_date(end_date, "تاریخ پایان")
    if start > end:
        raise RoseError("تاریخ شروع نباید بعد از تاریخ پایان باشد.")
    if start < MIN_DATE:
        raise RoseError("تاریخ شروع نمی‌تواند پیش از 1940-01-01 باشد.")

    latest = latest_available(today)
    if end > latest:
        raise RoseError(
            f"تاریخ پایان نباید بعد از {latest.isoformat()} باشد؛ "
            "دادهٔ آرشیو با چند روز تأخیر منتشر می‌شود."
        )
    if (end - start).days > MAX_RANGE_DAYS:
        raise RoseError("بازهٔ زمانی حداکثر ۱۰ سال است.")
    return lat, lon, start, end


def _get_city(city_id) -> dict:
    """Look up a preset city by id."""
    city = CITY_BY_ID.get(str(city_id or "").strip().lower())
    if city is None:
        raise RoseError("شهر انتخاب‌شده در فهرست شهرها نیست.")
    return city


def _slug(value: object) -> str:
    """Make a filesystem-safe slug for generated image names."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return slug or "city"


# ------------------------------------------------------------------ data layer
def _request_params(lat, lon, start, end) -> dict:
    """Build the archive request; pin one model when configured."""
    params = {
        "latitude": round(float(lat), 4),
        "longitude": round(float(lon), 4),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "auto",
    }
    if MODEL:
        params["models"] = MODEL
    return params


def _cache_path(params: dict) -> Path:
    """Stable cache filename derived from the request parameters."""
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return CACHE_DIR / f"windrose_{digest}.json"


def _cache_allowed(end: date) -> bool:
    """Cache only ranges old enough to be final."""
    return end <= date.today() - timedelta(days=CACHE_MIN_AGE_DAYS)


def _cache_read(path: Path) -> dict | None:
    """Read a cached API payload; ignore missing or corrupt files."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def _cache_write(path: Path, payload: dict) -> None:
    """Write a payload atomically so a crash cannot leave half a JSON file."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        traceback.print_exc()


def _reason_from_response(response) -> str:
    """Extract the API's 'reason' for terminal diagnostics only."""
    try:
        return str(response.json().get("reason") or "")[:300]
    except ValueError:
        return response.text[:300]


def _retry_after(response) -> float:
    """Honour a short Retry-After header, capped so the UI stays responsive."""
    try:
        return min(float(response.headers.get("Retry-After", 0)), 10.0)
    except (TypeError, ValueError):
        return 0.0


def _request_json(params: dict) -> dict:
    """GET the archive endpoint with retries and Persian error messages."""
    last_message = "دریافت داده از Open-Meteo ناموفق بود."
    with requests.Session() as session:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            response = None
            try:
                response = session.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            except requests.Timeout:
                last_message = "زمان اتصال به Open-Meteo تمام شد. دوباره تلاش کنید."
            except requests.ConnectionError:
                last_message = "اتصال به Open-Meteo برقرار نشد. اتصال اینترنت را بررسی کنید."
            except requests.RequestException:
                last_message = "خطای شبکه در دریافت داده رخ داد. دوباره تلاش کنید."
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        raise RoseError("پاسخ Open-Meteo خوانا نبود. دوباره تلاش کنید.") from None
                    if not isinstance(payload, dict):
                        raise RoseError("پاسخ Open-Meteo ساختار مورد انتظار را نداشت.")
                    if payload.get("error"):
                        print(f"[windrose] API error: {payload.get('reason')}")
                        raise RoseError("Open-Meteo درخواست را نپذیرفت. بازه یا مختصات را بررسی کنید.")
                    return payload

                if response.status_code == 400:
                    print(f"[windrose] HTTP 400: {_reason_from_response(response)}")
                    raise RoseError("Open-Meteo درخواست را نپذیرفت. بازه یا مختصات را بررسی کنید.")
                if response.status_code == 429:
                    last_message = (
                        "Open-Meteo موقتاً درخواست‌ها را محدود کرده است. "
                        "کمی بعد دوباره تلاش کنید."
                    )
                elif 500 <= response.status_code < 600:
                    last_message = (
                        f"سرویس Open-Meteo موقتاً در دسترس نیست (کد {response.status_code})."
                    )
                else:
                    last_message = f"Open-Meteo پاسخ نامنتظره داد (کد {response.status_code})."

            if attempt < RETRY_ATTEMPTS:
                delay = min(2 ** (attempt - 1), 8)
                if response is not None and response.status_code == 429:
                    delay = max(delay, _retry_after(response))
                time.sleep(delay)

    raise RoseError(last_message)


def _to_float_array(values) -> np.ndarray:
    """Convert JSON numbers to float, mapping None and bad values to NaN."""
    out = np.empty(len(values), dtype=float)
    for index, value in enumerate(values):
        try:
            out[index] = np.nan if value is None else float(value)
        except (TypeError, ValueError):
            out[index] = np.nan
    return out


def _payload_to_wind_data(payload: dict) -> WindData:
    """Extract the two hourly series and grid metadata from a payload."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    speeds = hourly.get("wind_speed_10m") or []
    directions = hourly.get("wind_direction_10m") or []
    if not times or not speeds or not directions:
        raise RoseError("سرویس برای این بازه داده‌ای برنگرداند.")

    elevation = payload.get("elevation")
    try:
        elevation_value = float(elevation) if elevation is not None else None
    except (TypeError, ValueError):
        elevation_value = None
    if elevation_value is not None and not math.isfinite(elevation_value):
        elevation_value = None

    return WindData(
        times=[str(item) for item in times],
        speeds=_to_float_array(speeds),
        directions=_to_float_array(directions),
        grid_lat=float(payload.get("latitude", 0.0)),
        grid_lon=float(payload.get("longitude", 0.0)),
        elevation=elevation_value,
        timezone=payload.get("timezone"),
        model=MODEL or "best_match",
    )


def _fetch_wind(lat, lon, start: date, end: date) -> WindData:
    """Fetch hourly wind data, using the disk cache for final ranges."""
    params = _request_params(lat, lon, start, end)
    path = _cache_path(params)
    payload = _cache_read(path) if _cache_allowed(end) else None
    if payload is None:
        payload = _request_json(params)
        if _cache_allowed(end):
            _cache_write(path, payload)
    else:
        print(f"[windrose] cache hit: {path.name}")
    return _payload_to_wind_data(payload)


# ------------------------------------------------------------------- algorithm
def _clean_wind(times, speeds, directions, expected_hours: int):
    """Drop invalid hours and report coverage against the expected hour count."""
    speeds = np.asarray(speeds, dtype=float)
    directions = np.asarray(directions, dtype=float)
    if speeds.shape != directions.shape or speeds.size != len(times):
        raise RoseError("داده‌های دریافتی ناسازگار بودند.")

    valid = (
        np.isfinite(speeds)
        & np.isfinite(directions)
        & (speeds >= 0.0)
        & (directions >= 0.0)
        & (directions <= 360.0)
    )
    valid_times = [stamp for stamp, ok in zip(times, valid.tolist()) if ok]
    expected = max(int(expected_hours), len(times))
    coverage = 100.0 * int(valid.sum()) / expected if expected else 0.0
    return valid_times, speeds[valid], directions[valid], int(valid.sum()), expected, coverage


def _count_table(directions, speeds):
    """Bin directions into 16 sectors and speeds into 6 classes; calm separate."""
    directions = np.mod(np.asarray(directions, dtype=float), 360.0)
    speeds = np.asarray(speeds, dtype=float)

    # Sector N is centred on 0 and spans [348.75, 11.25). Adding half a sector
    # before the floor makes that wrap-around explicit.
    sector = np.floor(
        ((directions + SECTOR_WIDTH_DEG / 2.0) % 360.0) / SECTOR_WIDTH_DEG
    ).astype(int)
    sector %= N_SECTORS

    # digitize returns 0 below 0.5 m/s (calm) and 1..6 for the six classes.
    class_index = np.digitize(speeds, SPEED_EDGES, right=False)
    counts = np.zeros((N_SECTORS, len(SPEED_EDGES)), dtype=np.int64)
    active = class_index > 0
    np.add.at(counts, (sector[active], class_index[active] - 1), 1)
    calm = int(np.count_nonzero(~active))
    return counts, calm


def _percent_table(counts, calm_count: int):
    """Normalize every cell by all valid hours, calm hours included."""
    total = int(counts.sum()) + int(calm_count)
    if total == 0:
        return np.zeros_like(counts, dtype=float), 0.0
    return counts.astype(float) * 100.0 / total, 100.0 * int(calm_count) / total


def _round(value, digits: int = 2):
    """Round a float for JSON, mapping non-finite values to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def _build_stats(data: WindData, valid_times, speeds, table_pct, calm_pct,
                 coverage, expected_hours, start: date, end: date, place_fa: str) -> dict:
    """Build the JSON-safe statistics block shown next to the image."""
    totals = table_pct.sum(axis=1)
    if float(totals.max()) > 0.0:
        prevailing_index = int(totals.argmax())
        prevailing_sector = SECTOR_LABELS[prevailing_index]
        prevailing_pct = _round(totals[prevailing_index], 1)
    else:
        prevailing_index = None
        prevailing_sector = None
        prevailing_pct = 0.0

    max_index = int(np.argmax(speeds))
    warnings = []
    if coverage < COVERAGE_WARN_PCT:
        warnings.append(
            f"پوشش داده {coverage:.1f}٪ است؛ کمتر از {COVERAGE_WARN_PCT:.0f}٪ "
            "ساعت‌های این بازه دادهٔ معتبر دارند."
        )

    return {
        "place_fa": place_fa,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "valid_hours": int(len(valid_times)),
        "expected_hours": int(expected_hours),
        "coverage_pct": _round(coverage, 1),
        "mean_speed_ms": _round(float(np.mean(speeds)), 2),
        "max_speed_ms": _round(float(speeds[max_index]), 2),
        "max_speed_time": str(valid_times[max_index]).replace("T", " "),
        "calm_pct": _round(calm_pct, 1),
        "prevailing_index": prevailing_index,
        "prevailing_sector": prevailing_sector,
        "prevailing_pct": prevailing_pct,
        "grid_lat": _round(data.grid_lat, 4),
        "grid_lon": _round(data.grid_lon, 4),
        "elevation_m": int(round(data.elevation)) if data.elevation is not None else None,
        "timezone": data.timezone,
        "model": data.model,
        "warnings": warnings,
    }


def _stats_rows(stats: dict) -> list[dict]:
    """Translate the stats block into Persian label/value rows for the page."""
    grid = f'{stats["grid_lat"]:.4f}, {stats["grid_lon"]:.4f}'
    if stats["elevation_m"] is not None:
        grid += f' · {stats["elevation_m"]:,} m'

    if stats["prevailing_index"] is None:
        prevailing = "—"
    else:
        index = stats["prevailing_index"]
        prevailing = (
            f'{SECTOR_LABELS_FA[index]} ({SECTOR_LABELS[index]}) — '
            f'{stats["prevailing_pct"]:.1f}%'
        )

    return [
        {"label": "مکان", "value": stats["place_fa"]},
        {"label": "دوره", "value": f'{stats["period_start"]} تا {stats["period_end"]}'},
        {
            "label": "ساعت‌های معتبر",
            "value": (
                f'{stats["valid_hours"]:,} از {stats["expected_hours"]:,} '
                f'({stats["coverage_pct"]:.1f}%)'
            ),
        },
        {"label": "میانگین سرعت", "value": f'{stats["mean_speed_ms"]:.2f} m/s'},
        {
            "label": "بیشترین سرعت",
            "value": f'{stats["max_speed_ms"]:.2f} m/s — {stats["max_speed_time"]}',
        },
        {"label": "سهم آرام", "value": f'{stats["calm_pct"]:.1f}%'},
        {"label": "جهت غالب", "value": prevailing},
        {"label": "نقطهٔ شبکه", "value": grid},
        {"label": "مدل داده", "value": stats["model"] or "best_match"},
    ]


# -------------------------------------------------------------------- plotting
def _nice_radial_ticks(max_value: float):
    """Choose round percentage ticks and a matching radial limit."""
    if not math.isfinite(max_value) or max_value <= 0.0:
        return [1.0, 2.0, 3.0, 4.0, 5.0], 5.0

    raw_step = max_value / 5.0
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    step = next(
        (candidate * magnitude for candidate in (1.0, 2.0, 2.5, 5.0, 10.0)
         if max_value / (candidate * magnitude) <= 6.0),
        10.0 * magnitude,
    )
    top = math.ceil(max_value / step - 1e-9) * step
    ticks = [round(step * index, 10) for index in range(1, int(round(top / step)) + 1)]
    return ticks, top


def _build_figure(table_pct, calm_pct: float, stats: dict) -> Figure:
    """Draw the polar wind rose and return the figure (no pyplot state)."""
    fig = Figure(figsize=(8.8, 8.2), dpi=PLOT_DPI, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.04, 0.04, 0.68, 0.78], projection="polar")

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # clockwise, like a compass

    theta = np.deg2rad(np.arange(N_SECTORS) * SECTOR_WIDTH_DEG)
    bar_width = np.deg2rad(SECTOR_WIDTH_DEG) * 0.9
    cmap = colormaps["Blues"]
    colors = [cmap(value) for value in np.linspace(0.30, 0.92, len(SPEED_LABELS))]

    bottom = np.zeros(N_SECTORS, dtype=float)
    handles = []
    for class_index, label in enumerate(SPEED_LABELS):
        heights = np.asarray(table_pct[:, class_index], dtype=float)
        ax.bar(
            theta, heights, width=bar_width, bottom=bottom,
            color=colors[class_index], edgecolor="white", linewidth=0.5,
            align="center", zorder=3,
        )
        handles.append(Patch(facecolor=colors[class_index], edgecolor="white", label=label))
        bottom += heights

    ticks, top = _nice_radial_ticks(float(bottom.max()))
    ax.set_ylim(0.0, top)
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{tick:g}%" for tick in ticks], fontsize=8, color="#607d8b")

    # Put the radial labels on the quietest boundary between two sectors.
    totals = np.asarray(table_pct, dtype=float).sum(axis=1)
    quiet = int(np.argmin(totals + np.roll(totals, -1)))
    ax.set_rlabel_position((quiet + 0.5) * SECTOR_WIDTH_DEG)
    for label in ax.get_yticklabels():
        label.set_bbox({"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 1.0})

    ax.set_thetagrids(np.arange(0.0, 360.0, SECTOR_WIDTH_DEG), SECTOR_LABELS)
    ax.tick_params(axis="x", labelsize=9, pad=7, colors="#37474f")
    ax.grid(True, color="#cfd8dc", linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    ax.spines["polar"].set_color("#b0bec5")
    ax.spines["polar"].set_linewidth(0.8)

    # Calm has no direction, so it is shown as a neutral central hole instead
    # of a bar in any sector.
    hole = Circle(
        (0.5, 0.5), 0.075, transform=ax.transAxes,
        facecolor="white", edgecolor="#cfd8dc", linewidth=0.8, zorder=10,
    )
    ax.add_patch(hole)
    ax.text(
        0.5, 0.5, f"Calm\n{calm_pct:.1f}%", transform=ax.transAxes,
        ha="center", va="center", fontsize=8.5, color="#37474f",
        linespacing=1.1, zorder=11,
    )

    # Escape "$" so a manual place name cannot switch matplotlib into mathtext.
    place_en = str(stats["place_en"]).replace("$", r"\$")
    if len(place_en) > 60:
        place_en = place_en[:57].rstrip() + "..."
    period = f'{stats["period_start"]} to {stats["period_end"]}'
    elevation = f'{stats["elevation_m"]:,} m' if stats["elevation_m"] is not None else "n/a"
    subtitle = (
        f'Grid {stats["grid_lat"]:.4f}, {stats["grid_lon"]:.4f} · {elevation} · '
        f'{stats["valid_hours"]:,} valid hours ({stats["coverage_pct"]:.1f}%)'
    )

    fig.text(
        0.38, 0.965, f"Wind Rose — {place_en}", ha="center", va="top",
        fontsize=15, fontweight="bold", color="#1f2d33",
    )
    fig.text(0.38, 0.928, period, ha="center", va="top", fontsize=10.5, color="#37474f")
    fig.text(0.38, 0.902, subtitle, ha="center", va="top", fontsize=8.5, color="#607d8b")
    fig.text(
        0.38, 0.015, "Data: Open-Meteo Archive API · 10 m wind",
        ha="center", va="bottom", fontsize=7.5, color="#90a4ae",
    )

    fig.legend(
        handles=handles, loc="center left", bbox_to_anchor=(0.755, 0.42),
        frameon=False, title="Wind speed (m/s)", fontsize=9, title_fontsize=9.5,
    )
    return fig


def _render_png(table_pct, calm_pct: float, stats: dict, path: Path) -> None:
    """Render one PNG under a lock and always release the figure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RENDER_LOCK:
        fig = _build_figure(table_pct, calm_pct, stats)
        try:
            fig.savefig(path, dpi=PLOT_DPI, facecolor=fig.get_facecolor())
        finally:
            fig.clear()
    if not path.exists() or path.stat().st_size == 0:
        raise RoseError("رسم تصویر گلباد ناموفق بود.")


# ---------------------------------------------------------------- orchestration
def _guarded(work):
    """Run one request at a time and convert every failure to a Persian status."""
    if not _RUN_LOCK.acquire(blocking=False):
        message = "یک درخواست دیگر در حال اجراست. کمی صبر کنید."
        show(windrose_status=message, windrose_status_kind="warn", windrose_warning="")
        return {"ok": False, "message": message}
    try:
        return work()
    except RoseError as exc:
        print(f"[windrose] user error: {exc}")
        show(windrose_status=str(exc), windrose_status_kind="error", windrose_warning="")
        return {"ok": False, "message": str(exc)}
    except Exception:
        traceback.print_exc()
        message = "خطای غیرمنتظره در ساخت گلباد رخ داد. جزئیات در ترمینال چاپ شد."
        show(windrose_status=message, windrose_status_kind="error", windrose_warning="")
        return {"ok": False, "message": message}
    finally:
        _RUN_LOCK.release()


def _generate(place_fa, place_en, lat, lon, start, end, filename: str) -> dict:
    """Run the full pipeline for validated input and push the result to the page."""
    show(
        windrose_status="در حال دریافت داده‌های باد…",
        windrose_status_kind="info",
        windrose_warning="",
    )
    data = _fetch_wind(lat, lon, start, end)

    expected = ((end - start).days + 1) * 24
    show(windrose_status="در حال پردازش داده‌ها…")
    valid_times, speeds, directions, valid_hours, expected, coverage = _clean_wind(
        data.times, data.speeds, data.directions, expected
    )
    if valid_hours == 0:
        raise RoseError("برای این بازه هیچ ساعت معتبری با دادهٔ باد پیدا نشد.")

    counts, calm_count = _count_table(directions, speeds)
    table_pct, calm_pct = _percent_table(counts, calm_count)
    stats = _build_stats(
        data, valid_times, speeds, table_pct, calm_pct,
        coverage, expected, start, end, place_fa,
    )
    stats["place_en"] = place_en

    show(windrose_status="در حال رسم نمودار…")
    path = WINDROSE_DIR / filename
    _render_png(table_pct, calm_pct, stats, path)

    warning = stats["warnings"][0] if stats["warnings"] else ""
    status = "گلباد رسم شد." if not warning else "گلباد رسم شد؛ به هشدار پوشش داده توجه کنید."
    show(
        windrose_image=image(str(path)),
        windrose_stats=_stats_rows(stats),
        windrose_status=status,
        windrose_status_kind="warn" if warning else "ok",
        windrose_warning=warning,
    )
    try:
        file_label = str(path.relative_to(ROOT))
    except ValueError:
        file_label = str(path)
    return {
        "ok": True,
        "file": file_label,
        "valid_hours": stats["valid_hours"],
        "coverage_pct": stats["coverage_pct"],
        "warnings": stats["warnings"],
    }


# ------------------------------------------------------------- exposed functions
@expose
def get_cities():
    """Return preset cities, default dates and validation limits for the UI."""
    start, end = default_range()
    return {
        "cities": [dict(city) for city in CITIES],
        "defaults": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "limits": {
            "min_date": MIN_DATE.isoformat(),
            "max_date": latest_available().isoformat(),
            "max_range_days": MAX_RANGE_DAYS,
        },
    }


@expose
def windrose_city(city_id, start_date, end_date):
    """Draw the wind rose for a preset city and return a small status dict."""
    def work():
        city = _get_city(city_id)
        lat, lon, start, end = _validate_request(
            city["lat"], city["lon"], start_date, end_date
        )
        filename = f'{_slug(city["id"])}_{start.isoformat()}_{end.isoformat()}.png'
        return _generate(
            city["name_fa"], city["name_en"], lat, lon, start, end, filename
        )

    return _guarded(work)


@expose
def windrose_custom(name, lat, lon, start_date, end_date):
    """Draw a wind rose for manual coordinates and return a small status dict."""
    def work():
        lat_value, lon_value, start, end = _validate_request(
            lat, lon, start_date, end_date
        )
        label = str(name or "").strip()
        place_fa = label or "نقطه دستی"
        # matplotlib cannot shape Persian; keep the image Latin-only.
        place_en = label if label and label.isascii() else "Custom location"
        return _generate(
            place_fa, place_en, lat_value, lon_value, start, end, "custom.png"
        )

    return _guarded(work)
