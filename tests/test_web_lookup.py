import asyncio
import unittest
from web_lookup import needs_lookup,lookup


class Response:
    def __init__(self, data):
        self.data=data
    def raise_for_status(self):
        pass
    def json(self):
        return self.data


class WeatherClient:
    async def get(self,url,params=None,timeout=None):
        if "geocoding" in url:
            return Response({"results":[{"name":"Tajikistan","country":"Tajikistan",
                       "feature_code":"PCLI","latitude":39.0,"longitude":71.0}]})
        return Response({"current":{"time":"2026-11-09T21:00","temperature_2m":-4.6,
                          "relative_humidity_2m":90,"precipitation":0.1,
                          "wind_speed_10m":2.8,"weather_code":73},
                         "timezone":"Asia/Dushanbe"})


class WebLookupTests(unittest.TestCase):
    def test_searxng_results_are_bounded_valid_and_not_treated_as_evidence(self):
        from unittest.mock import patch
        from web_lookup import _search_sync, _searx_failures

        class SearchResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def iter_bytes(self): return iter([b'{"results":[]}'])
            def raise_for_status(self): pass
        class SearchResponseWithResults(SearchResponse):
            def iter_bytes(self):
                import json
                return iter([json.dumps({"results": [
                    {"title": "First result", "url": "https://example.com/story"},
                    {"title": "Duplicate domain", "url": "https://www.example.com/other"},
                    {"title": "Private destination", "url": "http://127.0.0.1/admin"},
                    {"title": "Second source", "url": "https://news.example.org/story"},
                ]}).encode()])

        with patch.dict("os.environ", {"ROBORATH_SEARXNG_URLS": "http://searx.internal:8080"}), \
             patch("web_lookup.httpx.stream", return_value=SearchResponseWithResults()) as get, \
             patch("web_lookup._ddgs_search", side_effect=AssertionError("fallback should not run")), \
             patch("web_lookup._bing_rss", side_effect=AssertionError("fallback should not run")):
            _searx_failures.clear()
            answer, domain = _search_sync("find a story")

        self.assertEqual(domain, "example.com")
        self.assertIn("First result", answer)
        self.assertIn("Second source", answer)
        self.assertNotIn("Duplicate domain", answer)
        self.assertNotIn("Private destination", answer)
        self.assertNotIn("provider snippet", answer)
        self.assertIn("titles are not verified facts", answer)
        self.assertEqual(get.call_args.kwargs["timeout"], 4)
        self.assertFalse(get.call_args.kwargs["follow_redirects"])

    def test_malformed_or_private_searx_origins_are_skipped(self):
        from unittest.mock import patch
        from web_lookup import _searxng
        with patch.dict("os.environ", {"ROBORATH_SEARXNG_URLS":
                "http://user:pass@search.example,https://search.example/path?token=x"}), \
             patch("web_lookup.httpx.get") as get:
            self.assertEqual(_searxng("query"), [])
        get.assert_not_called()

    def test_searxng_failure_is_temporarily_cooled_and_falls_back(self):
        from unittest.mock import patch
        from web_lookup import _search_sync, _searx_failures
        with patch.dict("os.environ", {"ROBORATH_SEARXNG_URLS": "https://search.example"}), \
             patch("web_lookup.httpx.get", side_effect=RuntimeError("network down")), \
             patch("web_lookup._ddgs_search", return_value=[
                 {"href": "https://docs.example.org/guide", "title": "A result"}]), \
             patch("web_lookup._bing_rss", return_value=[]):
            _searx_failures.clear()
            answer, domain = _search_sync("docs guide")
            self.assertIn("https://search.example", _searx_failures)
            _search_sync("docs guide")
        self.assertEqual(domain, "docs.example.org")

    def test_search_rejects_non_https_or_ip_result_links(self):
        from web_lookup import _format_results
        answer, domain = _format_results([
            {"href": "http://insecure.example/path", "title": "HTTP"},
            {"href": "https://127.0.0.1/admin", "title": "Loopback"},
        ])
        self.assertEqual((answer, domain), ("", ""))

    def test_live_detection(self):
        self.assertFalse(needs_lookup("hello roborath"))
        self.assertFalse(needs_lookup("what do you know about mario kart?"))
        self.assertTrue(needs_lookup("weather in Tajikistan right now"))
        self.assertTrue(needs_lookup("latest news in Japan"))

    def test_bing_rss_filters_irrelevant_dictionary_results(self):
        from unittest.mock import patch
        from web_lookup import _bing_rss
        xml = b"""<?xml version="1.0"?><rss><channel>
        <item><title>WON Definition and Meaning</title><link>https://www.dictionary.com/won</link></item>
        <item><title>F1 Brazilian Grand Prix Race Results 2026</title><link>https://www.formula1.com/results</link></item>
        </channel></rss>"""
        class Response:
            content=xml
            def raise_for_status(self):pass
        with patch("web_lookup.httpx.get",return_value=Response()):
            hits=_bing_rss("who won latest Formula 1 Brazilian Grand Prix race 2026")
        self.assertEqual(len(hits),1)
        self.assertIn("Brazilian Grand Prix",hits[0]["title"])

    def test_web_results_are_link_titles_not_model_inventions(self):
        from unittest.mock import patch
        from web_lookup import _search_sync
        class FakeDDGS:
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def text(self,*args,**kwargs):
                return [{"href":"https://www.formula1.com/en/results",
                         "title":"Official 2026 F1 results",
                         "body":"Results page; no race winner stated in snippet."}]
        with patch("ddgs.DDGS",FakeDDGS):
            results,domain=_search_sync("latest f1 results")
        self.assertEqual(domain,"formula1.com")
        self.assertIn("Official 2026 F1 results",results)
        self.assertNotIn("Max Verstappen won",results)

    def test_live_weather_attribution_and_country_scope(self):
        context,domain=asyncio.run(lookup(
            "what is the weather like in tajikistan right now",WeatherClient()))
        self.assertEqual(domain,"open-meteo.com")
        self.assertIn("-4.6°C",context)
        self.assertIn("moderate snowfall",context)
        self.assertNotIn("partly cloudy",context)
        self.assertIn("country-center reading; local weather varies",context)
        self.assertIn("2026-11-09 21:00",context)


if __name__ == "__main__":
    unittest.main()
