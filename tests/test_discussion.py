import json
import tempfile
import unittest
from pathlib import Path

from discussion import extract_comment_consensus, parse_discussion_html


HTML = '''
<h3 class="tgme_post_discussion_header"><span class="js-header">4 comments</span></h3>
<form class="js-new_message_form">
  <input type="hidden" name="peer" value="-100123" />
  <input type="hidden" name="top_msg_id" value="395" />
  <input type="hidden" name="discussion_hash" value="public-hash" />
</form>
<div class="tme_messages_more" data-before="10" data-after="30"></div>
<div class="tgme_widget_message js-widget_message" data-post-id="20">
  <a class="tgme_widget_message_author_name" href="https://t.me/user_one">User One</a>
  <div class="tgme_widget_message_text js-message_text">飞天螳螂</div>
  <time datetime="2026-08-01T03:45:00+00:00"></time>
</div>
<div class="tgme_widget_message js-widget_message" data-post-id="21">
  <a class="tgme_widget_message_author_name" href="https://t.me/user_two">User Two</a>
  <div class="tgme_widget_message_text js-message_text">我猜是 飞天螳螂 吧</div>
  <time datetime="2026-08-01T03:46:00+00:00"></time>
</div>
<div class="tgme_widget_message js-widget_message" data-post-id="22">
  <a class="tgme_widget_message_author_name" href="https://t.me/user_three">User Three</a>
  <div class="tgme_widget_message_text js-message_text">飞天螳螂</div>
  <time datetime="2026-08-01T03:47:00+00:00"></time>
</div>
<div class="tgme_widget_message js-widget_message" data-post-id="23">
  <a class="tgme_widget_message_author_name" href="https://t.me/user_four">User Four</a>
  <div class="tgme_widget_message_text js-message_text">官网</div>
  <time datetime="2026-08-01T03:48:00+00:00"></time>
</div>
'''


class DiscussionTests(unittest.TestCase):
    def test_parse_widget_comments_and_cursors(self):
        parsed = parse_discussion_html(HTML)
        self.assertEqual(parsed["comment_count"], 4)
        self.assertEqual(parsed["next_before"], 10)
        self.assertEqual(parsed["next_after"], 30)
        self.assertEqual(parsed["fields"]["top_msg_id"], "395")
        self.assertEqual(len(parsed["comments"]), 4)
        self.assertEqual(parsed["comments"][0].text, "飞天螳螂")
        self.assertIsNotNone(parsed["comments"][0].author_key)

    def test_consensus_requires_known_name_and_distinct_public_authors(self):
        with tempfile.TemporaryDirectory() as directory:
            names_path = Path(directory) / "names.json"
            names_path.write_text(json.dumps({"names": ["飞天螳螂"]}, ensure_ascii=False), encoding="utf-8")
            names = {"飞天螳螂"}
        parsed = parse_discussion_html(HTML)
        signal = extract_comment_consensus(
            {"comments": parsed["comments"], "comment_count": 4, "loaded_count": 4},
            post_id=395,
            post_url="https://t.me/pokemon521/395",
            published_at="2026-08-01T03:44:00+00:00",
            pokemon_names=names,
        )
        self.assertEqual(len(signal), 1)
        self.assertEqual(signal[0]["code"], "飞天螳螂")
        self.assertEqual(signal[0]["matching_comment_count"], 3)
        self.assertEqual(signal[0]["distinct_author_count"], 3)

    def test_longest_canonical_name_wins_over_substring(self):
        from discussion import extract_pokemon_candidate

        names = {"地鼠", "三地鼠"}
        self.assertEqual(extract_pokemon_candidate("我猜是三地鼠吧", names), "三地鼠")
        self.assertIsNone(
            extract_pokemon_candidate("三地鼠和飞天螳螂", {"三地鼠", "飞天螳螂"})
        )


if __name__ == "__main__":
    unittest.main()
