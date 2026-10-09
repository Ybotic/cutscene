import unittest

from backend.services.caption_translation import (
    contains_devanagari,
    should_transliterate,
    transliterate_hindi_captions,
)


class HindiCaptionDetectionTests(unittest.TestCase):
    def test_detects_devanagari_script(self):
        self.assertTrue(contains_devanagari("नमस्ते dost"))
        self.assertFalse(contains_devanagari("namaste dost"))

    def test_detection_uses_whisper_language_or_script(self):
        self.assertTrue(should_transliterate("नमस्ते", "en"))
        self.assertTrue(should_transliterate("kya haal hai", "hi"))
        self.assertFalse(should_transliterate("hello there", "en"))

    def test_non_hindi_captions_skip_model_call(self):
        captions = {1: "Hello there"}
        self.assertEqual(
            transliterate_hindi_captions(captions, "en"), captions
        )


if __name__ == "__main__":
    unittest.main()
