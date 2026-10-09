"""Rendered display preserves source/memory and rejects active model HTML."""

from local_agent.mobile.markdown import display_thread, render_markdown


def test_markdown_formats_circuit_review_and_preserves_code():
    text = "## Review\n\n**Unverified** and `R1`\n\n- Check voltage\n- Check ground\n\n| Part | Value |\n| --- | --- |\n| R1 | 10k |\n\n```spice\nR1 in out 10k\n```\n\n[Source](https://example.com/manual)"
    html = render_markdown(text)
    for value in (
        "<h2>Review</h2>",
        "<strong>Unverified</strong>",
        "<ul>",
        "<table>",
        "<pre><code>",
        "R1 in out 10k",
        'href="https://example.com/manual"',
    ):
        assert value in html


def test_model_html_links_and_images_cannot_execute_or_fetch():
    html = render_markdown(
        '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1))\n\n![tracking](https://example.com/pixel)\n\n<iframe src="https://example.com"></iframe>'
    )
    assert "&lt;script&gt;" in html
    for unsafe in ("<script", "<img", "<iframe", 'href="javascript:', 'onerror="'):
        assert unsafe not in html


def test_display_view_does_not_change_saved_messages_or_user_text():
    thread = {
        "thread_id": "x",
        "messages": [
            {"role": "user", "content": "<b>User</b>"},
            {"role": "assistant", "content": "**Answer**"},
        ],
    }
    view = display_thread(thread)
    assert view["messages"][1]["rendered_html"] == "<p><strong>Answer</strong></p>\n"
    assert "rendered_html" not in thread["messages"][1]
    assert "rendered_html" not in view["messages"][0]
    assert view["messages"][1]["content"] == thread["messages"][1]["content"]
