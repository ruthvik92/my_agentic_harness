"""Browser-facing agent built on the mobile screenshot capture pipeline.

This module adapts the existing ``ScreenshotAgent`` capture and provider image
formatting to any valid non-circuit ``AgentConfig`` while retaining the actual
selected instructions and tool allowlist. It does not enforce the phone-v1 /
no-tools restrictions that ``ScreenshotAgent`` applies, and it exposes the
captured image as a workspace-relative scratch path for browser tooling.
"""

from local_agent.mobile import ScreenshotAgent, image_mime, validate_request
from local_agent.runtime.agent import Agent


class BrowserAgent(ScreenshotAgent):
    """ScreenshotAgent that works with any valid non-circuit AgentConfig.

    - Accepts the same validated screenshot request as ScreenshotAgent.
    - Skips the phone-v1 / no-tools restrictions so real tools may be used.
    - Copies the captured image into the isolated workspace scratch directory.
    - Reports a truthful browser diagnostic (actual tools, image path, info).
    """

    def __init__(self, *args, request=None, **kwargs):
        if request is not None:
            self.input_request = validate_request(request)
        else:
            self.input_request = None
        # Bypass ScreenshotAgent.__init__ so its phone-v1 / no-tools checks do
        # not run; initialize the base Agent directly instead.
        Agent.__init__(self, *args, **kwargs)

    async def prepare(self):
        await ScreenshotAgent.prepare(self)
        manifest = self.prepared()
        image_ref = manifest.get("image_ref")
        if image_ref is not None:
            raw_bytes = self.store.blobs.read(image_ref)
            mime = image_mime(raw_bytes)
            filename = "browser-upload.png" if mime == "image/png" else "browser-upload.jpg"
            scratch_dir = self.path / "scratch"
            scratch_dir.mkdir(parents=True, exist_ok=True)
            (scratch_dir / filename).write_bytes(raw_bytes)
            manifest = dict(manifest)
            manifest["image_path"] = "scratch/" + filename
        self.event(
            "browser.prepared",
            "runtime",
            {"input_ref": self.store.blobs.put_json(manifest)},
        )

    def prepared(self):
        for e in reversed(self.store.events(self.run_id)):
            if e.event_type == "browser.prepared":
                return self.store.blobs.json(e.data["input_ref"])
        return super().prepared()

    def fixed_messages(self, task):
        messages = ScreenshotAgent.fixed_messages(self, task)
        manifest = self.prepared()
        tools = list(self.config.tools)
        if tools:
            tools_text = "Available tools (per config): " + ", ".join(tools) + "."
        else:
            tools_text = "No tools are available for this run."
        image_path = manifest.get("image_path")
        if image_path:
            image_text = (
                "Captured image available at workspace-relative path '"
                + image_path
                + "' (relative to the isolated workspace). "
                + "Image info: "
                + str(manifest.get("image_info") or {})
            )
        else:
            image_text = "No image was submitted for this request."
        diagnostic = (
            "Harness upload diagnostics: browser mode. "
            + tools_text
            + " "
            + image_text
            + " All paths are relative to the isolated workspace, and the "
            "available tools follow the agent config."
        )
        messages[1] = {"role": "system", "content": diagnostic}
        if self.config.instructions_version.startswith("coder-"):
            messages.insert(2, self.directory_message())
        return messages
