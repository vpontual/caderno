"""The `caderno` command. Standard library only."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import __version__, notes

KIT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = KIT_ROOT / "template"
ADAPTERS = KIT_ROOT / "adapters"
BEGIN = "<!-- caderno:begin -->"
END = "<!-- caderno:end -->"

# Where each agent keeps its user-wide instruction file.
AGENTS = {
    "codex": Path("~/.codex/AGENTS.md"),
    "claude": Path("~/.claude/CLAUDE.md"),
    "gemini": Path("~/.gemini/GEMINI.md"),
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caderno"


def read_config() -> dict:
    cfg = {}
    f = config_dir() / "config"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def write_config(cfg: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    body = "# caderno settings for this machine (not synced)\n" + "".join(f"{k}={v}\n" for k, v in cfg.items())
    (d / "config").write_text(body)


def notebook_root(arg: str | None = None) -> Path:
    raw = arg or os.environ.get("CADERNO_ROOT") or read_config().get("root")
    if not raw:
        sys.exit("caderno: no notebook found. Run `caderno init` first, or set CADERNO_ROOT.")
    root = Path(raw).expanduser()
    if not (root / "INDEX.md").exists():
        sys.exit(f"caderno: {root} does not look like a notebook (no INDEX.md).")
    return root


def host_label() -> str:
    return read_config().get("host") or socket.gethostname().split(".")[0].lower()


def denylist() -> list[str]:
    return notes.load_denylist(config_dir() / "denylist")


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], check=check, text=True, capture_output=True)


def ask(prompt: str, default: str, assume_yes: bool) -> str:
    if assume_yes or not sys.stdin.isatty():
        return default
    got = input(f"{prompt} [{default}]: ").strip()
    return got or default


# --- init --------------------------------------------------------------------


def cmd_init(a) -> int:
    root = Path(a.path or ask("Where should the notebook live?", "~/caderno", a.yes)).expanduser().resolve()
    owner = a.name or ask("Whose notebook is this (a name agents will use)?", os.environ.get("USER", "me"), a.yes)
    host = a.host or ask("A short name for this machine", host_label(), a.yes)

    if a.clone and not (root / "INDEX.md").exists():
        if root.exists() and any(root.iterdir()):
            sys.exit(f"caderno: {root} is not empty; pick another path to clone into.")
        r = subprocess.run(["git", "clone", "-q", a.clone, str(root)], text=True, capture_output=True)
        if r.returncode != 0:
            sys.exit(f"caderno: clone failed:\n{r.stderr}")
        print(f"Cloned your notebook into {root}")
    elif (root / "INDEX.md").exists():
        print(f"{root} is already a notebook; keeping its contents.")
    else:
        root.mkdir(parents=True, exist_ok=True)
        for src in TEMPLATE.rglob("*"):
            dst = root / src.relative_to(TEMPLATE)
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif not dst.exists():
                dst.write_text(src.read_text(encoding="utf-8").replace("{{OWNER}}", owner), encoding="utf-8")
        notes.write_indexes(root)
        print(f"Created a notebook for {owner} at {root}")

    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    install_hook(root)

    cfg = read_config()
    cfg.update(root=str(root), host=host)
    write_config(cfg)
    dl = config_dir() / "denylist"
    if not dl.exists():
        dl.write_text(
            "# One literal string per line that must never be committed to the notebook:\n"
            "# your real passwords, tokens, private hostnames. This file stays on this machine.\n"
        )
    link_cli()

    print("\nNext:")
    print("  caderno connect        # point your agents (Codex, Claude Code, Gemini) at it")
    print(f"  edit {root}/identity/  # or ask your agent to interview you (SETUP-WITH-AN-AGENT.md)")
    print("  caderno remote <git-url>  then  caderno install-timer   # sync across machines")
    return 0


def install_hook(root: Path) -> None:
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        "# installed by caderno: block commits that contain secrets\n"
        f'exec "{sys.executable}" "{KIT_ROOT / "bin" / "caderno"}" scan --staged --root "{root}"\n'
    )
    hook.chmod(0o755)


def link_cli() -> None:
    bindir = Path.home() / ".local" / "bin"
    target = bindir / "caderno"
    src = KIT_ROOT / "bin" / "caderno"
    if target.exists() or target.is_symlink():
        return
    try:
        bindir.mkdir(parents=True, exist_ok=True)
        target.symlink_to(src)
        print(f"Linked {target} -> {src}")
    except OSError as e:
        print(f"(could not link {target}: {e}; run {src} directly)")


# --- connect -----------------------------------------------------------------


def pointer_block(root: Path, agent: str) -> str:
    tpl = (ADAPTERS / "pointer.md").read_text(encoding="utf-8")
    home = str(Path.home())
    shown = str(root).replace(home, "~", 1) if str(root).startswith(home) else str(root)
    return f"{BEGIN}\n{tpl.replace('{{ROOT}}', shown).replace('{{AGENT}}', agent).strip()}\n{END}\n"


def upsert_block(path: Path, block: str) -> str:
    """Insert or replace the caderno block; leave the rest of the file alone."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if BEGIN in old and END in old:
        head, rest = old.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new = head + block.rstrip("\n") + tail
        verdict = "updated"
    else:
        sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
        new = old + sep + block
        verdict = "added"
    if new == old:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return verdict


