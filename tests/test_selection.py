"""Track-number selections: `radio play 1,3,5-8` / `radio playlist ...` (looks_like_selection,
parse_selection)."""

import time
import unittest

from radio_test_support import radio


class LooksLikeSelection(unittest.TestCase):
    def test_numbers_and_ranges(self):
        for toks in (["1"], ["1,3,5-8"], ["1", "2", "4"], ["8-5"], ["1, 3"], ["10-2,4"]):
            with self.subTest(toks=toks):
                self.assertTrue(radio.looks_like_selection(toks))

    def test_not_a_selection(self):
        for toks in ([], [""], ["--say"], ["chill"], ["1-"], ["-3"], ["1-2-3"], ["1.5"],
                     ["1", "x"], ["C:/music"], ["3-a"]):
            with self.subTest(toks=toks):
                self.assertFalse(radio.looks_like_selection(toks))


class ParseSelection(unittest.TestCase):
    def test_order_kept_and_repeats_kept(self):
        self.assertEqual(radio.parse_selection(["3,1,3"], 5), [3, 1, 3])
        self.assertEqual(radio.parse_selection(["2", "2"], 5), [2, 2])

    def test_ascending_and_descending_ranges(self):
        self.assertEqual(radio.parse_selection(["5-8"], 10), [5, 6, 7, 8])
        self.assertEqual(radio.parse_selection(["8-5"], 10), [8, 7, 6, 5])
        self.assertEqual(radio.parse_selection(["5-3,1 2"], 4), [4, 3, 1, 2])

    def test_out_of_range_dropped(self):
        self.assertEqual(radio.parse_selection(["0", "3", "12"], 10), [3])
        self.assertEqual(radio.parse_selection(["9-12"], 10), [9, 10])     # range clipped to 1..n
        self.assertEqual(radio.parse_selection(["11-20"], 10), [])         # wholly outside
        self.assertEqual(radio.parse_selection(["0-0"], 10), [])
        self.assertEqual(radio.parse_selection(["1-3"], 0), [])            # empty library

    def test_junk_tokens_ignored(self):
        self.assertEqual(radio.parse_selection(["a", "2", "1-x"], 5), [2])

    def test_huge_range_is_clamped_before_iterating(self):
        # Before 2026-09-28 the typed range was iterated and filtered afterwards: 1-50000000 took
        # 1.26 s and one more digit hung. The clamp bounds the work by the library size.
        for tok in ("1-50000000", "1-99999999999", "99999999999-1"):
            with self.subTest(tok=tok):
                t0 = time.perf_counter()
                got = radio.parse_selection([tok], 10)
                elapsed = time.perf_counter() - t0
                self.assertEqual(sorted(got), list(range(1, 11)))
                self.assertLess(elapsed, 0.1)
        self.assertEqual(radio.parse_selection(["99999999999-1"], 3), [3, 2, 1])


if __name__ == "__main__":
    unittest.main()
