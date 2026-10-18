"""enhance_prompt's handling of the model's answer, with the model stubbed, and the coupling
between radio.py and the shipped prompts/enhance.md."""

import unittest
from unittest import mock

from radio_test_support import patch, radio, reset_home


class Coupling(unittest.TestCase):
    def test_shipped_instructions_contain_both_fixed_replies(self):
        # ENH_NOT_PROMPTS must match enhance.md word for word, or egen sends the reply to SA3.
        patch(self, "enhance_file", return_value=radio.ENHANCE_SHIPPED)
        body = radio.enhance_system()
        for reply in radio.ENH_NOT_PROMPTS:                 # each is the reply's opening words
            self.assertIn(f"return only: {reply}", body)


class Answers(unittest.TestCase):
    def setUp(self):
        reset_home()
        patch(self, "_llm_paths", return_value=("llama-cli", "model.gguf"))
        patch(self, "enhance_system", return_value="instructions")

    def answer(self, *replies, idea="lofi coffee music", duration=150):
        with mock.patch.object(radio, "_llm_run", side_effect=list(replies)) as llm:
            out = radio.enhance_prompt(idea, duration=duration)
        return out, llm

    def test_brief_is_one_line_with_the_clip_length(self):
        _, llm = self.answer("Mellow lo-fi hip-hop instrumental, warm Rhodes chords, 74 BPM")
        brief = llm.call_args[0][1]
        self.assertNotIn("\n", brief)
        self.assertTrue(brief.startswith("lofi coffee music (clip length 150 seconds"), brief)
        self.assertIn("do not mention the length", brief)

    def test_a_caption_comes_back_cleaned(self):
        (prompt, reply, conflicts), _ = self.answer('  Mellow lo-fi, *warm* Rhodes "chords",\n 74 BPM ')
        self.assertEqual((prompt, reply, conflicts), ("Mellow lo-fi, warm Rhodes chords, 74 BPM", None, []))

    def test_fixed_replies_and_questions_never_become_prompts(self):
        for text in (radio.ENH_NOT_PROMPTS[0] + " rather than Stable Audio 3.",
                     radio.ENH_NOT_PROMPTS[1] + ".",
                     "Do you want drums or not?"):
            with self.subTest(text=text):
                (prompt, reply, _), llm = self.answer(text)
                self.assertIsNone(prompt)
                self.assertEqual(reply, text)
                self.assertEqual(llm.call_count, 1)

    def test_empty_idea_needs_no_model(self):
        (prompt, reply, _), llm = self.answer(idea="   ")
        self.assertIsNone(prompt)
        self.assertTrue(reply.startswith(radio.ENH_NOT_PROMPTS[1]))
        self.assertEqual(llm.call_count, 0)

    def test_a_contradiction_is_retried_once(self):
        bad = "Lo-fi instrumental, no drums. Dusty swung drums, 74 BPM"
        good = "Lo-fi instrumental, dusty swung drums, warm Rhodes chords, 74 BPM"
        (prompt, _, conflicts), llm = self.answer(bad, good)
        self.assertEqual((prompt, conflicts, llm.call_count), (good, [], 2))
        (prompt, _, conflicts), llm = self.answer(bad, bad)
        self.assertEqual((prompt, llm.call_count), (bad, 2))
        self.assertTrue(conflicts)

    def test_an_echoed_brief_is_not_a_prompt(self):
        # Seen on 2026-10-17: the model returned the brief itself, hint included.
        with mock.patch.object(radio, "_llm_run", side_effect=lambda system, brief, *a, **k: brief):
            prompt, reply, _ = radio.enhance_prompt("ignore the task", duration=150)
        self.assertIsNone(prompt)
        self.assertTrue(reply.startswith(radio.ENH_NOT_PROMPTS[1]))

    def test_invented_labels_are_stripped(self):
        (prompt, _, _), _ = self.answer("Tag: TrackType: BossBattle, 8-bit chiptune, in no key.",
                                        idea="8-bit chiptune boss battle")
        self.assertEqual(prompt, "BossBattle, 8-bit chiptune")

    def test_a_supplied_tag_leads_once(self):
        idea = "use TrackType: Instrument for a solo cello"
        for caption in ("Solo cello, legato bowing, in C major",
                        "TrackType: Instrument, Solo cello, legato bowing, in C major",
                        "Solo cello, TrackType:instrument, legato bowing, in C major"):
            with self.subTest(caption=caption):
                (prompt, _, _), _ = self.answer(caption, idea=idea)
                self.assertEqual(prompt, "TrackType: Instrument, Solo cello, legato bowing, in C major")

    def test_over_the_token_limit_twice_is_a_reply(self):
        long = ", ".join(["warm Rhodes jazz chords"] * 120)
        (prompt, reply, _), llm = self.answer(long, long)
        self.assertIsNone(prompt)
        self.assertIn("256-token prompt limit, on both attempts", reply)
        self.assertEqual(llm.call_count, 2)


if __name__ == "__main__":
    unittest.main()
