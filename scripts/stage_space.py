"""Assemble a Hugging Face Space directory for one application.

A Space is a git repository with a ``Dockerfile`` and a ``README.md`` carrying
Hugging Face's front matter at its root. Our repository has neither at the root,
because it holds two applications — so this script copies what one application
needs into a staging directory that is a valid Space, and prints the three
commands that push it.

    python scripts/stage_space.py pr1
    python scripts/stage_space.py p2 --out build/spaces/p2

What it copies, and nothing else:

* the application's Dockerfile, as ``Dockerfile``
* ``requirements.txt`` and the shared ``packages/``
* the application's backend and its ``web/`` folder
* the demo pack for that application only — its processed tables and its models

The raw datasets are not copied: 212 MB that neither hosted application reads.
Neither is the other application, so the separation rule survives deployment.

This script does not push. Pushing publishes, and that is the user's call.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Space:
    key: str
    repo: str                  # owner/name, as Hugging Face addresses it
    title: str
    emoji: str
    module: str                # the uvicorn target, for the README
    processed: str             # the processed-table folder for this app alone
    models: str
    blurb: str
    port: int = 7860


SPACES: dict[str, Space] = {
    "pr1": Space(
        key="pr1",
        repo="Nouman-20/supplyguard",
        title="SupplyGuard — Procurement Planning",
        emoji="🛡️",
        module="supplyguard.main:app",
        processed="data/processed/pr1-v1",
        models="models/pr1",
        blurb=(
            "Supplier allocation and delivery-risk prediction. Prices risk in money inside a "
            "mixed-integer plan across 520 suppliers and eight plants, and predicts delivery "
            "delay before a purchase order is released."
        ),
    ),
    "p2": Space(
        key="p2",
        repo="Nouman-20/trendwear-planner",
        title="TrendWear Planner — Integrated S&OP",
        emoji="🧵",
        module="trendwear.main:app",
        processed="data/processed/p2-v1",
        models="models/p2",
        blurb=(
            "A rolling monthly sales and operations planning cycle for apparel: demand forecast, "
            "cold-start for styles with no history, constrained production, fabric lot sizing "
            "against MOQ and lead time, and markdown timing from in-season sell-through."
        ),
    ),
}

# Git LFS, because the delay model is 29 MB and Hugging Face asks for LFS above
# ten. The parquet files are small but the same rule keeps the list short.
GITATTRIBUTES = """\
*.joblib filter=lfs diff=lfs merge=lfs -text
*.parquet filter=lfs diff=lfs merge=lfs -text
"""

# Everything Cloud Build does not need when deploying with --source. The models
# and processed tables are NOT excluded: the image is built around them.
GCLOUDIGNORE = """\
.git/
**/__pycache__/
*.pyc
.gitattributes
"""


# A Gradio Space runs `python app.py`. That is the only thing the free tier will
# do for us — the Docker SDK is behind the paid plan — so app.py starts uvicorn
# on the port Spaces proxies and serves the FastAPI application unchanged.
#
# Nothing about the application is adapted for this. It is the same ASGI app the
# Dockerfile runs and the same one that runs locally; only the launcher differs.
APP_PY = '''"""Entry point for a Hugging Face Gradio Space.

Spaces runs this file and proxies whatever listens on $PORT (7860 by default).
The application itself is untouched: same ASGI app, same planning cache, same
pre-fitted models. Startup loads them once and warms the headline figures, which
takes ten to fifteen seconds and then serves in milliseconds.
"""

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "packages"), str(HERE / "apps" / "{key}" / "backend")]

import uvicorn  # noqa: E402  - the path has to be set before this import

from {module}.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
'''

def readme(space: Space) -> str:
    """The Space front matter, plus enough for a visitor arriving cold."""
    return f"""---
title: {space.title}
emoji: {space.emoji}
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
python_version: "3.12"
pinned: false
license: mit
---

# {space.title}

{space.blurb}

