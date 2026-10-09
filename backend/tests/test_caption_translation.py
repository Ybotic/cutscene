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

    def test_auto_mode_uses_whisper_language_or_script_detection(self):
        self.assertTrue(should_transliterate("नमस्ते", "en", "auto"))
        self.assertTrue(should_transliterate("kya haal hai", "hi", "auto"))
        self.assertFalse(should_transliterate("hello there", "en", "auto"))

    def test_original_mode_never_transliterates(self):
        self.assertFalse(should_transliterate("नमस्ते", "hi", "original"))

    def test_non_hindi_auto_captions_skip_model_call(self):
        captions = {1: "Hello there"}
        self.assertEqual(
            transliterate_hindi_captions(captions, "en", "auto"), captions
        )

    def test_original_mode_keeps_devanagari_text(self):
        captions = {1: "नमस्ते"}
        self.assertEqual(
            transliterate_hindi_captions(captions, "hi", "original"), captions
        )


if __name__ == "__main__":
    unittest.main()
