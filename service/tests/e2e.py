"""End-to-end test against a running service, through the real MCP protocol.

    pip install "mcp==2.2.0"
    python service/tests/e2e.py http://127.0.0.1:8420/mcp "$WRITER_TOKEN" /path/to/notebook [AGENT_NAME [READER_TOKEN]]

AGENT_NAME is the name the writer token was issued to ("owner" for CADERNO_TOKEN);
with READER_TOKEN (from `agents add <name> --read-only`) the read-only scope is tested too.

It writes, corrects and retires real notes, so point it at a throwaway
notebook, never your own. Needs a real embedding model: the `fake` provider
matches words, not meaning, and the duplicate check will not fire.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL, TOKEN, NOTEBOOK = sys.argv[1], sys.argv[2], Path(sys.argv[3])
AGENT = sys.argv[4] if len(sys.argv) > 4 else "owner"
READER = sys.argv[5] if len(sys.argv) > 5 else None
RUN = str(int(time.time()))  # unique names, so reruns never collide with earlier history
passed = 0


def ok(cond: bool, what: str) -> None:
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {what}")
    passed += 1
    print(f"  ok  {what}")


async def call(s: ClientSession, tool: str, **args):
    r = await s.call_tool(tool, args)
    if getattr(r, "is_error", False):
        return {"error": " ".join(getattr(c, "text", "") for c in r.content)}
    if r.structured_content is not None:
        return r.structured_content
    return json.loads(r.content[0].text)


async def main() -> None:
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer wrong"}) as bad:
        r = await bad.post(URL, json={})
        ok(r.status_code == 401, "wrong token is rejected with 401")

    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=120)
    async with streamable_http_client(URL, http_client=http) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            ok({"recall", "remember", "update", "forget", "history", "context", "status"} <= tools, "all seven tools listed")

            r = await call(
                s,
                "remember",
                description="rebuilding the newsfeed app container cancels a pipeline run in progress",
                body="Check for running pipelines before `docker compose up -d --build app`. Lost three runs once.",
                name=f"newsfeed-rebuild-cancels-pipeline-{RUN}",
            )
            ok(r.get("saved") is True, "remember saves a new note")
            key = r["key"]
            ok((NOTEBOOK / f"{key}.md").exists(), "the note is a real markdown file")

            r = await call(
                s,
                "remember",
                description="redeploying newsfeed kills whatever pipeline is running",
                body="Don't rebuild the newsfeed container while the pipeline runs.",
            )
            ok(r.get("saved") is False and any(d["key"] == key for d in r.get("possible_duplicates", [])),
               "a near-duplicate is refused and points at the existing note")

            r = await call(s, "remember", description="db login", body="password: hunter2hunter2")
            ok("secret" in r.get("error", ""), "a note containing a password is refused")

            r = await call(s, "remember", description="x", body="y", name="../../etc/passwd")
            ok("error" in r, "a path outside the notebook is refused")

            r = await call(s, "recall", query="is it safe to redeploy the news aggregator right now?")
            ok(r["results"] and r["results"][0]["key"] == key, "recall finds the note by meaning, not keywords")

            r = await call(
                s, "update", key=key, reason="measured: it also drops the run's partial results",
                body="Check `pipeline_runs` for status='running' first. A rebuild cancels the run AND drops partial results.",
            )
            ok(r.get("updated") and r.get("revision") == 2, "update creates revision 2")

            h = (await call(s, "history", key=key))["revisions"]
            ok([x["status"] for x in h] == ["superseded", "active"], "history keeps rev 1 as superseded")
            ok(h[-1]["reason"] == "measured: it also drops the run's partial results", "history records why it changed")
            ok(h[-1]["by"] == AGENT and h[0]["by"] == AGENT, f"history records that agent '{AGENT}' made both revisions")

            r = await call(s, "recall", query="newsfeed redeploy pipeline")
            top = r["results"][0]
            ok(top["key"] == key and "partial results" in top["body"] and top["revision"] == 2,
               "recall returns only the corrected revision")

            # A note written by hand (or pulled in by sync) shows up without any tool call.
            (NOTEBOOK / "machines" / "gpu-box.md").write_text(
                "---\ndescription: the GPU box that serves embeddings and the local LLM\ntype: machine\n---\n\n"
                "Runs Ollama on port 11434. Reach it as gpu-box on the LAN.\n"
            )
            for _ in range(20):
                r = await call(s, "recall", query="which machine runs the language models?", limit=3)
                if any(x["key"] == "machines/gpu-box" for x in r["results"]):
                    break
                time.sleep(1)
            ok(any(x["key"] == "machines/gpu-box" for x in r["results"]), "a hand-written file is indexed on its own")
            gh = (await call(s, "history", key="machines/gpu-box"))["revisions"]
            ok(gh[-1]["by"] == "file edit", "a hand edit is attributed to 'file edit', not to an agent")

            r = await call(s, "forget", key=key, reason="the pipeline now survives rebuilds")
            ok(r.get("forgotten") and (NOTEBOOK / r["archived_to"]).exists(), "forget moves the note to _archive")
            ok(not (NOTEBOOK / f"{key}.md").exists(), "the live file is gone")
            r = await call(s, "recall", query="newsfeed redeploy pipeline")
            ok(all(x["key"] != key for x in r["results"]), "a forgotten note no longer comes back in recall")
            h = (await call(s, "history", key=key))["revisions"]
            ok(h[-1]["status"] == "retired" and h[-1]["reason"] == "the pipeline now survives rebuilds",
               "history shows it retired, and why")

            idx = (NOTEBOOK / "memory" / "INDEX.md").read_text()
            ok(f"newsfeed-rebuild-cancels-pipeline-{RUN}" not in idx, "memory/INDEX.md no longer lists it")
            midx = (NOTEBOOK / "machines" / "INDEX.md").read_text()
            ok("gpu-box" in midx, "machines/INDEX.md lists the hand-written note")

            r = await call(s, "context")
            ok("INDEX.md" in r["files"] and "identity/rules.md" in r["files"], "context returns the every-session files")

            r = await call(s, "status")
            ok(r["notes"]["active"] >= 1 and r["last_error"] is None, "status reports a healthy index")
            ok(r["you"] == {"agent": AGENT, "can_write": True}, "status says which agent is calling")

    if READER:
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {READER}"}, timeout=120)
        async with streamable_http_client(URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                r = await call(s, "recall", query="which machine runs the language models?")
                ok(bool(r.get("results")), "a read-only agent can recall")
                r = await call(s, "remember", description="should not be saved", body="read-only agents cannot write")
                ok("read-only" in r.get("error", ""), "a read-only agent cannot remember")
                r = await call(s, "update", key="machines/gpu-box", reason="x", body="overwritten")
                ok("read-only" in r.get("error", ""), "a read-only agent cannot update")
                r = await call(s, "forget", key="machines/gpu-box", reason="x")
                ok("read-only" in r.get("error", ""), "a read-only agent cannot forget")
                ok((NOTEBOOK / "machines" / "gpu-box.md").exists(), "the note it tried to forget is still there")
                r = await call(s, "status")
                ok(r["you"]["can_write"] is False, "status reports the reader as read-only")

    print(f"\n{passed} checks passed")


asyncio.run(main())
