"""prompt_tokens: Stable Audio 3's 256-token prompt check.

The real T5Gemma tokenizer.json is 34 MB and gated, so it never ships. These tests write a tiny
synthetic tokenizer.json (a handful of merges plus the 256 byte-fallback tokens, about 5 KB) into
the temporary data directory, where radio.py looks for llm/t5gemma-tokenizer.json. The expected
counts were cross-checked against Hugging Face `tokenizers` 0.22.1 loading the same fixture
(17 strings, 0 mismatches, 2026-10-12); `tokenizers` is not needed to run these tests.
"""

import json
import unittest

from radio_test_support import radio, reset_home

SPACE = "▁"


def fixture(string_merges=False):
    vocab = {"<unk>": 0, "<eos>": 1, "\n\n": 2}
    for b in range(256):
        vocab["<0x%02X>" % b] = len(vocab)
    for t in ["a", "b", "c", "x", SPACE, "ab", "abc", SPACE + "a", "xx"]:
        vocab[t] = len(vocab)
    merges = [["a", "b"], ["ab", "c"], [SPACE, "a"], ["x", "x"]]
    if string_merges:                       # the older tokenizer.json spelling: "a b"
        merges = [" ".join(m) for m in merges]
    flags = {"single_word": False, "lstrip": False, "rstrip": False, "normalized": False}
    added = [dict(flags, id=1, content="<eos>", special=True),
             dict(flags, id=2, content="\n\n", special=False)]
    return {                                # a complete tokenizer.json, loadable by HF `tokenizers`
        "version": "1.0", "truncation": None, "padding": None,
        "post_processor": None, "decoder": None,
        "added_tokens": added,
        "normalizer": {"type": "Replace", "pattern": {"String": " "}, "content": SPACE},
        "pre_tokenizer": {"type": "Split", "pattern": {"String": " "},
                          "behavior": "MergedWithPrevious", "invert": False},
        "model": {"type": "BPE", "unk_token": "<unk>", "fuse_unk": True, "byte_fallback": True,
                  "ignore_merges": False, "vocab": vocab, "merges": merges},
    }


CASES = [
    ("", 0),
    ("abc", 1),
    ("abcabc", 2),
    ("abc abc", 3),            # space becomes U+2581; "ab" (rank 0) beats U+2581+"a" (rank 2)
    ("ab ab", 3),
    (" a", 1),                 # U+2581 + "a" merges
    ("a b c", 5),
    ("cab", 2),
    ("xxx", 2),                # equal ranks: leftmost pair merges first
    ("xxxx", 2),
    ("  ", 2),
    ("é", 2),             # not in the vocab: one token per UTF-8 byte
    ("€", 3),
    ("abc<eos>abc", 3),        # added tokens match whole
    ("a\n\nb", 3),
    ("\n\n\n\n", 2),
    ("éabc €xx<eos>", 9),
]


class PromptTokensExact(unittest.TestCase):
    def setUp(self):
        reset_home()
        radio.LLM_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(setattr, radio, "_TOKENIZER", None)

    def write(self, obj):
        radio.TOKENIZER_FILE.write_text(json.dumps(obj), encoding="utf-8")
        radio._TOKENIZER = None

    def test_tokenizer_file_is_where_the_code_looks(self):
        self.assertEqual(radio.TOKENIZER_FILE, radio.ROOT / "llm" / "t5gemma-tokenizer.json")

    def test_counts(self):
        self.write(fixture())
        for text, want in CASES:
            with self.subTest(text=text):
                self.assertEqual(radio.prompt_tokens(text), (want, True))

    def test_string_form_merges(self):
        self.write(fixture(string_merges=True))
        for text, want in CASES:
            with self.subTest(text=text):
                self.assertEqual(radio.prompt_tokens(text), (want, True))

    def test_description_of_an_exact_count(self):
        self.assertEqual(radio._tokens_desc(12, True), "12 tokens")


class PromptTokensEstimate(unittest.TestCase):
    def setUp(self):
        reset_home()
        self.addCleanup(setattr, radio, "_TOKENIZER", None)

    def test_ceil_chars_over_four_without_tokenizer(self):
        self.assertFalse(radio.TOKENIZER_FILE.exists())
        for text, want in (("", 0), ("a", 1), ("abcd", 1), ("abcde", 2),
                           ("x" * 1024, 256), ("x" * 1025, 257)):
            with self.subTest(n=len(text)):
                self.assertEqual(radio.prompt_tokens(text), (want, False))
        self.assertIn("estimated", radio._tokens_desc(257, False))

    def test_unreadable_tokenizer_falls_back_to_estimate(self):
        radio.LLM_DIR.mkdir(parents=True, exist_ok=True)
        for junk in ("{not json", json.dumps({"model": {}})):
            with self.subTest(junk=junk):
                radio.TOKENIZER_FILE.write_text(junk, encoding="utf-8")
                radio._TOKENIZER = None
                self.assertEqual(radio.prompt_tokens("abcde"), (2, False))


if __name__ == "__main__":
    unittest.main()
