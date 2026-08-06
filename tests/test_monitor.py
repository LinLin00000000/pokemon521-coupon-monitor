import json
import tempfile
import unittest
from pathlib import Path

import monitor


FIXTURE = """
<div class="tgme_widget_message_wrap" data-post="pokemon521/100">
  <div class="tgme_widget_message_text js-message_text" dir="auto">八月兑换码：飞天螳螂<br>请到官网兑换</div>
  <a class="tgme_widget_message_photo_wrap" href="https://t.me/pokemon521/100" style="background-image:url('https://cdn4.telesco.pe/file/example.jpg')"></a>
  <time datetime="2026-08-01T03:44:06+00:00" class="time"></time>
  <div class="tgme_widget_message_replies"><a href="https://t.me/pokemon_love/200">12 comments</a></div>
</div>
<div class="tgme_widget_message_wrap" data-post="pokemon521/99">
  <div class="tgme_widget_message_text js-message_text" dir="auto">本月兑换码藏在图片里</div>
  <a class='tgme_widget_message_photo_wrap' style='background-image:url("https://cdn4.telesco.pe/file/clue.jpg")'></a>
  <time datetime="2026-07-01T03:44:06+00:00" class="time"></time>
</div>
"""


class MonitorTests(unittest.TestCase):
    def test_parse_history_and_media(self):
        messages = monitor.parse_public_history(FIXTURE)
        self.assertEqual([m.post_id for m in messages], [99, 100])
        message = messages[-1]
        self.assertEqual(message.published_at, "2026-08-01T03:44:06+00:00")
        self.assertIn("兑换码", message.text)
        self.assertIn("飞天螳螂", message.text)
        self.assertEqual(message.media_urls, ("https://cdn4.telesco.pe/file/example.jpg",))
        self.assertEqual(message.reply_url, "https://t.me/pokemon_love/200")
        self.assertEqual(message.reply_count, 12)

    def test_rules_extract_explicit_code_and_image_clue(self):
        messages = monitor.parse_public_history(FIXTURE)
        signals = [signal for message in messages for signal in monitor.extract_signals(message)]
        kinds = {(signal["post_id"], signal["kind"]) for signal in signals}
        self.assertIn((100, "text_code"), kinds)
        self.assertIn((99, "media_clue"), kinds)
        code = next(signal for signal in signals if signal["kind"] == "text_code")
        self.assertEqual(code["code_normalized"], "飞天螳螂")
        self.assertFalse(code["needs_manual_review"])

    def test_pagination_stops_on_duplicate_oldest(self):
        first = FIXTURE
        second = FIXTURE.replace('data-post="pokemon521/100"', 'data-post="pokemon521/80"', 1)
        pages = {
            "https://t.me/s/pokemon521": first,
            "https://t.me/s/pokemon521?before=99": second,
        }

        def fake_fetch(url):
            body = pages.get(url, second)
            return monitor.FetchResult(url, 200, url, "text/html", body)

        messages, page_count, visited = monitor.collect_public_channel(
            "https://t.me/s/pokemon521", max_messages=100, max_pages=3, fetcher=fake_fetch
        )
        self.assertGreaterEqual(page_count, 2)
        self.assertEqual(len(messages), 3)
        self.assertIn("before=99", visited[1])

    def test_history_is_idempotent(self):
        messages = monitor.parse_public_history(FIXTURE)
        signals = [signal for message in messages for signal in monitor.extract_signals(message)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            self.assertEqual(monitor.append_history(path, signals), 2)
            self.assertEqual(monitor.append_history(path, signals), 0)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
