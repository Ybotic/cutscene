import unittest

from backend.services.downloader import DownloadError, validate_youtube_url


class YouTubeUrlValidationTests(unittest.TestCase):
    def test_accepts_supported_youtube_hosts(self):
        for url in (
            "https://www.youtube.com/watch?v=example",
            "https://m.youtube.com/watch?v=example",
            "https://youtu.be/example",
            "http://youtube.com/watch?v=example",
        ):
            with self.subTest(url=url):
                validate_youtube_url(url)

    def test_rejects_non_youtube_hosts_and_url_authority_smuggling(self):
        for url in (
            "http://127.0.0.1/",
            "https://youtube.com.attacker.test/watch?v=example",
            "https://youtube.com@127.0.0.1/watch?v=example",
            "https://user@youtube.com/watch?v=example",
        ):
            with self.subTest(url=url), self.assertRaises(DownloadError):
                validate_youtube_url(url)

    def test_rejects_nonstandard_ports_and_malformed_urls(self):
        for url in (
            "https://youtube.com:8080/watch?v=example",
            "http://youtube.com:443/watch?v=example",
            "https://youtube.com:99999/watch?v=example",
            "https://youtube.com\n@attacker.test/watch?v=example",
            "https://youtube.com/\x00watch?v=example",
            f"https://youtube.com/{'a' * 2048}",
        ):
            with self.subTest(url=url), self.assertRaises(DownloadError):
                validate_youtube_url(url)


if __name__ == "__main__":
    unittest.main()
