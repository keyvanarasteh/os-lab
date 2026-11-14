"""CLN-32 tests: age and size filters with the filtered-in-flux guard.

The behaviours the task calls out get dedicated tests: duration parsing
(every unit, the multi-token ``2h30m`` / ``1y2mo`` sequences, bare seconds,
whitespace tolerance, and every refused shape — empty, wrong order, repeats,
negatives, unknown units, fractional unit values), filter parsing (numbers
and duration strings, inverted and negative ranges, non-numbers), the age
boundaries (exactly at a bound is included, one second past it is excluded,
a vanished path is ``missing``), the exclusion reasons of ``apply_filters``,
the ``blocked()`` truth table, and an end-to-end pass over plan-item dicts
built from a generated tree — never a real user folder (rule 8).
"""
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from cleanup_lab import filters as filters_module

# A fixed "now". Every helper takes ``now`` as a parameter, so no test
# depends on the clock or on a real user folder.
NOW = 1_700_000_000


def make_filters(**overrides):
    """A filters dict in parse_filters' shape, with nothing active by default."""
    filters = {
        "minAgeSeconds": None,
        "maxAgeSeconds": None,
        "minSizeBytes": None,
        "maxSizeBytes": None,
        "active": False,
    }
    filters.update(overrides)
    return filters


class ParseDurationTests(unittest.TestCase):
    """Durations: every unit, multi-token sequences, and refused shapes."""

    def test_every_unit_stands_alone(self):
        parse = filters_module.parse_duration
        self.assertEqual(parse("90"), 90.0)  # a bare number is seconds
        self.assertEqual(parse("45s"), 45.0)
        self.assertEqual(parse("10m"), 600.0)
        self.assertEqual(parse("2h"), 7200.0)
        self.assertEqual(parse("7d"), 604800.0)
        self.assertEqual(parse("3w"), 1814400.0)
        self.assertEqual(parse("2mo"), 5184000.0)  # a 30-day month
        self.assertEqual(parse("1y"), 31536000.0)  # a 365-day year
        for text in ("90", "45s", "2h", "1y"):
            self.assertIsInstance(parse(text), float)

    def test_multi_token_sequences_add_up(self):
        parse = filters_module.parse_duration
        self.assertEqual(parse("2h30m"), 9000.0)
        self.assertEqual(parse("1y2mo"), 36720000.0)
        self.assertEqual(parse("1d12h"), 129600.0)
        self.assertEqual(parse("1y2mo1w1d1h1m1s"), 37414861.0)

    def test_whitespace_is_allowed_between_tokens(self):
        parse = filters_module.parse_duration
        self.assertEqual(parse("2h 30m"), 9000.0)
        self.assertEqual(parse("1y 2mo"), 36720000.0)
        self.assertEqual(parse("  90  "), 90.0)
        self.assertEqual(parse("\t2h\t30m\t"), 9000.0)

    def test_units_are_case_insensitive(self):
        parse = filters_module.parse_duration
        self.assertEqual(parse("2H30M"), 9000.0)
        self.assertEqual(parse("2MO"), 5184000.0)
        self.assertEqual(parse("7D"), 604800.0)
        self.assertEqual(parse("1Y"), 31536000.0)

    def test_a_bare_number_may_be_fractional(self):
        self.assertEqual(filters_module.parse_duration("1.5"), 1.5)
        self.assertEqual(filters_module.parse_duration("0"), 0.0)

    def test_invalid_durations_are_refused(self):
        parse = filters_module.parse_duration
        for text in (
            "", "   ",    # empty
            "m2h",        # starts with a unit, not a number
            "2m1h",       # wrong order
            "2h2h",       # a unit twice
            "1h2m1h",     # a unit twice, further apart
            "-5d",        # negative
            "5x",         # unknown unit
            "abc",        # not a number at all
            "1.5h",       # a fractional unit value
            "2h30",       # a bare number mixed with units
            "2 h",        # a number separated from its unit
            "+90",        # not a plain number
            "1y1y",
        ):
            with self.assertRaises(ValueError, msg=repr(text)):
                parse(text)

    def test_errors_are_filter_errors_with_precise_messages(self):
        parse = filters_module.parse_duration
        with self.assertRaises(filters_module.FilterError) as caught:
            parse("2h2h")
        self.assertIn("more than once", str(caught.exception))
        with self.assertRaises(filters_module.FilterError) as caught:
            parse("5x")
        self.assertIn("Unknown duration unit", str(caught.exception))
        with self.assertRaises(filters_module.FilterError) as caught:
            parse("2m1h")
        self.assertIn("descending order", str(caught.exception))
        with self.assertRaises(filters_module.FilterError) as caught:
            parse("-5d")
        self.assertIn("negative", str(caught.exception))
        with self.assertRaises(filters_module.FilterError) as caught:
            parse("")
        self.assertIn("required", str(caught.exception))

    def test_an_absurdly_long_number_is_refused(self):
        with self.assertRaises(ValueError):
            filters_module.parse_duration("9" * 400)


