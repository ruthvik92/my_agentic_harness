# Optional configurations

The browser selector reads `config/`, which contains only browser, analog, and
coding profiles. These examples are deliberately outside that directory.

- `openai-local.yaml` exercises Ollama's local OpenAI-compatible endpoint.
  It is also used by the transport compatibility tests.
- `openai-reviewer.yaml` enables the optional external OpenAI reviewer only
  when explicitly passed at startup:

  ```bash
  ./browser --verifier-agent examples/configs/openai-reviewer.yaml
  ```

The reviewer reads its configured API-key environment variable on the host.
Its dropdown remains disabled when no reviewer profile is supplied, even if an
API key is present. Reviewer requests can incur provider charges.

```bash
uv run --locked local-agent run --agent examples/configs/openai-local.yaml \
  --repo /path/to/project --task-file /path/to/task.md
```

For a custom browser-selectable profile, copy an example into `config/` and
validate it in the editor. See [the configuration reference](../../docs/configs.md).
