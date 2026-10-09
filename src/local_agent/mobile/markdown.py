"""Render model Markdown for the phone UI without executable HTML or images."""

import bleach
from markdown_it import MarkdownIt

TAGS = frozenset(
    {
        "p",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "strong",
        "em",
        "s",
        "blockquote",
        "ul",
        "ol",
        "li",
        "pre",
        "code",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)


def render_markdown(text):
    # Per-request instances avoid sharing mutable parser/sanitizer state between threads.
    parser = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    return bleach.clean(
        parser.render(text),
        tags=TAGS,
        attributes={"a": ["href", "title"], "ol": ["start"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def display_thread(thread):
    """Derived view only: retain original text in durable history and model memory."""
    return {
        **thread,
        "messages": [
            {**message, "rendered_html": render_markdown(message["content"])}
            if message["role"] == "assistant"
            else dict(message)
            for message in thread["messages"]
        ],
    }