class ParseFiltersTests(unittest.TestCase):
    """parse_filters: typed fields, ranges, and honest refusals."""

    def test_numbers_and_duration_strings_parse(self):
        filters = filters_module.parse_filters({
            "minAgeSeconds": 3600,
            "maxAgeSeconds": "2h30m",
            "minSizeBytes": 100,
            "maxSizeBytes": 2048.0,
        })
        self.assertEqual(filters["minAgeSeconds"], 3600.0)
        self.assertEqual(filters["maxAgeSeconds"], 9000.0)
        self.assertEqual(filters["minSizeBytes"], 100)
        self.assertEqual(filters["maxSizeBytes"], 2048)
        self.assertTrue(filters["active"])
        self.assertIsInstance(filters["minAgeSeconds"], float)
        self.assertIsInstance(filters["maxAgeSeconds"], float)
        self.assertIsInstance(filters["minSizeBytes"], int)
        self.assertIsInstance(filters["maxSizeBytes"], int)

    def test_an_empty_request_means_no_active_filters(self):
        for request in ({}, {"minAgeSeconds": None, "maxSizeBytes": None}):
            self.assertEqual(
                filters_module.parse_filters(request),
                {"minAgeSeconds": None, "maxAgeSeconds": None,
                 "minSizeBytes": None, "maxSizeBytes": None, "active": False},
            )
        self.assertFalse(filters_module.parse_filters(None)["active"])

    def test_unknown_keys_are_not_this_function_s_business(self):
        filters = filters_module.parse_filters({
            "entryIds": ["system.caches"],
            "workers": 4,
            "mode": "trash",
            "minAgeSeconds": "1h",
        })
        self.assertEqual(filters["minAgeSeconds"], 3600.0)
        self.assertTrue(filters["active"])

    def test_inverted_ranges_are_refused(self):
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"minAgeSeconds": 7200, "maxAgeSeconds": 3600})
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"minSizeBytes": 2000, "maxSizeBytes": 1000})

    def test_equal_bounds_are_allowed(self):
        filters = filters_module.parse_filters({"minAgeSeconds": 3600, "maxAgeSeconds": 3600})
        self.assertTrue(filters["active"])
        filters = filters_module.parse_filters({"minSizeBytes": 10, "maxSizeBytes": 10})
        self.assertTrue(filters["active"])

    def test_negative_values_are_refused(self):
        for request in (
            {"minAgeSeconds": -5},
            {"maxAgeSeconds": -1},
            {"minAgeSeconds": "-5d"},
            {"minSizeBytes": -1},
            {"maxSizeBytes": -0.5},
        ):
            with self.assertRaises(ValueError, msg=repr(request)):
                filters_module.parse_filters(request)

    def test_unparseable_durations_name_the_field(self):
        for text in ("5x", "abc", "", "1.5h", "2h2h"):
            with self.assertRaises(ValueError) as caught:
                filters_module.parse_filters({"minAgeSeconds": text})
            self.assertIn("minAgeSeconds", str(caught.exception))

    def test_size_fields_take_numbers_only(self):
        for bad in ("1024", True, 10.5, [1024]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                filters_module.parse_filters({"minSizeBytes": bad})
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"maxSizeBytes": "1024"})

    def test_booleans_are_not_numbers(self):
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"minAgeSeconds": True})
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"minAgeSeconds": False})

    def test_non_finite_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"minAgeSeconds": float("inf")})
        with self.assertRaises(ValueError):
            filters_module.parse_filters({"maxSizeBytes": float("nan")})

    def test_a_non_object_request_is_refused(self):
        with self.assertRaises(ValueError):
            filters_module.parse_filters(["minAgeSeconds"])


