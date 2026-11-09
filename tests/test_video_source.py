import asyncio
import unittest
from unittest.mock import patch
from video_source import newest_video, _parse_feed


XML=b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<yt:channelId>IFGLFUgxRufs0od0acMzuQ</yt:channelId>
<title>The Shmuley Show</title>
<entry><title>Older Upload</title><yt:videoId>AAAAAAAAAAA</yt:videoId>
<published>2026-11-04T00:00:00+00:00</published></entry>
<entry><title>Latest Published Episode</title><yt:videoId>BBBBBBBBBBB</yt:videoId>
<published>2026-11-05T00:00:00+00:00</published></entry>
</feed>'''


class Response:
    status_code=200
    content=XML
    def raise_for_status(self):pass


class FakeHTTP:
    def __init__(self):self.calls=[]
    async def get(self,url,**kw):
        self.calls.append((url,kw))
        return Response()


class VideoTests(unittest.TestCase):
    def test_official_feed_title_and_date(self):
        http=FakeHTTP()
        text,url=asyncio.run(newest_video(
            "what is Rabbi Shmuley's latest video called?",http))
        self.assertIn("Latest Published Episode",text)
        self.assertIn("2026-11-05",text)
        self.assertEqual(url,"https://www.youtube.com/watch?v=BBBBBBBBBBB")
        self.assertEqual(len(http.calls),1)
        self.assertIn("feeds/videos.xml",http.calls[0][0])

    def test_unidentified_creator_does_not_guess(self):
        http=FakeHTTP()
        self.assertEqual(asyncio.run(newest_video(
            "who is that random creator?",http)),("",""))
        self.assertEqual(http.calls,[])

    def test_mismatched_channel_rejected(self):
        with self.assertRaises(ValueError):
            _parse_feed(XML,"UC0000000000000000000000")


if __name__=="__main__":
    unittest.main()
