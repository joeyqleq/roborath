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