class AgeBucketTests(unittest.TestCase):
    """age_bucket: exactly at a bound is included, one second past excludes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-filters-age-")
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, name, age_seconds):
        path = os.path.join(self.base, name)
        with open(path, "wb") as handle:
            handle.write(b"x")
        stamp = NOW - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_without_age_filters_everything_is_included_and_unstat_ed(self):
        calls = []

        def lstat(path):
            calls.append(path)
            return os.lstat(path)

        path = self.make_file("keep.bin", 0)
        for filters in (
            make_filters(),
            make_filters(active=True, minSizeBytes=10),  # size-only: not age's business
        ):
            self.assertEqual(
                filters_module.age_bucket(path, filters=filters, now=NOW, lstat=lstat),
                "include",
            )
        self.assertEqual(calls, [])
        self.assertEqual(
            filters_module.age_bucket(
                os.path.join(self.base, "gone.bin"), filters=make_filters(), now=NOW
            ),
            "include",
        )

    def test_exactly_the_minimum_age_is_included(self):
        path = self.make_file("edge.bin", 3600)
        filters = make_filters(minAgeSeconds=3600.0, active=True)
        self.assertEqual(filters_module.age_bucket(path, filters=filters, now=NOW), "include")

    def test_one_second_under_the_minimum_is_excluded(self):
        path = self.make_file("fresh.bin", 3599)
        filters = make_filters(minAgeSeconds=3600.0, active=True)
        self.assertEqual(filters_module.age_bucket(path, filters=filters, now=NOW), "exclude")

    def test_exactly_the_maximum_age_is_included(self):
        path = self.make_file("edge.bin", 86400)
        filters = make_filters(maxAgeSeconds=86400.0, active=True)
        self.assertEqual(filters_module.age_bucket(path, filters=filters, now=NOW), "include")

    def test_one_second_over_the_maximum_is_excluded(self):
        path = self.make_file("older.bin", 86401)
        filters = make_filters(maxAgeSeconds=86400.0, active=True)
        self.assertEqual(filters_module.age_bucket(path, filters=filters, now=NOW), "exclude")

    def test_both_bounds_bracket_the_window(self):
        filters = make_filters(minAgeSeconds=3600.0, maxAgeSeconds=86400.0, active=True)
        expected = (
            ("fresh.bin", 3599, "exclude"),
            ("min-edge.bin", 3600, "include"),
            ("middle.bin", 43200, "include"),
            ("max-edge.bin", 86400, "include"),
            ("older.bin", 86401, "exclude"),
        )
        for name, age, bucket in expected:
            path = self.make_file(name, age)
            self.assertEqual(
                filters_module.age_bucket(path, filters=filters, now=NOW), bucket, name
            )

    def test_a_vanished_path_is_missing(self):
        filters = make_filters(minAgeSeconds=3600.0, active=True)
        self.assertEqual(
            filters_module.age_bucket(
                os.path.join(self.base, "gone.bin"), filters=filters, now=NOW
            ),
            "missing",
        )

    def test_a_failing_lstat_is_missing_and_receives_the_path(self):
        path = self.make_file("there.bin", 40000)
        received = []

        def failing_lstat(p):
            received.append(p)
            raise OSError(2, "no such file or directory")

        filters = make_filters(minAgeSeconds=3600.0, active=True)
        self.assertEqual(
            filters_module.age_bucket(path, filters=filters, now=NOW, lstat=failing_lstat),
            "missing",
        )
        self.assertEqual(received, [path])

    def test_a_future_mtime_is_too_fresh(self):
        path = self.make_file("future.bin", -100)  # the mtime is 100s ahead of now
        filters = make_filters(minAgeSeconds=3600.0, active=True)
        self.assertEqual(filters_module.age_bucket(path, filters=filters, now=NOW), "exclude")


class ApplyFiltersTests(unittest.TestCase):
    """apply_filters: reasons, None sizes, vanished items, and order."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-filters-apply-")
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, name, size_bytes, age_seconds=None):
        path = os.path.join(self.base, name)
        if age_seconds is not None:
            path = self.make_file(name, age_seconds)
        return {"path": path, "sizeBytes": size_bytes}

    def make_file(self, name, age_seconds):
        path = os.path.join(self.base, name)
        with open(path, "wb") as handle:
            handle.write(b"x")
        stamp = NOW - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_inactive_filters_include_everything_without_statting(self):
        def failing_lstat(path):
            raise AssertionError("lstat must not be called without active filters")

        items = [
            {"path": os.path.join(self.base, "a"), "sizeBytes": 1},
            {"path": os.path.join(self.base, "b"), "sizeBytes": None},
        ]
        result = filters_module.apply_filters(
            items, filters=make_filters(), now=NOW, lstat=failing_lstat
        )
        self.assertEqual(result["included"], items)
        self.assertEqual(result["excluded"], [])

    def test_size_only_filters_never_stat_and_trust_size_bytes(self):
        def failing_lstat(path):
            raise AssertionError("size filtering compares sizeBytes, it does not stat")

        items = [
            {"path": os.path.join(self.base, "a"), "sizeBytes": 5},
            {"path": os.path.join(self.base, "vanished"), "sizeBytes": 5000},
            {"path": os.path.join(self.base, "b"), "sizeBytes": None},
        ]
        filters = make_filters(minSizeBytes=100, maxSizeBytes=1000, active=True)
        result = filters_module.apply_filters(items, filters=filters, now=NOW, lstat=failing_lstat)
        self.assertEqual([item["sizeBytes"] for item in result["included"]], [None])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["below the minimum size", "above the maximum size"],
        )

    def test_age_reasons_are_reported(self):
        filters = make_filters(minAgeSeconds=3600.0, maxAgeSeconds=86400.0, active=True)
        young = self.item("young", 100, age_seconds=600)
        middle = self.item("middle", 100, age_seconds=43200)
        old = self.item("old", 100, age_seconds=100000)
        result = filters_module.apply_filters([young, middle, old], filters=filters, now=NOW)
        self.assertEqual(result["included"], [middle])
        self.assertEqual(
            [(entry["item"], entry["reason"]) for entry in result["excluded"]],
            [
                (young, "younger than the minimum age"),
                (old, "older than the maximum age"),
            ],
        )
        self.assertIs(result["excluded"][0]["item"], young)  # the very item dict

    def test_size_reasons_are_reported(self):
        filters = make_filters(minSizeBytes=100, maxSizeBytes=1000, active=True)
        small = {"path": os.path.join(self.base, "small"), "sizeBytes": 50}
        right = {"path": os.path.join(self.base, "right"), "sizeBytes": 500}
        big = {"path": os.path.join(self.base, "big"), "sizeBytes": 5000}
        result = filters_module.apply_filters([small, right, big], filters=filters, now=NOW)
        self.assertEqual(result["included"], [right])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["below the minimum size", "above the maximum size"],
        )

    def test_a_none_size_is_included_never_guessed(self):
        filters = make_filters(minSizeBytes=100, active=True)
        item = {"path": os.path.join(self.base, "unknown"), "sizeBytes": None}
        result = filters_module.apply_filters([item], filters=filters, now=NOW)
        self.assertEqual(result["included"], [item])
        self.assertEqual(result["excluded"], [])

    def test_a_vanished_item_is_excluded_as_gone(self):
        filters = make_filters(minAgeSeconds=3600.0, active=True)
        item = {"path": os.path.join(self.base, "gone"), "sizeBytes": 100}
        result = filters_module.apply_filters([item], filters=filters, now=NOW)
        self.assertEqual(result["included"], [])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["the item no longer exists"],
        )

    def test_age_is_checked_before_size(self):
        filters = make_filters(minAgeSeconds=3600.0, minSizeBytes=100, active=True)
        item = self.item("young-small", 10, age_seconds=60)
        result = filters_module.apply_filters([item], filters=filters, now=NOW)
        self.assertEqual(result["included"], [])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["younger than the minimum age"],
        )

    def test_included_items_keep_their_order(self):
        filters = make_filters(minSizeBytes=10, active=True)
        items = [
            {"path": os.path.join(self.base, "a"), "sizeBytes": 100},
            {"path": os.path.join(self.base, "b"), "sizeBytes": 1},   # excluded
            {"path": os.path.join(self.base, "c"), "sizeBytes": 50},
            {"path": os.path.join(self.base, "d"), "sizeBytes": 5},   # excluded
            {"path": os.path.join(self.base, "e"), "sizeBytes": 20},
        ]
        result = filters_module.apply_filters(items, filters=filters, now=NOW)
        self.assertEqual(
            [item["path"] for item in result["included"]],
            [items[0]["path"], items[2]["path"], items[4]["path"]],
        )
        self.assertEqual(
            [entry["item"]["path"] for entry in result["excluded"]],
            [items[1]["path"], items[3]["path"]],
        )


