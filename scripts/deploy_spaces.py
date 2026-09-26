"""Create and deploy both Hugging Face Spaces from the API, not the web UI.

    .venv\\Scripts\\python.exe scripts\\deploy_spaces.py            # deploy both
    .venv\\Scripts\\python.exe scripts\\deploy_spaces.py --app pr1  # just one
    .venv\\Scripts\\python.exe scripts\\deploy_spaces.py --status    # look, change nothing
    .venv\\Scripts\\python.exe scripts\\deploy_spaces.py --dry-run   # check everything first

Why this exists: creating a Space through the web form meant choosing an SDK and
a hardware tier by hand, and getting either wrong produced a Space that could not
be fixed afterwards — Hugging Face will not let you downgrade hardware without a
paid plan. Creating the Space from the API sets both correctly at birth, so there
is nothing to downgrade and nothing to click.

It also uploads with ``upload_folder``, which uses Hugging Face's own transfer
protocol. That removes git and git-lfs from the path entirely, along with the
"file over 10 MB was not tracked" failure that comes with them.

The token is read from the gitignored ``.env``. It is never printed, never
written to disk, and never passed on a command line.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPACES = {
    "pr1": {
        "repo": "Nouman-20/supplyguard",
        "dir": ROOT / "build" / "spaces" / "pr1",
        "name": "SupplyGuard (PR1)",
        "url": "https://nouman-20-supplyguard.hf.space",
    },
    "p2": {
        "repo": "Nouman-20/trendwear-planner",
        "dir": ROOT / "build" / "spaces" / "p2",
        "name": "TrendWear Planner (P2)",
        "url": "https://nouman-20-trendwear-planner.hf.space",
    },
}

# Gradio, not Docker: Hugging Face moved the Docker SDK behind the PRO plan, so a
# free account cannot run one however it is created. A Gradio Space simply runs
# `python app.py`, and app.py starts uvicorn on the port Spaces proxies — the
# application itself is identical to the one in the Dockerfile.
SDK = "gradio"

# Requested, not guaranteed: the creation form greys CPU basic out for free
# accounts and offers ZeroGPU instead. If the API refuses it, the Space is
# created on whatever the account is allowed and the deploy continues.
HARDWARE = "cpu-basic"

# An earlier git-based attempt leaves a .git directory in the staged tree.
# upload_folder would happily ship all of it, so it is excluded by name.
# .gitattributes is NOT excluded: Hugging Face reads it for large-file handling.
IGNORE = [".git/**", "**/__pycache__/**", "**/*.pyc"]


def read_token() -> str | None:
    """Take HF_TOKEN from .env. Never log it, never echo it."""
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("HF_TOKEN"):
            _, _, value = line.partition("=")
            return value.strip().strip('"').strip("'") or None
    return None


def describe(api, repo: str) -> str:
    from huggingface_hub.utils import HfHubHTTPError
    try:
        info = api.space_info(repo)
    except HfHubHTTPError as error:
        return f"not reachable ({error.response.status_code})"
    runtime = getattr(info, "runtime", None) or {}
    stage = runtime.get("stage") if isinstance(runtime, dict) else getattr(runtime, "stage", None)
    hardware = (
        runtime.get("hardware") if isinstance(runtime, dict)
        else getattr(runtime, "hardware", None)
    )
    current = (hardware or {}).get("current") if isinstance(hardware, dict) else None
    message = runtime.get("errorMessage") if isinstance(runtime, dict) else None
    out = f"stage={stage} hardware={current}"
    return f"{out} error={message}" if message else out


def deploy(api, key: str, recreate: bool) -> bool:
    from huggingface_hub.utils import HfHubHTTPError

    space = SPACES[key]
    repo, folder = space["repo"], space["dir"]
    print(f"\n=== {space['name']}  ->  {repo}")

    if not folder.exists():
        print(f"  FAIL  {folder} is missing.")
        print(f"        Stage it first: python scripts/stage_space.py {key} --force")
        return False

    files = [
        p for p in folder.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(folder).parts
        and "__pycache__" not in p.parts
    ]
    megabytes = sum(p.stat().st_size for p in files) / 1e6
    print(f"  {len(files)} files, {megabytes:.0f} MB staged")

    if recreate:
        try:
            api.delete_repo(repo_id=repo, repo_type="space")
            print("  ok    deleted the old Space (its hardware could not be downgraded)")
            time.sleep(3)
        except HfHubHTTPError as error:
            if error.response.status_code == 404:
                print("  ok    no existing Space to remove")
            else:
                print(f"  FAIL  could not delete: {error.response.status_code} {error}")
                return False

    created = False
    for hardware in (HARDWARE, None):
        try:
            api.create_repo(
                repo_id=repo,
                repo_type="space",
                space_sdk=SDK,
                space_hardware=hardware,
                private=False,
                exist_ok=True,
            )
            print(f"  ok    created with sdk={SDK} hardware={hardware or 'account default'}")
            created = True
            break
        except HfHubHTTPError as error:
            if hardware is not None:
                print(f"  ...   {hardware} refused ({error.response.status_code}); "
                      "retrying on the account default")
                continue
            print(f"  FAIL  could not create: {error.response.status_code} {error}")
    if not created:
        return False

    print(f"  ...   uploading {megabytes:.0f} MB (the 30 MB model takes a minute)")
    try:
        api.upload_folder(
            repo_id=repo,
            repo_type="space",
            folder_path=str(folder),
            commit_message="deploy",
            ignore_patterns=IGNORE,
        )
    except HfHubHTTPError as error:
        print(f"  FAIL  upload failed: {error.response.status_code} {error}")
        return False

    print(f"  ok    uploaded — {describe(api, repo)}")
    print(f"        building: https://huggingface.co/spaces/{repo}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=[*SPACES, "both"], default="both")
    parser.add_argument("--status", action="store_true", help="report and change nothing")
    parser.add_argument("--dry-run", action="store_true", help="check inputs, touch nothing")
    parser.add_argument("--keep", action="store_true", help="do not delete before creating")
    args = parser.parse_args(argv)

    # Prefer the credential the hf CLI stores after `hf auth login`: it is the
    # user's own browser/terminal login, so no secret has to sit in a file or be
    # passed around. .env stays as the fallback for unattended runs like CI.
    from huggingface_hub import get_token
    token = get_token() or read_token()
    if not token:
        print("Not authenticated. Either of these works:")
        print("  hf auth login          (recommended — paste your write token at its prompt)")
        print("  add HF_TOKEN=... to .env")
        return 1
    source = "the hf CLI login" if get_token() else ".env"
    print(f"Authenticated from {source} (token not shown).")

    targets = list(SPACES) if args.app == "both" else [args.app]

    if args.dry_run:
        for key in targets:
            space = SPACES[key]
            folder = space["dir"]
            files = [
                p for p in folder.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(folder).parts
                and "__pycache__" not in p.parts
            ] if folder.exists() else []
            print(f"  {space['name']:24} staged={folder.exists()} "
                  f"files={len(files)} -> {space['repo']}")
        print(f"\nWould create each with sdk={SDK}, hardware={HARDWARE}, then upload.")
        return 0

    from huggingface_hub import HfApi
    api = HfApi(token=token)

    try:
        who = api.whoami()
        print(f"Authenticated as {who.get('name')} ({who.get('type')}).")
    except Exception as error:  # noqa: BLE001 — the message is what matters
        print(f"Token rejected: {error}")
        print("It needs to be a WRITE token: https://huggingface.co/settings/tokens")
        return 1

    if args.status:
        for key in targets:
            print(f"  {SPACES[key]['repo']:34} {describe(api, SPACES[key]['repo'])}")
        return 0

    failures = sum(not deploy(api, key, recreate=not args.keep) for key in targets)

    if failures:
        print(f"\n{failures} Space(s) failed. Nothing else will help until that is fixed.")
        return 1

    print("\nBoth uploaded. Builds take a few minutes; watch them with:")
    print("  .venv\\Scripts\\python.exe scripts\\deploy_spaces.py --status")
    for key in targets:
        print(f"  {SPACES[key]['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
