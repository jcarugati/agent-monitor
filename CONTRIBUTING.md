# Contributing

Contributions that improve provider compatibility, privacy, accessibility, tests, or documentation are welcome.

## Development rules

1. Preserve monitoring-only behavior. Never add process signals, controls, mutation routes, or writes to provider state.
2. Keep all SQLite connections in URI read-only mode (`mode=ro`). Do not use database status rows as substitutes for the documented liveness sources of truth.
3. Keep the backend on the Python standard library unless a dependency is clearly justified.
4. Use synthetic temporary fixtures. Never commit copied databases, rollout files, prompts, command output, credentials, addresses, usernames, hostnames, or personal project names.
5. Keep controls accessible, preserve reduced-motion and keyboard-focus behavior, and test the UI at 360–430px widths.
6. Use generic examples such as `$HOME` or `/home/alice` in documentation.

## Verify changes

Run every gate before submitting a change:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile server.py agent_monitor/*.py tests/*.py
node --check frontend/app.js
bash -n install.sh
git diff --check
```

Also inspect the staged diff for personal data and credentials. Reports and test output should identify affected filenames without reproducing sensitive values.

## Change scope

Keep commits focused and use a conventional commit message such as `fix: preserve mobile session labels`. Explain user-visible behavior and privacy implications in the change description.
