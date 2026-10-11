import unittest

from pydantic import ValidationError

from backend.models import GenerateRequest, ReviewRequest


class GenerateRequestTests(unittest.TestCase):
    def test_caption_language_is_not_a_user_selectable_request_field(self):
        self.assertNotIn("caption_language", GenerateRequest.model_fields)

    def test_defaults_to_three_clips(self):
        request = GenerateRequest(youtube_url="https://youtu.be/example")
        self.assertEqual(request.clip_count, 3)

    def test_accepts_requested_counts_between_one_and_five(self):
        for count in (1, 2, 3, 4, 5):
            with self.subTest(count=count):
                request = GenerateRequest(
                    youtube_url="https://youtu.be/example", clip_count=count
                )
                self.assertEqual(request.clip_count, count)

    def test_rejects_clip_counts_outside_one_to_five(self):
        for count in (0, 6):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                GenerateRequest(
                    youtube_url="https://youtu.be/example", clip_count=count
                )


class ReviewRequestTests(unittest.TestCase):
    @staticmethod
    def clip(candidate_id):
        return {
            "candidate_id": candidate_id,
            "title": f"Clip {candidate_id}",
            "start": 0,
            "end": 10,
        }

    def test_accepts_one_to_five_clips(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                request = ReviewRequest(
                    clips=[self.clip(candidate_id) for candidate_id in range(count)]
                )
                self.assertEqual(len(request.clips), count)

    def test_rejects_empty_and_more_than_five_clips(self):
        for count in (0, 6):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                ReviewRequest(
                    clips=[self.clip(candidate_id) for candidate_id in range(count)]
                )


if __name__ == "__main__":
    unittest.main()
