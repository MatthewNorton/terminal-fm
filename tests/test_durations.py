"""Track length: a length written in the prompt (_stated_duration), a stray DURATION: line from
the enhancer (_split_duration), and gen's auto-pick (pick_duration)."""

import unittest
from unittest import mock

from radio_test_support import radio, reset_home


class StatedDuration(unittest.TestCase):
    # The cases CLAUDE.md names (80s synthwave, 74 BPM, 6/8, an 8 second reverb tail, 600 second
    # clamped to 380) plus the stated-length forms around them.
    CASES = [
        ("90 second cinematic trailer build", 90),
        ("3 second phone notification chime", 3),
        ("a 30-second commercial bed", 30),
        ("2 minute ambient piece", 120),
        ("5 min intro", 300),
        ("45 secs", 45),
        ("80s synthwave", None),                 # a decade, not a length
        ("74 BPM lofi groove", None),
        ("waltz in 6/8", None),
        ("an 8 second reverb tail", None),       # times a sound, not the clip
        ("track with 2 sec delay", None),
        ("a very long six minute build", None),  # spelled-out number: left to the model
        ("600 second drone", 380),               # clamped to ENH_DUR_MAX
        ("10 minutes of rain", 380),
        ("0 seconds of silence", 1),             # clamped to ENH_DUR_MIN
        ("", None),
        (None, None),
    ]

    def test_cases(self):
        for text, want in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(radio._stated_duration(text), want)

    def test_bounds_are_the_documented_range(self):
        self.assertEqual((radio.ENH_DUR_MIN, radio.ENH_DUR_MAX), (1, 380))

    def test_first_stated_length_wins(self):
        # Documents current behaviour: only the first match counts, so "2 minutes 30 seconds"
        # reads as 120, not 150.
        self.assertEqual(radio._stated_duration("2 minutes 30 seconds"), 120)
        # A sound-timing number is skipped and the next stated length is used.
        self.assertEqual(radio._stated_duration("a 4 second fade out then 20 seconds of pads"), 20)


class SplitDuration(unittest.TestCase):
    def test_no_marker(self):
        self.assertEqual(radio._split_duration("  No marker here.  "), ("No marker here.", None))

    def test_marker_removed_from_prompt(self):
        self.assertEqual(radio._split_duration("Warm lofi. DURATION: 150 seconds"), ("Warm lofi", 150))
        self.assertEqual(radio._split_duration("Pads (Duration - 45s)"), ("Pads", 45))
        self.assertEqual(radio._split_duration("Lofi, DURATION: 90s - slow and warm"),
                         ("Lofi - slow and warm", 90))

    def test_clamped(self):
        self.assertEqual(radio._split_duration("DURATION: 999"), ("", 380))
        self.assertEqual(radio._split_duration("duration=0"), ("", 1))


class PickDuration(unittest.TestCase):
    def setUp(self):
        reset_home()
        cfg = radio.load_config()
        cfg["stability_api"]["duration"] = 77
        p = mock.patch.object(radio, "CONFIG", cfg)
        p.start()
        self.addCleanup(p.stop)

    def no_model(self):
        return mock.patch.object(radio, "_llm_paths", return_value=(None, None))

    def test_keyword_rules_when_no_model(self):
        cases = [
            ("phone notification chime", 5), ("a short sting", 5),
            ("radio station jingle", 15), ("podcast bumper", 15),
            ("lofi commercial bed", 30),          # use-case word beats the genre (checked first)
            ("dark ambient drone", 300),
            ("dark techno warehouse", 240),
            ("epic trailer", 120), ("fast punk", 120),
            ("synthwave night drive", 150), ("lo-fi study beats", 150), ("hip hop", 150),
        ]
        with self.no_model(), mock.patch.object(radio, "_llm_run") as llm:
            for text, want in cases:
                with self.subTest(text=text):
                    self.assertEqual(radio.pick_duration(text), (want, "keyword rules decided", ""))
            llm.assert_not_called()

    def test_whole_words_only_then_config_default(self):
        with self.no_model():
            for text in ("a quiet field recording", "pops and clicks", "stinging strings", ""):
                with self.subTest(text=text):
                    self.assertEqual(radio.pick_duration(text), (77, "config default", ""))

    def test_stated_length_beats_everything(self):
        with self.no_model():
            self.assertEqual(radio.pick_duration("90 second trailer"), (90, "as stated", ""))
        with mock.patch.object(radio, "_llm_paths", return_value=("llama-cli", "m.gguf")), \
                mock.patch.object(radio, "_llm_run") as llm:
            self.assertEqual(radio.pick_duration("a 600 second techno build"), (380, "as stated", ""))
            llm.assert_not_called()

    def test_model_answer_parsed_and_clamp_reported(self):
        with mock.patch.object(radio, "_llm_paths", return_value=("llama-cli", "m.gguf")):
            with mock.patch.object(radio, "_llm_run", return_value="DURATION: 95 - mellow groove"):
                self.assertEqual(radio.pick_duration("mellow groove"), (95, "local model decided", ""))
            with mock.patch.object(radio, "_llm_run", return_value="DURATION: 999 - huge"):
                self.assertEqual(radio.pick_duration("huge"),
                                 (380, "local model decided", " (model said 999s)"))
            with mock.patch.object(radio, "_llm_run", return_value="about 42 seconds"):
                self.assertEqual(radio.pick_duration("odd answer"), (42, "local model decided", ""))
            # No number in the answer: the keyword rules decide, as with no model.
            with mock.patch.object(radio, "_llm_run", return_value="I cannot say"):
                self.assertEqual(radio.pick_duration("dark techno"), (240, "keyword rules decided", ""))


if __name__ == "__main__":
    unittest.main()
