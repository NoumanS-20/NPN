"""The two containers, and the workflow that ships them.

These are cheap text assertions, and they exist because a container that is
wrong is discovered late — usually while a Space build log scrolls past during
the ten minutes before a demo.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = {
    "pr1": ROOT / "apps" / "pr1" / "Dockerfile",
    "p2": ROOT / "apps" / "p2" / "Dockerfile",
}


def test_each_application_has_its_own_dockerfile() -> None:
    for app, path in DOCKERFILES.items():
        assert path.exists(), f"{app} has no Dockerfile"


def test_each_container_is_a_single_python_stage() -> None:
    """One stage. A multi-stage build here would buy nothing and cost clarity."""
    for app, path in DOCKERFILES.items():
        text = path.read_text(encoding="utf-8")
        froms = [line for line in text.splitlines() if line.startswith("FROM ")]
        assert len(froms) == 1, f"{app} has {len(froms)} stages"
        assert "python:3.12" in froms[0], f"{app} does not pin Python 3.12"


def test_each_container_copies_the_backend_the_web_folder_and_the_shared_package() -> None:
    for app, path in DOCKERFILES.items():
        text = path.read_text(encoding="utf-8")
        assert f"apps/{app}/backend" in text, f"{app} does not copy its backend"
        assert f"apps/{app}/web" in text, f"{app} does not copy its web folder"
        assert "packages/" in text, f"{app} does not copy the shared packages"


def test_each_container_exposes_the_spaces_port_and_runs_uvicorn_on_it() -> None:
    """7860 is the Hugging Face Spaces default; a different port serves nothing."""
    for app, path in DOCKERFILES.items():
        text = path.read_text(encoding="utf-8")
        assert "EXPOSE 7860" in text, f"{app} does not expose 7860"
        assert "--port" in text and "7860" in text.split("CMD")[-1], f"{app} CMD is not on 7860"
        assert "uvicorn" in text.split("CMD")[-1], f"{app} does not end in a uvicorn CMD"


def test_each_container_honours_an_injected_port() -> None:
    """Cloud Run sets $PORT and ignores EXPOSE; Spaces expects 7860.

    One image has to satisfy both, which means the default lives in the CMD and
    the exec form cannot be used — it would pass the literal string "$PORT".
    """
    for app, path in DOCKERFILES.items():
        cmd = path.read_text(encoding="utf-8").split("CMD")[-1]
        assert "${PORT:-7860}" in cmd, f"{app} ignores an injected PORT"
        assert not cmd.strip().startswith("["), f"{app} uses exec form, so $PORT will not expand"


def test_the_healthcheck_probes_the_same_port_the_app_listens_on() -> None:
    """A probe on a fixed port fails forever wherever the port is injected.

    Render and Cloud Run both set $PORT. When the probe ignored it, the build
    succeeded and the deploy failed, with nothing in the log saying which of the
    two was actually wrong.
    """
    for app, path in DOCKERFILES.items():
        text = path.read_text(encoding="utf-8")
        probe = [line for line in text.splitlines() if "urlopen" in line]
        assert probe, f"{app} has no healthcheck probe"
        assert "PORT" in probe[0], f"{app} probes a hardcoded port"
        assert "127.0.0.1:7860/api/health" not in text, f"{app} still hardcodes 7860"


def test_each_container_runs_the_right_application() -> None:
    assert "supplyguard.main:app" in DOCKERFILES["pr1"].read_text(encoding="utf-8")
    assert "trendwear.main:app" in DOCKERFILES["p2"].read_text(encoding="utf-8")


def test_neither_container_mentions_the_other_application() -> None:
    """The separation rule holds at the container boundary too."""
    pr1 = DOCKERFILES["pr1"].read_text(encoding="utf-8")
    p2 = DOCKERFILES["p2"].read_text(encoding="utf-8")
    assert "trendwear" not in pr1 and "apps/p2" not in pr1
    assert "supplyguard" not in p2 and "apps/pr1" not in p2


def test_neither_container_trains_a_model_or_downloads_data_at_build_time() -> None:
    """A Space build that fetches 212 MB from Kaggle would fail, slowly."""
    for app, path in DOCKERFILES.items():
        text = path.read_text(encoding="utf-8")
        for forbidden in ("fetch_data", "kaggle", "pipeline build", "--build"):
            assert forbidden not in text, f"{app} does work at build time ({forbidden})"


def test_the_staging_script_declares_both_spaces() -> None:
    from scripts.stage_space import SPACES

    assert set(SPACES) == {"pr1", "p2"}
    for name, space in SPACES.items():
        assert space.repo.count("/") == 1, f"{name} space id is not owner/name"
        assert space.port == 7860


def test_the_deploy_workflow_exists_and_waits_for_ci() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "workflow_run" in workflow or "needs:" in workflow, "deploy does not wait for CI"
    assert "HF_TOKEN" in workflow, "deploy has no Hugging Face token"
    assert "secrets." in workflow, "deploy hard-codes a credential"