Built for the Cognizant NPN Supply Chain Management hackathon by **team Vortex5**.
Source, tests, measured results and the documentation set:
<https://github.com/NoumanS-20/NPN>

## What this deployment is

The container carries pre-built artifacts: the processed planning tables and the
fitted models. Nothing is trained or downloaded when a page loads, which is why
a plan re-solves in about a second.

This Space sleeps after inactivity and takes 30–60 seconds to wake.

## Honesty about the data

Every screen states the origin of the numbers it shows — real, public-synthetic,
or generated by us — and every accuracy figure is measured on real rows only,
against a named baseline. See `docs/data-sources.md` and `docs/assumptions.md`
in the repository.
"""


def _force_remove(func, path, _exc) -> None:
    """Delete a file that git left read-only.

    A previous git-based push leaves .git/objects full of read-only pack files,
    and shutil.rmtree raises PermissionError on them under Windows. Clearing the
    bit and retrying is the documented fix.
    """
    import os
    import stat

    os.chmod(path, stat.S_IWRITE)
    func(path)


def stage(space: Space, out: Path, force: bool = False) -> Path:
    if out.exists():
        if not force:
            raise SystemExit(f"{out} already exists; pass --force to replace it")
        shutil.rmtree(out, onexc=_force_remove)
    out.mkdir(parents=True)

    def copy(source: str, destination: str | None = None) -> None:
        src = ROOT / source
        dst = out / (destination or source)
        if not src.exists():
            raise SystemExit(
                f"missing {source}. Build the demo pack first:\n"
                "    python scripts/build_demo_pack.py"
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)

    copy(f"apps/{space.key}/Dockerfile", "Dockerfile")
    copy("requirements.txt")
    copy("packages")
    copy(f"apps/{space.key}/backend")
    copy(f"apps/{space.key}/web")
    copy(space.processed)
    copy(space.models)

    (out / "app.py").write_text(
        APP_PY.format(key=space.key, module=space.module.split(".")[0]), encoding="utf-8"
    )

    # The Gradio SDK expects gradio to be installable even when, as here, the
    # application never imports it. Appending rather than editing the source
    # requirements keeps the Docker image free of it.
    requirements = (out / "requirements.txt").read_text(encoding="utf-8")
    if "gradio" not in requirements:
        (out / "requirements.txt").write_text(
            requirements.rstrip()
            + "\ngradio>=5,<6        # only so the Spaces SDK resolves\n",
            encoding="utf-8",
        )

    (out / "README.md").write_text(readme(space), encoding="utf-8")
    (out / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")

    # Cloud Run's --source deploy uploads this directory to Cloud Build. Without
    # this it would also upload the .git left by a git-based push and every
    # __pycache__ written by a local test run.
    (out / ".gcloudignore").write_text(GCLOUDIGNORE, encoding="utf-8")
    return out


def size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=sorted(SPACES), help="which application to stage")
    parser.add_argument("--out", default=None, help="staging directory")
    parser.add_argument("--force", action="store_true", help="replace the staging directory")
    args = parser.parse_args(argv)

    space = SPACES[args.app]
    out = Path(args.out) if args.out else ROOT / "build" / "spaces" / space.key
    stage(space, out, force=args.force)

    print(f"Staged {space.repo} in {out} ({size_mb(out):.0f} MB)")
    print("\nCreate the Space once, in the browser: https://huggingface.co/new-space")
    print(f"  name: {space.repo.split('/')[1]}    SDK: Docker    visibility: public")
    print("\nThen push:")
    print(f"  cd {out}")
    print("  git init -b main && git lfs install")
    print(f"  git remote add origin https://huggingface.co/spaces/{space.repo}")
    print('  git add -A && git commit -m "deploy"')
    print("  git push --force origin main        # asks for your HF token as the password")
    print("\nThe Space builds in a few minutes, then answers at:")
    print(f"  https://{space.repo.replace('/', '-').lower()}.hf.space/api/health")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
