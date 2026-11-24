"""Standalone tests for the wind rose pipeline.

Run with:  .venv/bin/python tests/test_rose.py
No browser and no network access are required.
"""

import json
import math
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import module.rose as rose  # noqa: E402


def fake_wind_data(days=3):
    """Three days of synthetic wind covering all classes and calm."""
    count = days * 24
    base = datetime(2024, 1, 1)
    times = [
        (base + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M")
        for index in range(count)
    ]
    speeds = np.tile(np.array([0.2, 1.0, 3.0, 5.0, 9.0, 12.0]), count // 6)
    directions = np.tile(
        np.array([0.0, 90.0, 180.0, 270.0, 350.0, 10.0]), count // 6
    )
    return rose.WindData(
        times=times,
        speeds=speeds,
        directions=directions,
        grid_lat=35.6766,
        grid_lon=51.4286,
        elevation=1173.0,
        timezone="Asia/Tehran",
        model="era5",
    )


def stats_dict(place_en="Testville", **overrides):
    """A complete stats dict for rendering tests."""
    stats = {
        "place_fa": "آزمون",
        "place_en": place_en,
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "valid_hours": 72,
        "expected_hours": 72,
        "coverage_pct": 100.0,
        "mean_speed_ms": 5.0,
        "max_speed_ms": 12.0,
        "max_speed_time": "2024-01-02 03:00",
        "calm_pct": 0.0,
        "prevailing_index": 12,
        "prevailing_sector": "W",
        "prevailing_pct": 100.0,
        "grid_lat": 35.6766,
        "grid_lon": 51.4286,
        "elevation_m": 1173,
        "timezone": "Asia/Tehran",
        "model": "era5",
        "warnings": [],
    }
    stats.update(overrides)
    return stats


class TestSectorBinning(unittest.TestCase):
    def test_north_wraps(self):
        """Directions around north must all land in sector N."""
        counts, calm = rose._count_table([0, 360, 350, 10, 359, 1], [5] * 6)
        self.assertEqual(int(counts.sum()), 6)
        self.assertEqual(int(counts[0].sum()), 6)
        self.assertEqual(calm, 0)

    def test_cardinal_directions(self):
        """East, south and west map to sectors 4, 8 and 12."""
        counts, _ = rose._count_table([90, 180, 270], [5, 5, 5])
        self.assertEqual(int(counts[4].sum()), 1)   # E
        self.assertEqual(int(counts[8].sum()), 1)   # S
        self.assertEqual(int(counts[12].sum()), 1)  # W

    def test_sector_boundaries(self):
        """Lower sector edges are inclusive and upper edges exclusive."""
        counts, _ = rose._count_table([348.75, 11.25, 33.75], [5, 5, 5])
        self.assertEqual(int(counts[0].sum()), 1)   # 348.75 is still N
        self.assertEqual(int(counts[1].sum()), 1)   # 11.25 starts NNE
        self.assertEqual(int(counts[2].sum()), 1)   # 33.75 starts NE


class TestSpeedClasses(unittest.TestCase):
    def test_edges_are_lower_inclusive(self):
        """Class edges 0.5 and 2.0 start the next class."""
        speeds = [0.49, 0.5, 2.0, 4.0, 6.0, 8.0, 10.0, 30.0]
        counts, calm = rose._count_table([0] * len(speeds), speeds)
        self.assertEqual(calm, 1)  # 0.49 m/s
        np.testing.assert_array_equal(counts[0], [1, 1, 1, 1, 1, 2])

    def test_open_ended_last_class(self):
        """Speeds above 10 m/s go to the open-ended class."""
        counts, calm = rose._count_table([270], [30.0])
        self.assertEqual(calm, 0)
        self.assertEqual(int(counts[12, 5]), 1)
        self.assertEqual(int(counts.sum()), 1)

    def test_calm_excluded_and_normalized(self):
        """Calm hours stay out of sectors but count in percentages."""
        counts, calm = rose._count_table([0, 0], [0.1, 5.0])
        pct, calm_pct = rose._percent_table(counts, calm)
        self.assertEqual(calm, 1)
        self.assertEqual(int(counts.sum()), 1)
        self.assertAlmostEqual(calm_pct, 50.0)
        self.assertAlmostEqual(float(pct.sum()) + calm_pct, 100.0)


class TestCleaning(unittest.TestCase):
    def test_invalid_rows_are_dropped(self):
        """None, NaN, negative speed and bad direction are dropped."""
        times = [f"t{index}" for index in range(6)]
        speeds = [1.0, None, float("nan"), -1.0, 5.0, 2.0]
        directions = [0.0, 10.0, 20.0, 30.0, 40.0, 361.0]
        valid_times, _, _, count, expected, coverage = rose._clean_wind(
            times, speeds, directions, 6
        )
        self.assertEqual(count, 2)
        self.assertEqual(valid_times, ["t0", "t4"])
        self.assertEqual(expected, 6)
        self.assertAlmostEqual(coverage, 100.0 * 2 / 6)

    def test_direction_360_is_valid(self):
        """360 degrees is valid and normalizes to north."""
        _, _, _, count, _, coverage = rose._clean_wind(
            ["t"], [5.0], [360.0], 1
        )
        self.assertEqual(count, 1)
        self.assertAlmostEqual(coverage, 100.0)

    def test_missing_hours_lower_coverage(self):
        """Missing hours reduce coverage below 100 percent."""
        _, _, _, count, expected, coverage = rose._clean_wind(
            ["a", "b"], [1.0, 2.0], [0.0, 90.0], 12
        )
        self.assertEqual(count, 2)
        self.assertEqual(expected, 12)
        self.assertAlmostEqual(coverage, 100.0 * 2 / 12)

    def test_mismatched_lengths_raise(self):
        """Mismatched series lengths raise a user-facing error."""
        with self.assertRaises(rose.RoseError):
            rose._clean_wind(["a", "b"], [1.0], [0.0, 1.0], 2)


class TestValidation(unittest.TestCase):
    TODAY = date(2026, 11, 22)

    def test_persian_and_arabic_digits(self):
        """Localized digits and the Arabic decimal separator parse."""
        self.assertAlmostEqual(rose._parse_number("۳۵٫۶۸۹۲", "عرض"), 35.6892)
        self.assertAlmostEqual(rose._parse_number("٣٥.٦٨٩٢", "عرض"), 35.6892)
        self.assertEqual(rose._parse_date("۲۰۲۴-۰۱-۰۱", "تاریخ"), date(2024, 1, 1))

    def test_normal_request(self):
        """A valid localized request returns normalized values."""
        lat, lon, start, end = rose._validate_request(
            "۳۵٫۶۸۹۲", "۵۱٫۳۸۹۰", "۲۰۲۴-۰۱-۰۱", "۲۰۲۴-۱۲-۳۱", today=self.TODAY
        )
        self.assertAlmostEqual(lat, 35.6892)
        self.assertAlmostEqual(lon, 51.3890)
        self.assertEqual(start, date(2024, 1, 1))
        self.assertEqual(end, date(2024, 12, 31))

    def test_bad_coordinates(self):
        """Latitude and longitude limits are enforced."""
        for lat, lon in ((91, 51), (-91, 51), (35, 181), (35, -181)):
            with self.assertRaises(rose.RoseError):
                rose._validate_request(lat, lon, "2024-01-01", "2024-12-31", today=self.TODAY)

    def test_bad_numbers(self):
        """Non-numeric coordinate text raises a Persian error."""
        with self.assertRaises(rose.RoseError):
            rose._parse_number("abc", "عرض جغرافیایی")

    def test_reversed_dates(self):
        """Start after end is rejected."""
        with self.assertRaises(rose.RoseError):
            rose._validate_request(35, 51, "2024-12-31", "2024-01-01", today=self.TODAY)

    def test_before_1940(self):
        """Dates before the archive start are rejected."""
        with self.assertRaises(rose.RoseError):
            rose._validate_request(35, 51, "1939-12-31", "1940-12-31", today=self.TODAY)

    def test_future_end(self):
        """End dates beyond the archive lag are rejected."""
        latest = rose.latest_available(self.TODAY)
        with self.assertRaises(rose.RoseError):
            rose._validate_request(
                35, 51, "2024-01-01", (latest + timedelta(days=1)).isoformat(),
                today=self.TODAY,
            )

    def test_range_limit(self):
        """Ranges longer than ten years are rejected."""
        with self.assertRaises(rose.RoseError):
            rose._validate_request(35, 51, "2000-01-01", "2011-01-01", today=self.TODAY)
        rose._validate_request(35, 51, "2010-01-01", "2019-12-31", today=self.TODAY)


class TestStats(unittest.TestCase):
    def build(self, coverage=None):
        data = fake_wind_data()
        valid_times, speeds, directions, count, expected, actual_coverage = rose._clean_wind(
            data.times, data.speeds, data.directions, 72
        )
        counts, calm = rose._count_table(directions, speeds)
        table_pct, calm_pct = rose._percent_table(counts, calm)
        stats = rose._build_stats(
            data, valid_times, speeds, table_pct, calm_pct,
            actual_coverage if coverage is None else coverage,
            expected, date(2024, 1, 1), date(2024, 1, 3), "تهران",
        )
        stats["place_en"] = "Tehran"
        return stats, table_pct, calm_pct

    def test_values_and_json_safety(self):
        """Stats are finite, correct and JSON-serializable."""
        stats, _, _ = self.build()
        json.dumps(stats, allow_nan=False)
        rows = rose._stats_rows(stats)
        json.dumps(rows, allow_nan=False)

        self.assertEqual(stats["valid_hours"], 72)
        self.assertAlmostEqual(stats["coverage_pct"], 100.0)
        self.assertAlmostEqual(stats["calm_pct"], 100.0 / 6, places=1)
        self.assertEqual(stats["prevailing_sector"], "N")
        self.assertAlmostEqual(stats["prevailing_pct"], 33.3)
        self.assertAlmostEqual(stats["max_speed_ms"], 12.0)
        self.assertEqual(stats["max_speed_time"], "2024-01-01 05:00")
        self.assertEqual(stats["warnings"], [])

    def test_low_coverage_warning(self):
        """Low coverage adds a Persian warning."""
        stats, _, _ = self.build(coverage=50.0)
        self.assertTrue(stats["warnings"])
        self.assertIn("پوشش داده", stats["warnings"][0])


class TestRendering(unittest.TestCase):
    def test_west_only_geometry_and_png(self):
        """West-only winds produce one stack and a valid PNG."""
        speeds = np.array([1.0, 5.0, 11.0] * 4)
        directions = np.array([270.0] * 12)
        counts, calm = rose._count_table(directions, speeds)
        table_pct, calm_pct = rose._percent_table(counts, calm)
        stats = stats_dict(calm_pct=calm_pct)

        fig = rose._build_figure(table_pct, calm_pct, stats)
        try:
            ax = fig.axes[0]
            bars = [
                patch for patch in ax.patches
                if hasattr(patch, "get_x") and patch.get_height() > 0
            ]
            west = [
                patch for patch in bars
                if math.isclose(
                    patch.get_x() + patch.get_width() / 2,
                    3 * math.pi / 2,
                    abs_tol=1e-6,
                )
            ]
            self.assertEqual(len(west), 3)
            self.assertEqual(len(bars), 3)  # exactly one sector has bars

            west.sort(key=lambda patch: patch.get_y())
            cumulative = 0.0
            for patch, class_index in zip(west, (0, 2, 5)):
                self.assertAlmostEqual(patch.get_y(), cumulative, places=6)
                self.assertAlmostEqual(
                    patch.get_height(), table_pct[12, class_index], places=6
                )
                cumulative += table_pct[12, class_index]

            self.assertTrue(any(text.get_text().startswith("Calm") for text in ax.texts))
            self.assertTrue(any("Wind Rose — Testville" in text.get_text() for text in fig.texts))
            legend_labels = [text.get_text() for text in fig.legends[0].get_texts()]
            self.assertEqual(legend_labels[-1], ">=10 m/s")
        finally:
            fig.clear()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rose.png"
            rose._render_png(table_pct, calm_pct, stats, path)
            self.assertGreater(path.stat().st_size, 1000)


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.calls = []
        self.old_fetch = rose._fetch_wind
        self.old_dir = rose.WINDROSE_DIR
        self.old_show = rose.show
        rose._fetch_wind = lambda *args, **kwargs: fake_wind_data()
        rose.WINDROSE_DIR = Path(self.folder.name)
        rose.show = lambda **values: self.calls.append(values)

    def tearDown(self):
        rose._fetch_wind = self.old_fetch
        rose.WINDROSE_DIR = self.old_dir
        rose.show = self.old_show

    def test_city_result_is_json_safe_and_rendered(self):
        """A city run returns JSON-safe data and writes a PNG."""
        result = rose.windrose_city("tehran", "2024-01-01", "2024-01-03")
        self.assertTrue(result["ok"])
        self.assertEqual(result["valid_hours"], 72)
        self.assertTrue(result["file"].endswith("tehran_2024-01-01_2024-01-03.png"))
        json.dumps(result, allow_nan=False)
        json.dumps(self.calls[-1], allow_nan=False)

        image_path = Path(self.folder.name) / "tehran_2024-01-01_2024-01-03.png"
        self.assertGreater(image_path.stat().st_size, 1000)
        self.assertTrue(self.calls[-1]["windrose_image"].startswith("data:image/png;base64,"))
        self.assertIsInstance(self.calls[-1]["windrose_stats"], list)

    def test_custom_persian_name_and_digits(self):
        """A Persian manual name stays in the HTML stats."""
        result = rose.windrose_custom(
            "تهران", "۳۵٫۶۸۹۲", "۵۱٫۳۸۹۰", "2024-01-01", "2024-01-03"
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["file"].endswith("custom.png"))
        rows = self.calls[-1]["windrose_stats"]
        place = next(row for row in rows if row["label"] == "مکان")
        self.assertEqual(place["value"], "تهران")

    def test_invalid_input_is_reported(self):
        """Invalid manual coordinates produce a Persian error."""
        result = rose.windrose_custom("x", "120", "51", "2024-01-01", "2024-01-03")
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls[-1]["windrose_status_kind"], "error")

    def test_low_coverage_warning_is_shown(self):
        """Low coverage is pushed to the page as a warning."""
        data = fake_wind_data()
        data.speeds[:60] = np.nan
        rose._fetch_wind = lambda *args, **kwargs: data
        result = rose.windrose_city("tehran", "2024-01-01", "2024-01-03")
        self.assertTrue(result["ok"])
        self.assertTrue(result["warnings"])
        self.assertTrue(self.calls[-1]["windrose_warning"])
        self.assertEqual(self.calls[-1]["windrose_status_kind"], "warn")

    def test_no_valid_data_is_reported(self):
        """An empty valid series produces a Persian error."""
        data = fake_wind_data()
        data.speeds[:] = np.nan
        rose._fetch_wind = lambda *args, **kwargs: data
        result = rose.windrose_city("tehran", "2024-01-01", "2024-01-03")
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls[-1]["windrose_status_kind"], "error")

    def test_unknown_city(self):
        """Unknown preset ids produce a Persian error."""
        result = rose.windrose_city("atlantis", "2024-01-01", "2024-01-03")
        self.assertFalse(result["ok"])
        self.assertIn("شهر", result["message"])

    def test_busy_guard(self):
        """A second request is rejected while the lock is held."""
        rose._RUN_LOCK.acquire()
        try:
            result = rose.windrose_city("tehran", "2024-01-01", "2024-01-03")
        finally:
            rose._RUN_LOCK.release()
        self.assertFalse(result["ok"])
        self.assertIn("درخواست", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
