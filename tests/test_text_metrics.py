import unittest
from text_metrics import content_counts


class ContentMetricsTests(unittest.TestCase):
    def test_username_labels_mentions_and_spaces_do_not_count(self):
        self.assertEqual(content_counts('alice: @bob Hello world!',username='alice'),(2,11))
        self.assertEqual(content_counts('bob, Hello\tworld!\n',reply_username='bob'),(2,11))
        self.assertEqual(content_counts('@alice @bob'),(0,0))
        self.assertEqual(content_counts('Hello world!'),(2,11))

    def test_names_in_ordinary_prose_are_message_content(self):
        self.assertEqual(content_counts('I asked Bob yesterday.'),(4,19))
        self.assertEqual(content_counts('مرحبا يا عالم'),(3,11))
