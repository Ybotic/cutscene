import unittest

from backend.services.captions import replace_caption_text


class CaptionEditTests(unittest.TestCase):
    def setUp(self):
        self.transcript = {
            "segments": [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "text": "Hello there",
                    "words": [
                        {"word": "Hello", "start": 1.0, "end": 1.4},
                        {"word": "there", "start": 1.5, "end": 2.0},
                    ],
                }
            ]
        }

    def test_same_word_count_preserves_whisper_timing(self):
        edited = replace_caption_text(self.transcript, "Hey there", 1.0, 2.0)

        self.assertEqual(edited["segments"][0]["words"][0]["word"], "Hey")
        self.assertEqual(edited["segments"][0]["words"][0]["start"], 1.0)
        self.assertEqual(edited["segments"][0]["words"][1]["end"], 2.0)

    def test_different_word_count_is_distributed_across_clip(self):
        edited = replace_caption_text(self.transcript, "A new caption", 1.0, 4.0)
        words = edited["segments"][0]["words"]

        self.assertEqual(len(words), 3)
        self.assertAlmostEqual(words[0]["start"], 1.0)
        self.assertAlmostEqual(words[-1]["end"], 4.0)

    def test_empty_caption_removes_burned_words(self):
        self.assertEqual(replace_caption_text(self.transcript, "", 1.0, 2.0), {"segments": []})


if __name__ == "__main__":
    unittest.main()
