"""Controller browser acceptance check; start geckodriver on loopback port 8844 first."""

import base64
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

from local_agent.mobile.web import PhoneServer

captured = []
source = Path.home() / "snap/firefox/common"
source.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="local-agent-browser-", dir=source) as directory:
    directory = Path(directory)
    image_path = directory / "input.png"
    Image.new("RGB", (16, 16), "white").save(image_path)

    def runner(path):
        captured.append(json.loads(path.read_text()))
        return {
            "status": "completed_unverified",
            "answer": (
                "## Review\n\n**Unverified**\n\n| Part | Value |\n| --- | --- |\n| R1 | 10k |\n\n```spice\nR1 in out 10k\n```"
                if captured[-1]["question"].startswith("Independently review")
                else "<script>safe text</script>"
            ),
            "run_id": None,
        }

    server = PhoneServer(directory / "state", Path("config/phone.yaml"), port=0, runner=runner)
    server.models.catalog = lambda **_kwargs: {
        "models": [
            {
                "id": "ollama:qwen3.8:27b",
                "model": "qwen3.8:27b",
                "provider": "ollama",
                "capabilities": ["completion", "vision"],
                "vision": True,
                "selectable": True,
            },
            {
                "id": "ollama:glm-4.7-flash:q8_0",
                "model": "glm-4.7-flash:q8_0",
                "provider": "ollama",
                "capabilities": ["completion", "tools"],
                "vision": False,
                "selectable": True,
            },
        ],
        "default_id": "ollama:qwen3.8:27b",
        "error": None,
        "verifier": {
            "model": "gpt-6-astra",
            "default_id": "openai:gpt-6-astra",
            "enabled": True,
            "reason": None,
            "models": [
                {
                    "id": "openai:" + model,
                    "model": model,
                    "provider": "openai",
                    "capabilities": ["completion", "vision", "reasoning"],
                    "vision": True,
                    "selectable": True,
                }
                for model in ("gpt-6-astra", "gpt-6-luna", "gpt-4.1-2025-04-14")
            ],
        },
    }
    old_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "browser-fake-provider-only"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    driver = httpx.Client(base_url="http://127.0.0.1:8844", timeout=45, trust_env=False)
    session = None

    def call(method, path, data=None):
        result = driver.request(method, path, json=data).json()
        value = result.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise RuntimeError(str(value))
        return value

    try:
        session = call(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "firefox",
                        "moz:firefoxOptions": {"args": ["-headless"]},
                    }
                }
            },
        )["sessionId"]
        prefix = "/session/" + session

        def js(script, *args):
            return call("POST", prefix + "/execute/sync", {"script": script, "args": list(args)})

        def wait(script):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = js(script)
                if result:
                    return result
                time.sleep(0.1)
            raise AssertionError(
                "Browser wait failed: " + script + "\n" + str(js("return document.body.innerText"))
            )

        call("POST", prefix + "/window/rect", {"width": 420, "height": 850})
        helper = server.assets["/thread-controls.js"]
        server.assets["/thread-controls.js"] = b""
        call("POST", prefix + "/url", {"url": f"http://127.0.0.1:{server.server_port}"})
        wait(
            "return document.getElementById('error-banner').textContent.includes('Model controls could not load')"
        )
        assert js("return document.getElementById('login-btn').disabled")
        server.assets["/thread-controls.js"] = helper
        call("POST", prefix + "/refresh", {})
        wait("return document.getElementById('ask-btn').disabled")
        js(
            "document.getElementById('pairing-code').value=arguments[0];document.getElementById('login-btn').click()",
            server.pairing_code,
        )
        wait("return !document.getElementById('ask-btn').disabled")
        element = call("POST", prefix + "/element", {"using": "css selector", "value": "#image"})
        element_id = element["element-6066-11e4-a52e-4f735466cecf"]
        call("POST", prefix + "/element/" + element_id + "/value", {"text": str(image_path)})
        wait("return document.getElementById('status').textContent.includes('Screenshot attached')")

        def prepare(raw, name, mime):
            return call(
                "POST",
                prefix + "/execute/async",
                {
                    "script": """
                        const done=arguments[3];
                        const bytes=Uint8Array.from(atob(arguments[0]), c=>c.charCodeAt(0));
                        prepareImage(new File([bytes], arguments[1], {type:arguments[2]}))
                          .then(result=>done(result)).catch(error=>done({error:error.message}));
                    """,
                    "args": [base64.b64encode(raw).decode(), name, mime],
                },
            )

        for mime in ("", "application/octet-stream", "image/jpeg"):
            result = prepare(image_path.read_bytes(), "crop.unknown", mime)
            assert result["url"].startswith("data:image/png;") and not result["changed"]
        webp = io.BytesIO()
        Image.new("RGB", (32, 24), "white").save(webp, format="WEBP")
        result = prepare(webp.getvalue(), "crop.unknown", "")
        assert result["url"].startswith("data:image/png;") and result["changed"]
        oversized = io.BytesIO()
        Image.new("RGB", (5000, 4000), "white").save(oversized, format="PNG")
        result = prepare(oversized.getvalue(), "large.png", "image/png")
        assert result["changed"] and result["width"] * result["height"] <= 16_000_000
        js("""
            const transfer=new DataTransfer();
            transfer.items.add(new File(['invalid'], 'broken.png', {type:'image/png'}));
            document.getElementById('image').files=transfer.files;
            document.getElementById('image').dispatchEvent(new Event('change'));
        """)
        wait("return document.getElementById('error-banner').textContent.includes('cannot decode')")
        assert js(
            "return document.getElementById('status').textContent.includes('Previous screenshot is still attached')"
        )
        js(
            "window.originalFetch=window.fetch; window.failOnce=true; window.fetch=(...args)=>{if(window.failOnce && String(args[0]).startsWith('/api/jobs/')){window.failOnce=false;return Promise.reject(new Error('test network drop'));}return window.originalFetch(...args);}"
        )
        js(
            "document.getElementById('question').value='First question';document.getElementById('ask-btn').click()"
        )
        wait("return document.getElementById('status').textContent.includes('Polling paused')")
        js("document.getElementById('resume-btn').click()")
        wait("return document.getElementById('status').textContent.includes('Completed')")
        assert (
            len(captured) == 1 and base64.b64decode(captured[0]["image"]) == image_path.read_bytes()
        )
        assert "<script>safe text</script>" in js(
            'return document.getElementById("transcript").textContent'
        )
        assert js('return document.getElementById("transcript").querySelector("script")===null')
        js(
            "document.getElementById('question').value='Follow up';document.getElementById('ask-btn').click()"
        )
        wait(
            "return document.getElementById('transcript').textContent.includes('Follow up') && !document.getElementById('ask-btn').disabled"
        )
        assert len(captured) == 2 and captured[1]["history"] == [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "<script>safe text</script>"},
        ]
        assert captured[1]["image"] == captured[0]["image"]
        js(
            "window.failOnce=true;document.getElementById('question').value='Recovered request';document.getElementById('ask-btn').click()"
        )
        wait("return document.getElementById('status').textContent.includes('Polling paused')")
        call("POST", prefix + "/refresh", {})
        wait(
            "return document.getElementById('transcript').textContent.includes('Recovered request') && !document.getElementById('ask-btn').disabled"
        )
        assert len(captured) == 3, "Resume/reload submitted duplicate jobs"
        assert js(
            "return document.getElementById('transcript').textContent.includes('First question')"
        )
        assert js(
            "return !document.getElementById('preview-container').classList.contains('hidden')"
        )
        assert js(
            "return document.getElementById('model-select').options[0].textContent.includes('vision')"
        )
        js(
            "document.getElementById('inference-select').value='ollama:glm-4.7-flash:q8_0';document.getElementById('netlist-btn').click()"
        )
        wait(
            "return document.getElementById('breakdown').textContent.includes('Netlist inference: glm-4.7-flash:q8_0') && !document.getElementById('ask-btn').disabled"
        )
        assert len(captured) == 4 and "image" not in captured[-1]
        assert js(
            "return document.getElementById('reviewer-select').value === 'openai:gpt-6-astra'"
        )
        js(
            "const s=document.getElementById('reviewer-select');s.value='openai:gpt-6-luna';s.dispatchEvent(new Event('change'));document.getElementById('verify-btn').click()"
        )
        wait(
            "return document.getElementById('breakdown').textContent.includes('OpenAI paid review: gpt-6-luna') && !document.getElementById('ask-btn').disabled"
        )
        assert len(captured) == 5 and captured[-1]["image"] == captured[0]["image"]
        js("document.getElementById('thumb-up').click()")
        wait("return document.getElementById('thumb-up').getAttribute('aria-pressed') === 'true'")
        js("document.getElementById('trace-toggle').click()")
        wait("return document.getElementById('trace').textContent.includes('phone.feedback')")
        call("POST", prefix + "/refresh", {})
        wait("return document.getElementById('thumb-up').getAttribute('aria-pressed') === 'true'")
        assert js(
            "return document.getElementById('breakdown').textContent.includes('Netlist inference: glm')"
        )
        assert js(
            "return document.getElementById('history-note').textContent.includes('1 saved chats')"
        )
        assert js(
            "return document.getElementById('thread-usage').textContent.includes('Estimated net tokens saved')"
        )
        assert js(
            "return document.getElementById('all-usage').textContent.includes('All saved chats')"
        )
        js("document.getElementById('refresh-usage').click()")
        assert js("return document.getElementById('reviewer-select').value") == "openai:gpt-6-luna"
        js(
            "document.querySelector('#transcript details.assistant[open] .answer-feedback button[data-vote=down]').click()"
        )
        wait(
            "return document.querySelector('#transcript details.assistant[open] .answer-feedback button[data-vote=down]').getAttribute('aria-pressed') === 'true'"
        )
        assert (
            js("return document.getElementById('thumb-up').getAttribute('aria-pressed')") == "true"
        )
        assert (
            js("return document.querySelectorAll('#transcript details.assistant[open]').length")
            == 1
        )
        js(
            "document.getElementById('trace-toggle').click();document.getElementById('trace-toggle').click()"
        )
        wait(
            "return document.getElementById('trace').textContent.includes('phone.answer_feedback')"
        )
        call("POST", prefix + "/refresh", {})
        wait(
            "return document.querySelector('#transcript details.assistant[open] .answer-feedback button[data-vote=down]')?.getAttribute('aria-pressed') === 'true'"
        )
        # Exercise actual Markdown presentation, folded history and reopening.
        assert js(
            "return !!document.querySelector('#transcript details.assistant[open] table') && !!document.querySelector('#transcript details.assistant[open] pre code')"
        )
        js("document.querySelector('#transcript details.assistant summary').click()")
        assert js("return document.querySelector('#transcript details.assistant').open")
        js(
            "document.querySelector('#transcript details.assistant .answer-feedback button[data-vote=up]').click()"
        )
        wait(
            "return document.querySelector('#transcript details.assistant .answer-feedback button[data-vote=up]').getAttribute('aria-pressed') === 'true'"
        )
        assert (
            js("return document.querySelectorAll('#transcript details.assistant[open]').length")
            == 2
        )
        js(
            "document.querySelector('#transcript details.assistant .answer-feedback button[data-vote=up]').click()"
        )
        wait(
            "return document.querySelector('#transcript details.assistant .answer-feedback button[data-vote=up]').getAttribute('aria-pressed') === 'false'"
        )
        saved_thread = js("return localStorage.getItem('threadId')")
        js("document.getElementById('new-conversation-btn').click()")
        assert js('return document.getElementById("transcript").textContent') == ""
        assert js("return localStorage.getItem('reviewer-select')") == "openai:gpt-6-luna"
        js(
            "document.getElementById('thread-select').value=arguments[0];document.getElementById('thread-select').dispatchEvent(new Event('change'))",
            saved_thread,
        )
        wait(
            "return document.getElementById('transcript').textContent.includes('First question') && !document.getElementById('ask-btn').disabled"
        )
        js(
            "document.getElementById('question').value='Continue saved chat';document.getElementById('ask-btn').click()"
        )
        wait(
            "return document.getElementById('transcript').textContent.includes('Continue saved chat') && !document.getElementById('ask-btn').disabled"
        )
        assert len(captured) == 6 and len(captured[-1]["history"]) == 6
        assert captured[-1]["image"] == captured[0]["image"]
        assert js("return document.documentElement.scrollWidth <= window.innerWidth")
        print(
            "Firefox checks passed: image formats/resizing, failed replacement retention, pairing, persisted chat/image, model capabilities, netlist stage, fake paid review, feedback trace, resume/reload recovery, reset."
        )
    finally:
        try:
            if session:
                call("DELETE", "/session/" + session)
        finally:
            driver.close()
            server.shutdown()
            server.server_close()
            thread.join()
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key
