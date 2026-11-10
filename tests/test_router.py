import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from router import Ledger,Router,authorize,classify,estimate_usd,load_env

class DummyResponse:
    def __init__(self,body,status=200):
        self.body=body;self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:raise ValueError("bad request")
    def json(self):return self.body

class DummyHTTP:
    def __init__(self,fail_first=False):
        self.calls=[];self.requests=[];self.fail_first=fail_first
    async def post(self,url,headers,json,timeout):
        self.calls.append((url,json["model"],json["max_tokens"]))
        self.requests.append(json)
        if self.fail_first and len(self.calls)==1:return DummyResponse({},500)
        return DummyResponse({"choices":[{"message":{"role":"assistant","content":"hey chat, quick answer."},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":15,"completion_tokens":10}})

class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Ledger(str(Path(self.temp.name)/"ledger.sqlite"))
        self.env={"NVIDIA_BASE_URL":"https://example.invalid/v1",
                  "NVIDIA_API_KEY":"fake-key",
                  "NEBIUS_BASE_URL":"https://example.invalid/v1",
                  "NEBIUS_API_KEY":"fake-key",
                  "MERGE_BASE_URL":"https://example.invalid/v1",
                  "MERGE_API_KEY":"fake-key"}
    def tearDown(self):self.temp.cleanup()

    def test_modes_and_admin_identity(self):
        self.assertEqual(classify("who won?", "mario"),"mario")
        self.assertEqual(classify("compare sources about this"),"research")
        self.assertEqual(classify("hey"),"chat")
        for kw in ({"tier":"admin","origin":"twitch","actor_id":"123","owner_id":"123"},
                   {"tier":"admin","origin":"mattermost","actor_id":"untrusted","owner_id":"123"}):
            with self.assertRaises(PermissionError):authorize(**kw)
        authorize("admin",actor_id="123",owner_id="123",origin="mattermost")

    def test_evidence_required(self):
        with self.assertRaises(ValueError):
            asyncio.run(Router(self.env,self.db,DummyHTTP()).complete("is this true?",tier="research"))

    def test_private_file_permissions(self):
        f=Path(self.temp.name)/"secrets.env"
        f.write_text("NEBIUS_API_KEY=SECRET")
        f.chmod(0o644)
        with self.assertRaises(PermissionError):load_env(str(f))
        f.chmod(0o600)
        self.assertEqual(load_env(str(f))["NEBIUS_API_KEY"],"SECRET")

    def test_ledger_caps_and_refunds(self):
        self.assertTrue(self.db.reserve("a","NEBIUS",0.5))
        self.assertTrue(self.db.reserve("b","NEBIUS",0.5))
        self.db.refund("a")
        self.assertAlmostEqual(self.db.reserved_total("NEBIUS"),0.5)
        self.assertFalse(self.db.reserve("x","NEBIUS",20.0))
        self.db.finish("b",0.2)
        self.assertAlmostEqual(self.db.reserved_total("NEBIUS"),0.2)

    def test_routing_and_cost_record(self):
        http=DummyHTTP()
        self.env["NVIDIA_VERIFIED"]="true"
        r=Router(self.env,self.db,http,available_models={"NVIDIA":{"nvidia/nemotron-3-super-120b-a12b"},"MERGE":set(),"NEBIUS":set()})
        answer=asyncio.run(r.complete("hey!",max_tokens=45))
        self.assertEqual(answer.provider,"NVIDIA")
        self.assertIn("quick answer",answer.text)
        self.assertEqual(http.calls[0][1],"nvidia/nemotron-3-super-120b-a12b")
        self.assertGreater(self.db.reserved_total("NVIDIA"),0)

    def test_failover_after_model_error(self):
        http=DummyHTTP(fail_first=True)
        r=Router(self.env,self.db,http)
        answer=asyncio.run(r.complete("hello"))
        self.assertEqual(answer.provider,"MERGE")
        self.assertEqual(len(http.calls),2)
        self.assertGreater(self.db.reserved_total("MERGE"),0)
        self.assertEqual(self.db.reserved_total("NEBIUS"),0)

    def test_twitch_owner_is_not_bot_or_streamer(self):
        http=DummyHTTP()
        r=Router(self.env,self.db,http)
        asyncio.run(r.complete("hello roborath",actor_login="joeyleq",
                               actor_role="owner",max_tokens=55))
        instr=http.requests[0]["messages"][0]["content"]
        self.assertIn("speaker is Twitch account @joeyleq",instr)
        self.assertIn("You are RoboRath",instr)
        self.assertIn("Never address the speaker as RoboRath, Rath, or Rather",instr)
        self.assertEqual(http.requests[0]["messages"][1]["content"],"hello roborath")

    def test_source_evidence_is_passed_for_conversation(self):
        http=DummyHTTP()
        r=Router(self.env,self.db,http)
        asyncio.run(r.complete("weather now",sources="Open-Meteo: 5 C.",
                               actor_login="joeyleq"))
        self.assertIn("Open-Meteo: 5 C",http.requests[0]["messages"][1]["content"])

    def test_https_only(self):
        self.env["NVIDIA_BASE_URL"]="http://localhost:9999/v1"
        r=Router(self.env,self.db,DummyHTTP())
        self.assertNotIn("NVIDIA",[x[0] for x in r.candidates("chat")])

    def test_research_uses_verified_evidence(self):
        http=DummyHTTP()
        r=Router(self.env,self.db,http,available_models={"NVIDIA":set(),"NEBIUS":{"Qwen/Qwen3.5-397B-A17B"}})
        result=asyncio.run(r.complete("what does the document say?",tier="research",sources="Primary source: data"))
        self.assertEqual(result.provider,"NEBIUS")
        self.assertEqual(result.model,"Qwen/Qwen3.5-397B-A17B")

    def test_tool_call_response_fails_closed_and_is_accounted(self):
        class ToolHTTP(DummyHTTP):
            async def post(self,url,headers,json,timeout):
                self.calls.append((url,json["model"],json["max_tokens"]))
                return DummyResponse({"choices":[{"message":{"role":"assistant",
                    "content":"<think>{\"name\":\"search_tools\",\"arguments\":{}}"},
                    "finish_reason":"stop"}],"usage":{"prompt_tokens":31,"completion_tokens":9}})
        http=ToolHTTP()
        r=Router(self.env,self.db,http,available_models={"NEBIUS":{"NousResearch/Hermes-4-405B"},
            "MERGE":set(),"NVIDIA":set()})
        with self.assertRaises(RuntimeError):
            asyncio.run(r.complete("who started the Six-Day War?"))
        self.assertAlmostEqual(self.db.reserved_total("NEBIUS"),0.000058)

    def test_non_assistant_and_tool_finish_are_rejected(self):
        cases=(({"role":"tool","content":"source text"},"stop"),
               ({"role":"assistant","content":"no public answer"},"tool_calls"),
               ({"role":"assistant","content":[{"text":"flatten me"}]},"stop"))
        for message,finish in cases:
            class OddHTTP(DummyHTTP):
                async def post(self,url,headers,json,timeout):
                    return DummyResponse({"choices":[{"message":message,"finish_reason":finish}],
                        "usage":{"prompt_tokens":2,"completion_tokens":3}})
            r=Router(self.env,self.db,OddHTTP(),available_models={"NEBIUS":{"NousResearch/Hermes-4-405B"},
                "MERGE":set(),"NVIDIA":set()})
            with self.assertRaises(RuntimeError):
                asyncio.run(r.complete("hello"))

    def test_provider_circuit_breaker_opens_after_three_bad_responses(self):
        class BadHTTP(DummyHTTP):
            async def post(self,url,headers,json,timeout):
                self.calls.append((url,json["model"],json["max_tokens"]))
                return DummyResponse({"choices":[],"usage":{}})
        http=BadHTTP()
        r=Router(self.env,self.db,http,available_models={"NEBIUS":{"NousResearch/Hermes-4-405B"},
            "MERGE":set(),"NVIDIA":set()})
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                asyncio.run(r.complete("hello"))
        self.assertEqual(len(http.calls),3)
        self.assertEqual(list(r.candidates("chat")),[])

if __name__=="__main__":unittest.main()
