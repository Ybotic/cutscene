import unittest

from pydantic import ValidationError

from backend.models import GenerateRequest


class CaptionLanguageRequestTests(unittest.TestCase):
    def test_auto_detection_is_the_default(self):
        request = GenerateRequest(youtube_url="https://youtu.be/example")
        self.assertEqual(request.caption_language, "auto")

    def test_original_script_can_be_selected(self):
        request = GenerateRequest(
            youtube_url="https://youtu.be/example",
            caption_language="original",
        )
        self.assertEqual(request.caption_language, "original")

    def test_unknown_caption_language_is_rejected(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                youtube_url="https://youtu.be/example",
                caption_language="something-else",
            )


if __name__ == "__main__":
    unittest.main()
