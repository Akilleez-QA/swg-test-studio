import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from swg_test_studio import model, recording
from swg_test_studio.clips import parse_ranges, validate_ranges
from test_journey import capture


class ClipTests(unittest.TestCase):
    def records(self):
        unsupported = dict(capture()[0], event="movement_requested", data={"capture_contract": 2})
        records = [unsupported] + capture() + [copy.deepcopy(unsupported)] + capture()
        for index, event in enumerate(records):
            event["sequence"] = index + 1
        return records

    def draft(self, records, ranges=None, errors=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            meta = {"actors": {"123": {"role": "actor"}}}
            with patch.object(recording, "load", return_value=(None, meta, root)), patch.object(recording, "status", return_value={
                    "state": "stopped", "errors": errors or [], "events": records}):
                return recording.draft(root, "a" * 32, "selected_cases", "Selected cases", ranges)

    def test_explicit_clips_keep_raw_history_and_create_independent_cases(self):
        records = self.records()
        original = copy.deepcopy(records)
        self.assertTrue(self.draft(records)["review"]["unsupported"])
        ranges = parse_ranges(["2:5", "7:10"])
        draft = self.draft(records, ranges)
        self.assertEqual(records, original)
        self.assertEqual(draft["review"]["capture_ranges"], ranges)
        self.assertFalse(draft["review"]["approved"])
        self.assertEqual(draft["review"]["unsupported"], [])
        self.assertEqual(len(draft["steps"]), 2)
        self.assertTrue(all(s["options"]["prepare_start"] for s in draft["steps"]))
        draft["review"]["approved"] = True
        model.validate(draft, runnable=True)

    def test_unsupported_or_incomplete_events_inside_a_clip_still_block(self):
        for ranges in ([[{"first": 1, "last": 5}]], [[{"first": 3, "last": 5}]]):
            draft = self.draft(self.records(), ranges[0])
            self.assertTrue(draft["review"]["unsupported"])
            draft["review"]["approved"] = True
            with self.assertRaises(ValueError): model.validate(draft, runnable=True)

    def test_clipping_never_hides_capture_corruption_or_missing_events(self):
        with self.assertRaises(ValueError):
            self.draft(self.records(), [{"first": 2, "last": 5}], errors=["capture error"])
        with self.assertRaises(ValueError):
            self.draft(self.records(), [{"first": 2, "last": 20}])

    def test_range_types_order_overlap_bounds_and_source_identity_are_strict(self):
        for value in ([], [{"first": True, "last": 4}], [{"first": 0, "last": 4}],
                      [{"first": 1, "last": 4097}], [{"first": 4, "last": 3}],
                      [{"first": 1, "last": 4}, {"first": 4, "last": 7}],
                      [{"first": 5, "last": 6}, {"first": 1, "last": 3}]):
            with self.subTest(value=value), self.assertRaises(ValueError): validate_ranges(value)
        for value in ("1", "0:2", "1:99999", "1:2;command", " 1:2"):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_ranges([value])
        draft = self.draft(self.records(), [{"first": 2, "last": 5}])
        draft["review"]["recording"] = None
        with self.assertRaises(ValueError): model.validate(draft)