def remove_block(path: Path) -> bool:
    if not path.exists():
        return False
    old = path.read_text(encoding="utf-8")
    if BEGIN not in old:
        return False
    head, rest = old.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    path.write_text((head.rstrip("\n") + "\n" + tail.lstrip("\n")).lstrip("\n"), encoding="utf-8")
    return True


def cmd_connect(a) -> int:
    root = notebook_root(a.root)
    chosen = a.agents or [name for name, p in AGENTS.items() if p.expanduser().parent.is_dir()]
    if not chosen:
        print("No agent config folders found (~/.codex, ~/.claude, ~/.gemini). Name one: caderno connect codex")
        return 1
    for name in chosen:
        path = AGENTS[name].expanduser()
        if a.remove:
            print(f"{name}: {'removed from' if remove_block(path) else 'nothing in'} {path}")
        else:
            print(f"{name}: {upsert_block(path, pointer_block(root, name))} {path}")
    return 0


# --- notes -------------------------------------------------------------------


def cmd_new(a) -> int:
    root = notebook_root(a.root)
    slug = a.name or notes.slugify(a.description)
    if not notes.SLUG_RE.match(slug):
        sys.exit(f"caderno: '{slug}' is not a valid name (lowercase letters, digits, dashes)")
    folder = "machines" if a.type == "machine" else "memory"
    path = root / folder / f"{slug}.md"
    if path.exists():
        sys.exit(f"caderno: {path} already exists. Edit it instead of writing a second note.")
    path.write_text(notes.render({"description": a.description, "type": a.type}, a.body or "TODO"), encoding="utf-8")
    notes.write_indexes(root)
    print(path)
    return 0


def cmd_index(a) -> int:
    root = notebook_root(a.root)
    changed = notes.write_indexes(root)
    for p in changed:
        print(f"rewrote {p.relative_to(root)}")
    if not changed:
        print("indexes already up to date")
    return 0


def cmd_check(a) -> int:
    root = notebook_root(a.root)
    problems = notes.check(root, denylist())
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s)" if problems else "notebook is healthy")
    return 1 if problems else 0


