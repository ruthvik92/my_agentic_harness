"""Persistent phone chat threads module.

Implements a thread manager that stores chat history in JSON files under
root/phone/threads. Uses atomic writes via publish() and enforces
thread limits, message bounds, and validation.
"""

import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from local_agent.circuits.agent import read_evidence
from local_agent.mobile.jobs import publish
from local_agent.storage.blobs import private_directory

THREAD_ID_RE = re.compile(r"[0-9a-f]{32}")
THREAD_LIMIT = 1000
MESSAGE_LIMIT = 200
EXCHANGE_LIMIT = 3
CHAR_LIMIT = 16000
MAX_BYTES = 16 * 1024 * 1024


class Threads:
    """Manages persistent phone chat threads.

    Args:
        root: Root directory for thread storage (threads stored under root/phone/threads).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._threads_dir = self.root / "phone" / "threads"
        private_directory(self._threads_dir)

    def _validate_thread_id(self, thread_id: str) -> None:
        """Validate thread ID format.

        Args:
            thread_id: Thread identifier to validate.

        Raises:
            ValueError: If thread_id does not match the expected 32-hex format.
        """
        if not isinstance(thread_id, str) or not THREAD_ID_RE.fullmatch(thread_id):
            raise ValueError(f"Invalid thread ID: {thread_id}")

    def _read_thread_json(self, thread_id: str) -> Dict[str, Any]:
        """Read thread JSON file with size bounds.

        Args:
            thread_id: Thread identifier.

        Returns:
            Parsed thread metadata.

        Raises:
            ValueError: If file is missing or exceeds size limit.
        """
        try:
            content = read_evidence(self._threads_dir, thread_id + "/thread.json", MAX_BYTES)
        except FileNotFoundError:
            raise ValueError(f"Thread not found: {thread_id}") from None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in thread {thread_id}: {exc}") from exc

    def _write_thread_json(self, thread_id: str, data: Dict[str, Any]) -> None:
        """Atomically write thread JSON file.

        Args:
            thread_id: Thread identifier.
            data: Thread metadata to persist.
        """
        path = self._threads_dir / thread_id / "thread.json"
        publish(path, data)

    def create(self, title: str = "New chat") -> str:
        """Create a new chat thread.

        Args:
            title: Chat title (default: "New chat").

        Returns:
            Generated 32-hex thread ID.

        Raises:
            RuntimeError: If thread limit is reached.
        """
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("Title must contain 1–160 characters")
        with self._lock:
            if sum(1 for _ in self._threads_dir.iterdir()) >= THREAD_LIMIT:
                raise RuntimeError(f"Thread limit reached ({THREAD_LIMIT})")

            thread_id = secrets.token_hex(16)
            thread_dir = self._threads_dir / thread_id
            private_directory(thread_dir)

            now = time.time()
            thread = {
                "thread_id": thread_id,
                "owner": "local-owner",
                "created": now,
                "updated": now,
                "title": title,
                "messages": [],
                "image": None,
                "feedback": None,
            }

            self._write_thread_json(thread_id, thread)
            return thread_id

    def get(self, thread_id: str) -> Dict[str, Any]:
        """Retrieve thread metadata.

        Args:
            thread_id: Thread identifier.

        Returns:
            Thread metadata dictionary.

        Raises:
            ValueError: If thread_id is invalid or thread not found.
        """
        self._validate_thread_id(thread_id)
        return self._read_thread_json(thread_id)

    def recent(self) -> List[Dict[str, Any]]:
        """Return summaries of recent threads sorted by updated timestamp.

        Returns:
            List of thread summaries (title, updated, thread_id) without image data.
        """
        with self._lock:
            summaries = []
            for path in self._threads_dir.iterdir():
                if not THREAD_ID_RE.fullmatch(path.name) or not path.is_dir():
                    continue
                try:
                    thread = self._read_thread_json(path.name)
                except (ValueError, OSError):
                    continue
                summaries.append(
                    {
                        "thread_id": path.name,
                        "title": thread.get("title", ""),
                        "updated": thread.get("updated", 0),
                    }
                )
            return sorted(summaries, key=lambda s: s["updated"], reverse=True)

    def update_image(self, thread_id: str, image: Optional[str], mime: Optional[str]) -> None:
        """Persist an image for a thread.

        Args:
            thread_id: Thread identifier.
            image: Base64-encoded image data (or None).
            mime: MIME type of the image (or None).

        Raises:
            ValueError: If thread_id is invalid or thread not found.
        """
        self._validate_thread_id(thread_id)
        with self._lock:
            thread = self._read_thread_json(thread_id)
            thread["image"] = image
            thread["mime"] = mime
            thread["updated"] = time.time()
            self._write_thread_json(thread_id, thread)

    def add_exchange(
        self,
        thread_id: str,
        question: str,
        answer: str,
        job_id: str,
        run_id: str,
        model: str,
        kind: str = "answer",
    ) -> None:
        """Append a user/assistant exchange to a thread.

        Args:
            thread_id: Thread identifier.
            question: User question content.
            answer: Assistant answer content.
            job_id: Job identifier (idempotency key).
            run_id: Run identifier.
            model: Model name used for the answer.
            kind: Exchange kind (default: "answer").

        Raises:
            ValueError: If thread_id is invalid or thread not found.
        """
        self._validate_thread_id(thread_id)
        with self._lock:
            thread = self._read_thread_json(thread_id)
            if any(m.get("job_id") == job_id for m in thread["messages"]):
                return
            if len(thread["messages"]) >= MESSAGE_LIMIT:
                raise ValueError("Thread is full (100 exchanges); start a new chat")
            now = time.time()

            # Build exchange entries
            user_entry = {
                "role": "user",
                "content": question,
                "created": now,
            }
            assistant_entry = {
                "role": "assistant",
                "content": answer,
                "model": model,
                "job_id": job_id,
                "run_id": run_id,
                "kind": kind,
                "created": now,
            }

            # Append and enforce message limit
            thread["messages"].append(user_entry)
            thread["messages"].append(assistant_entry)
            if len(thread["messages"]) > MESSAGE_LIMIT:
                thread["messages"] = thread["messages"][-MESSAGE_LIMIT:]

            thread["updated"] = now
            self._write_thread_json(thread_id, thread)

    def history(self, thread_id: str) -> List[Dict[str, str]]:
        """Return recent complete exchanges from a thread.

        Args:
            thread_id: Thread identifier.

        Returns:
            List of message dictionaries with only role and content fields.

        Raises:
            ValueError: If thread_id is invalid or thread not found.
        """
        self._validate_thread_id(thread_id)
        with self._lock:
            thread = self._read_thread_json(thread_id)
            messages = thread.get("messages", [])
            result = []
            for index in range(len(messages) - 2, max(-1, len(messages) - 8), -2):
                pair = messages[index : index + 2]
                if len(pair) != 2 or [m["role"] for m in pair] != ["user", "assistant"]:
                    continue
                clean = [{"role": m["role"], "content": m["content"]} for m in pair]
                if not result:
                    for m in clean:
                        m["content"] = m["content"][:8000]
                if sum(len(m["content"]) for m in clean + result) > CHAR_LIMIT:
                    break
                result = clean + result
            return result

    def update(self, thread_id, **fields):
        with self._lock:
            thread = self.get(thread_id)
            thread.update(fields, updated=time.time())
            self._write_thread_json(thread_id, thread)
            return thread

    def feedback(self, thread_id: str, vote: Optional[str]) -> None:
        """Persist feedback for a thread.

        Args:
            thread_id: Thread identifier.
            vote: Feedback vote ("up", "down", or None).

        Raises:
            ValueError: If thread_id is invalid, thread not found, or vote is invalid.
        """
        self._validate_thread_id(thread_id)
        if vote not in (None, "up", "down"):
            raise ValueError(f"Invalid feedback vote: {vote}")

        with self._lock:
            thread = self._read_thread_json(thread_id)
            thread["feedback"] = vote
            thread["updated"] = time.time()
            self._write_thread_json(thread_id, thread)
