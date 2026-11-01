"""Bounded review progress survives exchange compaction; reserve a report turn."""

from local_agent.runtime.context import ContextBuilder, estimate
from local_agent.storage.blobs import canonical, digest


def progress(store, observations):
    reads, commands = {}, {}
    for item in observations:
        args = store.blobs.json(item["arguments_ref"])
        if item["tool"] == "read_file" and item["status"] == "succeeded":
            key = (args.get("path"), args.get("line_offset", 0), args.get("byte_offset", 0))
            entry = {key: args[key] for key in ("path", "line_offset", "byte_offset") if key in args}
            try:
                output = store.blobs.json(item["output_ref"])
                entry.update({key: output[key] for key in ("next_line", "next_byte_offset", "content_hash")
                              if key in output})
            except (ValueError, TypeError):
                pass
            reads[key] = entry
        elif item["tool"] == "run_command":
            command = {key: args[key] for key in ("argv", "cwd") if key in args}
            command.setdefault("cwd", "project")
            key = canonical(command)
            if len(key) > 2048:
                command = {"arguments_preview": key[:512].decode(errors="replace")}
            entry = {**command, "status": item["status"], "exit_code": item["exit_code"],
                     "output_ref": item["output_ref"], "output_preview": item["output"][-400:]}
            # Retain a command's most recent result and expose repeated execution.
            prior = commands.pop(key, {})
            commands[key] = {**entry, "executions": prior.get("executions", 0) + 1}
    summary = {"read_pages": list(reads.values())[-32:],
               "commands": list(commands.values())[-12:]}
    while len(canonical(summary)) > 10000:
        if summary["read_pages"]:
            summary["read_pages"].pop(0)
        else:
            summary["commands"].pop(0)
    return summary


class ProgressTracker:
    def __init__(self):
        self.turn, self.fingerprint, self.stalled = None, None, 0

    def update(self, turn, summary):
        if turn == self.turn:
            return
        commands = [{key: item[key] for key in ("argv", "cwd", "arguments_preview", "status", "exit_code")
                     if key in item} for item in summary["commands"]]
        # Counts, output timing and command recency change even when no new work was done.
        fingerprint = canonical({
            "read_pages": sorted(canonical(item).decode() for item in summary["read_pages"]),
            "commands": sorted(canonical(item).decode() for item in commands),
        })
        self.stalled = self.stalled + 1 if fingerprint == self.fingerprint else 0
        self.turn, self.fingerprint = turn, fingerprint


class ReviewContext(ContextBuilder):
    def __init__(self, agent):
        super().__init__(agent.store.blobs, agent.config)
        self.agent = agent

    def build(self, fixed, groups):
        self.agent.report_turn = self.agent.report_only
        snapshot, ref = super().build(fixed, groups)
        if not self.agent.report_turn:
            return snapshot, ref
        # Keep the same transport/reasoning/history while offering no more tool calls.
        wire = self.blobs.json(snapshot.payload_ref)
        wire.pop("tools", None)
        wire.pop("tool_choice", None)
        payload_ref = self.blobs.put_json(wire)
        snapshot = snapshot.model_copy(update={
            "payload_ref": payload_ref, "payload_hash": digest(canonical(wire)),
            "tool_definitions": (), "token_estimate": estimate(wire),
        })
        return snapshot, self.blobs.put_json(snapshot)