def cmd_scan(a) -> int:
    """Secret scan. With --staged, scans what is about to be committed."""
    root = notebook_root(a.root)
    dl = denylist()
    hits = []
    if a.staged:
        names = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACM").stdout.split()
        for n in names:
            text = git(root, "show", f":{n}", check=False).stdout
            hits += [f"{n}:{ln}: {label}" for ln, label in notes.scan_text(text, dl)]
    else:
        for p in sorted(root.rglob("*")):
            if p.is_file() and ".git" not in p.parts and p.suffix in (".md", ".txt", ".toml", ".json", ".yml", ".yaml"):
                for ln, label in notes.scan_text(p.read_text(encoding="utf-8", errors="replace"), dl):
                    hits.append(f"{p.relative_to(root)}:{ln}: {label}")
    for h in hits:
        print(f"possible secret: {h}", file=sys.stderr)
    if hits:
        print(
            "caderno: refusing to commit. Remove the secret, or if it is a false alarm add "
            "`caderno:allow` to that line.",
            file=sys.stderr,
        )
        return 1
    return 0


# --- sync --------------------------------------------------------------------


def cmd_remote(a) -> int:
    root = notebook_root(a.root)
    if git(root, "remote", check=False).stdout.split().count("origin"):
        git(root, "remote", "set-url", "origin", a.url)
    else:
        git(root, "remote", "add", "origin", a.url)
    print(f"origin -> {a.url}")
    return 0


def cmd_sync(a) -> int:
    root = notebook_root(a.root)
    has_remote = "origin" in git(root, "remote", check=False).stdout.split()
    has_head = git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0
    branch = git(root, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip() or "main"

    if has_remote:
        heads = git(root, "ls-remote", "--heads", "origin", branch, check=False)
        if heads.returncode != 0:
            print(f"caderno: cannot reach origin: {heads.stderr.strip()}", file=sys.stderr)
            return 1
        if heads.stdout.strip():
            if not has_head:
                print(
                    "caderno: origin already has a notebook but this copy has no history.\n"
                    "Join it with `caderno init --clone <git-url>` instead.",
                    file=sys.stderr,
                )
                return 1
            pull = git(root, "pull", "-q", "--rebase", "--autostash", "origin", branch, check=False)
            if pull.returncode != 0:
                print(f"caderno: pull failed; resolve it by hand in {root}:\n{pull.stderr}", file=sys.stderr)
                return 1

    notes.write_indexes(root)
    git(root, "add", "-A")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        c = git(root, "commit", "-q", "-m", f"sync from {host_label()} at {stamp}", check=False)
        if c.returncode != 0:
            git(root, "reset", "-q", check=False)
            print(c.stderr or c.stdout, file=sys.stderr)
            return 1
        print("committed local changes")
    if has_remote:
        p = git(root, "push", "-q", "-u", "origin", branch, check=False)
        if p.returncode != 0:
            print(f"caderno: push failed:\n{p.stderr}", file=sys.stderr)
            return 1
    print("in sync" if has_remote else "committed locally (no remote yet: `caderno remote <git-url>`)")
    return 0


SYSTEMD_SERVICE = """[Unit]
Description=Sync the caderno notebook

[Service]
Type=oneshot
ExecStart={python} {cli} sync
TimeoutStartSec=2min
"""

SYSTEMD_TIMER = """[Unit]
Description=Sync the caderno notebook every {minutes} minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec={minutes}min
Persistent=true

[Install]
WantedBy=timers.target
"""

LAUNCHD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.caderno.sync</string>
  <key>ProgramArguments</key><array><string>{python}</string><string>{cli}</string><string>sync</string></array>
  <key>StartInterval</key><integer>{seconds}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def cmd_install_timer(a) -> int:
    notebook_root(a.root)
    cli = KIT_ROOT / "bin" / "caderno"
    vals = dict(python=sys.executable, cli=cli, minutes=a.minutes, seconds=a.minutes * 60)
    system = platform.system()
    if system == "Linux" and shutil.which("systemctl"):
        d = Path.home() / ".config" / "systemd" / "user"
        d.mkdir(parents=True, exist_ok=True)
        (d / "caderno-sync.service").write_text(SYSTEMD_SERVICE.format(**vals))
        (d / "caderno-sync.timer").write_text(SYSTEMD_TIMER.format(**vals))
        if a.dry_run:
            print(f"wrote units to {d} (not enabled: --dry-run)")
            return 0
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "caderno-sync.timer"], check=True)
        print(f"enabled caderno-sync.timer (every {a.minutes} min). Logs: journalctl --user -u caderno-sync")
        print("On a server with nobody logged in, also run: loginctl enable-linger $USER")
    elif system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "org.caderno.sync.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(LAUNCHD.format(log=Path.home() / "Library/Logs/caderno-sync.log", **vals))
        if a.dry_run:
            print(f"wrote {plist} (not loaded: --dry-run)")
            return 0
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
        print(f"loaded {plist}. Note: LaunchAgents only run while you are logged in.")
    else:
        print("No systemd or launchd here. Add this line with `crontab -e`:")
        print(f"*/{a.minutes} * * * * {sys.executable} {cli} sync >/dev/null 2>&1")
        print("On Windows, create a Task Scheduler task that runs the same command.")
    return 0


