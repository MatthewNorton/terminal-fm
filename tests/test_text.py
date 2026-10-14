"""Text clean-up around the local LLM and the DJ: the enhancer's self-contradiction guard
(_contradictions), llama-cli stdout filtering (_strip_cli_chrome) and the Stop-hook blurb
(_clean_blurb). All prompts here are synthetic."""

import unittest

from radio_test_support import radio


class Contradictions(unittest.TestCase):
    def test_genuine_contradictions_flagged(self):
        cases = [
            ("Brushed drums and warm upright bass. No beats, just a gentle groove.",
             ["'No beats' vs 'Brushed drums'"]),
            ("Ethereal choir pads drift slowly. Instrumental only, without vocals.",
             ["'without vocals' vs 'Ethereal choir'"]),
            ("Dry, close-miked piano with no reverb. A long echo trails each phrase.",
             ["'no reverb' vs 'A long echo'"]),
            ("Warm pads, no bass. A deep bassline enters later.",
             ["'no bass' vs 'A deep bassline'"]),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(radio._contradictions(text), want)

    def test_beatless_and_one_sided_prompts_not_flagged(self):
        # A false alarm costs a generation (egen refuses to spend), so these must stay clean.
        for text in (
            "No percussion, rhythm, or beat structure. Slow evolving drone pads.",
            "Ambient wash of strings without drums. Soft sub-bass swells beneath.",
            "Driving drums and a punchy kick, with no vocals.",
            "Beatless and weightless: no drums, no bass, no vocals. Only shimmering glass tones.",
            "Tight drums, deep bass, a lead vocal hook and lush reverb.",
            "",
        ):
            with self.subTest(text=text):
                self.assertEqual(radio._contradictions(text), [])

    def test_two_families_reported_together(self):
        got = radio._contradictions("Big drums and a choir. No percussion here. Sung without vocals.")
        self.assertEqual(len(got), 2)
        self.assertTrue(got[0].startswith("'No percussion'"))
        self.assertTrue(got[1].startswith("'without vocals'"))

    def test_negation_cue_reaches_to_sentence_start(self):
        # Documents current behaviour, which differs from the docstring's example: a cue anywhere
        # earlier in the sentence negates a term, so in "No vocals, with driving drums" the drums
        # count as denied, not described. A later "no percussion" therefore goes unflagged.
        self.assertEqual(radio._contradictions(
            "No vocals, with driving drums. The intro has no percussion."), [])


LLAMA_STDOUT = (
    "\x1b[0mLoading model... \n"
    "▄▄ ▄▄\n"
    "██ ██\n"
    "build      : b10069-abcdef\n"
    "model      : qwen3-4b-instruct-q4km.gguf\n"
    "modalities : text\n"
    "available commands:\n"
    "  /exit or Ctrl+C     stop or exit\n"
    "  /regen              regenerate the last response\n"
    "\r\n"
    "> lofi coffee music\r\n"
    "\r\n"
    "Warm lo-fi hip hop with dusty vinyl crackle.\r\n"
    "Soft Rhodes chords.\r\n"
    "\r\n"
    "[ Prompt: 120.5 t/s | Generation: 30.1 t/s ]\r\n"
    "\r\n"
    "Exiting...\r\n"
)


class StripCliChrome(unittest.TestCase):
    def test_banner_echo_and_footer_removed(self):
        self.assertEqual(radio._strip_cli_chrome(LLAMA_STDOUT, "lofi coffee music"),
                         "Warm lo-fi hip hop with dusty vinyl crackle.\nSoft Rhodes chords.")

    def test_no_marker_cuts_after_the_echoed_idea(self):
        out = "build : b1\nmodel : m\nlofi coffee music\nA dusty lofi beat.\n[ Prompt: 1 t/s ]\n"
        self.assertEqual(radio._strip_cli_chrome(out, "lofi coffee music"), "A dusty lofi beat.")

    def test_no_marker_no_idea_falls_back_to_chrome_regex(self):
        out = "build : b1\nmodel : m\n▀▀▀\nA dusty lofi beat.\nExiting...\n"
        self.assertEqual(radio._strip_cli_chrome(out, ""), "A dusty lofi beat.")

    def test_stops_at_a_second_prompt(self):
        out = "> idea\nThe answer.\n> \n> \n"
        self.assertEqual(radio._strip_cli_chrome(out, "idea"), "The answer.")

    def test_empty(self):
        self.assertEqual(radio._strip_cli_chrome("", ""), "")
        self.assertEqual(radio._strip_cli_chrome(None, "x"), "")


class CleanBlurb(unittest.TestCase):
    def test_question_dropped(self):
        self.assertEqual(
            radio._clean_blurb("I fixed the playlist bug and added a regression test. Want me to push it?"),
            "I fixed the playlist bug and added a regression test.")

    def test_markdown_code_links_and_lists_stripped(self):
        text = ("## Done\n\n- **Built** the `radio.py` parser\n"
                "- Wired the [hook](http://example.com) into Stop\n\n```py\nprint(1)\n```\n")
        self.assertEqual(radio._clean_blurb(text), "Built the radio.py parser. Wired the hook into Stop.")

    def test_tables_skipped(self):
        text = "| a | b |\n|---|---|\n| 1 | 2 |\nUpdated the table renderer to align columns."
        self.assertEqual(radio._clean_blurb(text), "Updated the table renderer to align columns.")

    def test_filler_opener_dropped_and_capitalised(self):
        self.assertEqual(radio._clean_blurb("Okay, I rewired the hook so the DJ speaks between tracks."),
                         "I rewired the hook so the DJ speaks between tracks.")
        self.assertEqual(radio._clean_blurb("so, removed the old cache and rebuilt the index."),
                         "Removed the old cache and rebuilt the index.")

    def test_too_short_returns_empty_for_the_generic_line(self):
        for text in ("", "ok", "Done.", "```\ncode only\n```", "---"):
            with self.subTest(text=text):
                self.assertEqual(radio._clean_blurb(text), "")

    def test_length_capped(self):
        long = "I updated the parser so that " + "very " * 100 + "long lines work."
        out = radio._clean_blurb(long)
        self.assertLessEqual(len(out), 280)
        self.assertTrue(out.startswith("I updated the parser"))
        # Documents current behaviour: a single sentence over the cap is cut mid-word.
        self.assertEqual(len(out), 280)

    def test_only_questions_left_are_kept(self):
        # Documents current behaviour: when every sentence is a question or directed at the user,
        # the filter falls back to them rather than returning nothing.
        self.assertEqual(radio._clean_blurb("Should I keep going? Let me know."),
                         "Should I keep going? Let me know.")


if __name__ == "__main__":
    unittest.main()