class BlockedTests(unittest.TestCase):
    """blocked(): the filtered-in-flux guard is a plain truth test."""

    def test_an_empty_exclusion_list_is_not_blocked(self):
        self.assertFalse(filters_module.blocked([]))

    def test_any_exclusion_blocks(self):
        self.assertTrue(filters_module.blocked([{"item": {}, "reason": "r"}]))
        self.assertTrue(
            filters_module.blocked(
                [{"item": {}, "reason": "r"}, {"item": {}, "reason": "s"}]
            )
        )

    def test_it_accepts_the_whole_apply_filters_result(self):
        result = {"included": [{"path": "/t/a", "sizeBytes": 1}], "excluded": []}
        self.assertFalse(filters_module.blocked(result))
        result["excluded"].append({"item": {}, "reason": "the item no longer exists"})
        self.assertTrue(filters_module.blocked(result))


class GeneratedTreeTests(unittest.TestCase):
    """End to end: parse a request, filter plan items from a generated tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cln-filters-tree-")
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def plan_items(self, shapes):
        items = []
        for name, size_bytes, age_seconds in shapes:
            path = os.path.join(self.base, name)
            with open(path, "wb") as handle:
                handle.write(b"0" * size_bytes)
            stamp = NOW - age_seconds
            os.utime(path, (stamp, stamp))
            items.append({"path": path, "sizeBytes": size_bytes})
        return items

    def test_plan_items_are_filtered_end_to_end(self):
        items = self.plan_items([
            ("fresh-small.bin", 500, 600),    # too fresh
            ("old-small.bin", 50, 100000),    # too old (age wins over size)
            ("old-good.bin", 5000, 40000),    # inside every window
            ("old-big.bin", 50000, 40000),    # too large
            ("edge-old.bin", 5000, 86400),    # exactly at the maximum age
        ])
        filters = filters_module.parse_filters({
            "minAgeSeconds": "1h",
            "maxAgeSeconds": "1d",
            "minSizeBytes": 100,
            "maxSizeBytes": 10000,
        })
        self.assertTrue(filters["active"])
        result = filters_module.apply_filters(items, filters=filters, now=NOW)
        self.assertEqual(
            [item["path"] for item in result["included"]],
            [items[2]["path"], items[4]["path"]],
        )
        self.assertEqual(
            [(entry["item"]["path"], entry["reason"]) for entry in result["excluded"]],
            [
                (items[0]["path"], "younger than the minimum age"),
                (items[1]["path"], "older than the maximum age"),
                (items[3]["path"], "above the maximum size"),
            ],
        )
        self.assertTrue(filters_module.blocked(result["excluded"]))

    def test_a_vanished_item_is_reported_as_gone(self):
        items = self.plan_items([("kept.bin", 500, 40000), ("doomed.bin", 500, 40000)])
        filters = filters_module.parse_filters({"minAgeSeconds": "30m"})
        os.remove(items[1]["path"])
        result = filters_module.apply_filters(items, filters=filters, now=NOW)
        self.assertEqual([item["path"] for item in result["included"]], [items[0]["path"]])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["the item no longer exists"],
        )
        self.assertTrue(filters_module.blocked(result))

    def test_without_filters_nothing_is_blocked(self):
        items = self.plan_items([("a.bin", 10, 100), ("b.bin", 20, 200000)])
        filters = filters_module.parse_filters({})
        self.assertFalse(filters["active"])
        result = filters_module.apply_filters(items, filters=filters, now=NOW)
        self.assertEqual(result["included"], items)
        self.assertEqual(result["excluded"], [])
        self.assertFalse(filters_module.blocked(result))

    def test_a_duration_only_request_filters_by_age_alone(self):
        items = self.plan_items([
            ("hour-old.bin", 10, 3600),
            ("week-old.bin", 10, 7 * 86400),
        ])
        filters = filters_module.parse_filters({"minAgeSeconds": "2h"})
        result = filters_module.apply_filters(items, filters=filters, now=NOW)
        self.assertEqual([item["path"] for item in result["included"]], [items[1]["path"]])
        self.assertEqual(
            [entry["reason"] for entry in result["excluded"]],
            ["younger than the minimum age"],
        )


if __name__ == "__main__":
    unittest.main()