# --- status ------------------------------------------------------------------


def cmd_status(a) -> int:
    root = notebook_root(a.root)
    mem = notes.searchable_notes(root)
    print(f"notebook  {root}")
    print(f"machine   {host_label()}")
    print(f"notes     {len(mem)} searchable")
    last = git(root, "log", "-1", "--format=%cr (%h)", check=False).stdout.strip()
    print(f"last sync {last or 'never committed'}")
    remote = git(root, "remote", "get-url", "origin", check=False).stdout.strip()
    print(f"remote    {remote or 'none'}")
    for name, p in AGENTS.items():
        f = p.expanduser()
        on = f.exists() and BEGIN in f.read_text(encoding="utf-8", errors="replace")
        print(f"{name:<9} {'connected' if on else 'not connected'} ({f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="caderno", description="One notebook that every AI agent you use can read.")
    ap.add_argument("--version", action="version", version=f"caderno {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--root", help="notebook path (default: from `caderno init`)")
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, "create a notebook on this machine")
    p.add_argument("path", nargs="?")
    p.add_argument("--name", help="whose notebook it is")
    p.add_argument("--host", help="a short name for this machine")
    p.add_argument("--clone", metavar="GIT_URL", help="join a notebook you already keep on another machine")
    p.add_argument("-y", "--yes", action="store_true", help="accept defaults without asking")

    p = add("connect", cmd_connect, "point your agents at the notebook")
    p.add_argument("agents", nargs="*", metavar="AGENT", help="codex, claude or gemini (default: every one installed)")
    p.add_argument("--remove", action="store_true", help="take the pointer back out")

    p = add("new", cmd_new, "start a new note")
    p.add_argument("description", help="the one line an agent reads to decide whether to open it")
    p.add_argument("--type", default="lesson", choices=notes.NOTE_TYPES)
    p.add_argument("--name", help="file name (default: from the description)")
    p.add_argument("--body")

    add("index", cmd_index, "rebuild the one-line indexes")
    add("check", cmd_check, "find missing descriptions, stale indexes and secrets")
    p = add("scan", cmd_scan, "scan for secrets (used by the pre-commit hook)")
    p.add_argument("--staged", action="store_true")
    p = add("remote", cmd_remote, "set the git remote the notebook syncs to")
    p.add_argument("url")
    add("sync", cmd_sync, "pull, reindex, commit and push")
    p = add("install-timer", cmd_install_timer, "run `caderno sync` on a schedule")
    p.add_argument("--minutes", type=int, default=5)
    p.add_argument("--dry-run", action="store_true", help="write the schedule files but don't enable them")
    add("status", cmd_status, "show what is set up on this machine")

    a = ap.parse_args(argv)
    if a.cmd == "connect":
        bad = [x for x in a.agents if x not in AGENTS]
        if bad:
            ap.error(f"unknown agent {', '.join(bad)} (choose from {', '.join(AGENTS)})")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
