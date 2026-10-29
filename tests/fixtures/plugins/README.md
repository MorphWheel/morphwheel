# Test plugins

Each folder is a plugin as a user would install one: a `plugin.toml` and a module next to it,
written against `morphwheel.plugins.api` only. They exist to misbehave on purpose, so the engine's
guards can be tested with real worker processes:

| Plugin | What it does |
|---|---|
| `echo` | Copies the input to the output. The well-behaved control. |
| `crash` | Kills its own process mid-conversion (`WORKER_CRASHED`, respawn). |
| `sleep` | Sleeps longer than the task timeout (`TIMEOUT`, terminate, respawn). |
| `tamper` | Appends a byte to the **source** (`SOURCE_CHANGED`: the critical alert, output discarded). |
| `broken` | Its module raises at import time; the GUI must still list its manifest (R5). |
