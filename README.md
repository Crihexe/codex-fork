# codex-fork

Fork a local Codex chat at the end of a specific turn and get the command to resume it.

```sh
codex-fork CHAT_ID 17
# codex resume NEW_CHAT_ID
```

Turn numbers include the complete history, including turns inherited from earlier forks. The selected turn is included in full; later turns are excluded.

## Requirements

- Python 3.10 or newer; no third-party Python packages.
- Codex CLI installed, authenticated, and available as `codex` on your `PATH`.
- The source chat must be available in your local Codex history.

Tested on Linux with Codex CLI **0.160.0**, in Bash and Zsh. The tool uses experimental App Server APIs, so compatibility with other CLI versions is not guaranteed.

## Install

```sh
git clone https://github.com/Crihexe/codex-fork.git
cd codex-fork
mkdir -p "$HOME/.local/bin"
install -m 755 codex_fork.py "$HOME/.local/bin/codex-fork"
```

If `~/.local/bin` is not already on your `PATH`, add this line to `~/.bashrc` or `~/.zshrc`, then open a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

You can also run the script directly without installing:

```sh
python3 codex_fork.py CHAT_ID 17
```

## Usage

Replace `CHAT_ID` with the source chat's ID. Turn numbering starts at **1**, oldest first.

### Preview a turn

```sh
codex-fork CHAT_ID 17 --dry-run
```

Shows the selected turn's ID and the beginning of its first user message, without creating a fork.

### List turns

```sh
codex-fork CHAT_ID --list-turns
```

Each row shows the turn number, ID, status, and a short message preview. Inherited turns, automatic continuations, interrupted turns, and failed turns all count. Some turns have no user message. Use this list to identify the boundary you want.

For example, if a chat inherits four turns, its first new turn is number 5.

### Create a fork

```sh
codex-fork CHAT_ID 17
```

The tool checks the new fork's turn count and final turn ID, then prints:

```sh
codex resume NEW_CHAT_ID
```

The selected turn's details go to stderr. After successful creation and verification, stdout contains only the resume command. The tool does not run that command automatically.

You can also require the selected turn's first user message to begin with an expected, case-sensitive prefix:

```sh
codex-fork CHAT_ID 17 --expect-prefix "Explain what you found"
```

Whitespace is normalized before comparison. A mismatch prevents fork creation. A turn still in progress is also rejected.

## How it works

The script starts a local `codex app-server` process and uses its JSON-RPC protocol:

1. List turns in ascending order, following pagination and inherited history.
2. Select the requested turn by number.
3. Call `thread/fork` with `lastTurnId` and `excludeTurns: true`, avoiding a full conversation dump.
4. Read the new fork's turn metadata and verify its boundary.
5. Print the resume command and close the App Server process.

It does not start an agent turn, edit existing chat logs, or create backups. This branches chat history; use Git separately to restore project files to an earlier state.

If verification fails after creation, the error includes the new chat ID. If a fork request times out or the connection closes, creation may still have succeeded; the tool does not automatically retry.

See the [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server#threads) for the protocol and thread operations.

## Update

From your checkout:

```sh
git pull --ff-only
install -m 755 codex_fork.py "$HOME/.local/bin/codex-fork"
```

## Tests

```sh
python3 -B -m unittest -v
```

Tests use simulated RPC responses; they do not require Codex or create real chats. They cover pagination, inherited turn numbering, previews, prefix checks, active turns, fork boundaries, and command output.

## License

[MIT](LICENSE).
