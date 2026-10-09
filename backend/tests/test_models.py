import unittest

from backend.models import GenerateRequest


class GenerateRequestTests(unittest.TestCase):
    def test_caption_language_is_not_a_user_selectable_request_field(self):
        self.assertNotIn("caption_language", GenerateRequest.model_fields)


if __name__ == "__main__":
    unittest.main()
