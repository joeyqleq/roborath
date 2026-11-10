import unittest
from datetime import datetime,timezone,timedelta
from email.utils import format_datetime
import httpx
import news


def feed(title='Gaza update',url='https://example.org/report',when=None):
    stamp=format_datetime(when or datetime.now(timezone.utc))
    return f'<rss><channel><item><title>{title}</title><description>Publisher summary.</description><link>{url}</link><pubDate>{stamp}</pubDate></item></channel></rss>'.encode()


class NewsTests(unittest.IsolatedAsyncioTestCase):
    def test_dates_and_unsafe_urls(self):
        now=datetime.now(timezone.utc)
        self.assertEqual(news.parse_feed(feed(when=now-timedelta(days=3)),'BBC'),[])
        self.assertEqual(news.parse_feed(feed(when=now+timedelta(hours=1)),'BBC'),[])
        self.assertEqual(news.parse_feed(feed(url='https://127.0.0.1/secret'),'BBC'),[])
        with self.assertRaises(ValueError):news.parse_feed(b'<!DOCTYPE x><rss/>','BBC')
        self.assertFalse(news.is_news_query('how would you improve communism for 2026'))
        self.assertTrue(news.is_news_query('latest Gaza news'))

    async def test_cache_diversity_and_relevance(self):
        news._cache.clear();calls=[]
        def handler(request):
            calls.append(str(request.url));return httpx.Response(200,content=feed())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
            rows=await news.fetch_news('latest Israel news',h)
            self.assertEqual(len(rows),2)
            self.assertEqual(len({r['source'] for r in rows}),2)
            self.assertEqual(await news.fetch_news('latest Shapiro news',h),[])
            self.assertEqual(len(calls),2)
        news._cache.clear()

    async def test_failure_returns_no_invented_news(self):
        news._cache.clear()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as h:
            self.assertEqual(await news.fetch_news('latest Gaza news',h),[])
        news._cache.clear()
