#!/usr/bin/env python3
"""Fork a Codex chat at the end of turn N in its complete history.

Requires Python 3.10+ and Codex CLI with thread/turns/list and excludeTurns.
Inherited, automatic, interrupted, and failed turns all count.
"""

import argparse
from contextlib import contextmanager
import json
import queue
import shlex
import subprocess
import sys
import threading
import time


@contextmanager
def app_server():
    process = subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    replies = queue.Queue()
    sequence = 0

    def read_replies():
        try:
            for line in process.stdout:
                message = json.loads(line)
                if "id" in message and ("result" in message or "error" in message):
                    replies.put(message)
        except (ValueError, OSError):
            replies.put(RuntimeError("Invalid response from the App Server."))
        finally:
            replies.put(None)

    reader = threading.Thread(target=read_replies, daemon=True)
    reader.start()

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def rpc(method, params):
        nonlocal sequence
        sequence += 1
        request_id = sequence
        uncertain = (
            " The fork may already exist; check your chats before retrying."
            if method == "thread/fork" else ""
        )
        try:
            send({"id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + 120
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                reply = replies.get(timeout=remaining)
                if reply is None:
                    raise RuntimeError("App Server exited during " + method + "." + uncertain)
                if isinstance(reply, Exception):
                    raise RuntimeError(str(reply) + uncertain)
                if reply.get("id") != request_id:
                    continue
                if "error" in reply:
                    error = reply["error"]
                    raise RuntimeError(f"{method}: {error.get('message', error)}")
                return reply["result"]
        except queue.Empty:
            raise RuntimeError("No response within 120 seconds for " + method + "." + uncertain) from None
        except BrokenPipeError:
            raise RuntimeError("App Server connection closed." + uncertain) from None

    try:
        rpc("initialize", {
            "clientInfo": {"name": "codex_fork_script", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True},
        })
        send({"method": "initialized", "params": {}})
        yield rpc
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=1)
        process.stdout.close()


def iter_turns(rpc, chat_id, items_view="summary"):
    cursor = None
    seen_cursors = set()
    while True:
        params = {"threadId": chat_id, "limit": 50,
                  "sortDirection": "asc", "itemsView": items_view}
        if cursor is not None:
            params["cursor"] = cursor
        page = rpc("thread/turns/list", params)
        yield from page["data"]
        cursor = page.get("nextCursor")
        if cursor is None:
            return
        if cursor in seen_cursors:
            raise RuntimeError("App Server repeated a pagination cursor.")
        seen_cursors.add(cursor)


def normalize(text):
    return " ".join("".join(c for c in text if c.isprintable() or c.isspace()).split())


def first_message(turn):
    for item in turn.get("items", []):
        if item.get("type") in ("userMessage", "UserMessage"):
            return normalize(" ".join(part.get("text", "") for part in item.get("content", [])
                                      if isinstance(part, dict)))
    return ""


def select_turn(rpc, chat_id, number, expect_prefix=None):
    count = 0
    for count, turn in enumerate(iter_turns(rpc, chat_id), 1):
        if count == number:
            if turn.get("status") == "inProgress":
                raise RuntimeError("The selected turn is still in progress.")
            if expect_prefix and not first_message(turn).startswith(normalize(expect_prefix)):
                raise RuntimeError("The turn's message does not start with the expected prefix.")
            return turn
    raise RuntimeError(f"Turn {number} does not exist: the chat contains {count} turns.")


def create_fork(rpc, chat_id, turn, number):
    result = rpc("thread/fork", {
        "threadId": chat_id, "lastTurnId": turn["id"], "excludeTurns": True,
    })
    fork_id = result.get("thread", {}).get("id")
    if not fork_id or fork_id == chat_id:
        raise RuntimeError("The response does not contain a valid new chat ID.")
    # Verify the new fork's boundary using turn metadata only.
    count, last_id = 0, None
    try:
        for count, saved_turn in enumerate(iter_turns(rpc, fork_id, "notLoaded"), 1):
            last_id = saved_turn["id"]
            if count > number:
                break
        if count != number or last_id != turn["id"]:
            raise RuntimeError("The fork's boundary does not match the requested turn.")
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        raise RuntimeError(f"Fork created with ID {fork_id}, but verification failed: {error}") from None
    return fork_id


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("The turn number must be at least 1.")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chat_id", help="Source chat ID")
    parser.add_argument("turn", type=positive_int, nargs="?", help="Last included turn, counting from 1")
    parser.add_argument("--dry-run", action="store_true", help="Preview the selected turn without creating a fork")
    parser.add_argument("--list-turns", action="store_true", help="List turns from the complete history")
    parser.add_argument("--expect-prefix", help="Require the turn's first user message to start with this text")
    args = parser.parse_args(argv)
    if args.list_turns and (args.turn is not None or args.dry_run or args.expect_prefix):
        parser.error("Use --list-turns with the chat ID only.")
    if not args.list_turns and args.turn is None:
        parser.error("Provide a turn number or use --list-turns.")
    try:
        with app_server() as rpc:
            if args.list_turns:
                for number, turn in enumerate(iter_turns(rpc, args.chat_id), 1):
                    print(f"{number:>4}  {turn['id']}  [{turn.get('status', '?')}]  {first_message(turn)[:160]}")
                return 0
            turn = select_turn(rpc, args.chat_id, args.turn, args.expect_prefix)
            print(f"Turn {args.turn}: {turn['id']}\nMessage: {first_message(turn)[:200] or '(no user message)'}",
                  file=sys.stderr)
            if args.dry_run:
                print("Preview complete: no fork created.")
                return 0
            fork_id = create_fork(rpc, args.chat_id, turn, args.turn)
            print("codex resume " + shlex.quote(fork_id))
            return 0
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If a fork request was sent, check your chats before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
