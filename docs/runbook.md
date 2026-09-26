# Runbook

How to run both applications, rebuild the data, deploy them, and what to do when
something breaks on the day.

Written for someone who did not build this. Every command is meant to be copied
and run from the repository root.

---

## 1. First-time setup

Python 3.12 and Node 20 or later. Node is only needed for the front-end tests.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
pip install pytest httpx ruff kaggle
```

### The datasets

Six public Kaggle datasets, 212 MB in total, not committed. They need a Kaggle
token in `~/.kaggle/access_token`.

```bash
python scripts/fetch_data.py            # download all six
python scripts/fetch_data.py --check    # what is present, what is missing
python scripts/fetch_data.py --list     # slugs, licences and what each is for
```

Licences and provenance per dataset are in [data-sources.md](data-sources.md).
Only the SCMS delivery history is genuinely real transaction data; two are
public synthetic sets, and what we generate ourselves is listed in
[assumptions.md](assumptions.md).

### Build the demo pack

```bash
python scripts/build_demo_pack.py           # ~4 minutes, both applications
python scripts/build_demo_pack.py --check   # verify, without rebuilding
```

This writes the processed tables under `data/processed/` and the fitted models
under `models/`. Both applications **load** these at startup and never train
anything while serving, which is why a plan re-solves in about a second.

---

## 2. Run them locally

Two applications, two commands, two ports. They share no data and no runtime.

```bash
python -m uvicorn supplyguard.main:app --port 8001 --reload
```
```bash
python -m uvicorn trendwear.main:app --port 8002 --reload
```

- SupplyGuard (PR1): <http://127.0.0.1:8001>
- TrendWear Planner (P2): <http://127.0.0.1:8002>

Each serves its own front end at `/`, the shared CSS and JavaScript at
`/shared/`, and its API under `/api/`. Interactive API docs at `/docs`.

Startup takes ten to fifteen seconds: it loads the processed tables and warms
the headline figures, which turns the cockpit from a 7.9-second request into a
0.03-second one.

If startup fails with *"planning cache is incomplete"*, the demo pack is not
built. Run `python scripts/build_demo_pack.py`. The applications fail loudly on
purpose rather than quietly training a model.

---

## 3. Tests and lint

```bash
python -m pytest -q          # 350 tests
python -m ruff check .       # clean
```
```bash
cd packages/web && node --test     # 32 tests
```

Recorded on 26 September 2026: **350 Python tests pass, 32 JavaScript tests
pass, ruff reports no issues.** Tests that read raw data skip themselves when it
is absent, so the suite is meaningful on a fresh clone without a Kaggle token.

CI runs all three on every push and pull request
(`.github/workflows/ci.yml`). It caches `data/raw` so a normal push does not
re-download 212 MB.

---

## 4. Containers

One image per application, built from the repository root because each image
needs the shared `packages/` folder as well as its own code.

```bash
docker build -f apps/pr1/Dockerfile -t supplyguard .
docker run -p 7860:7860 supplyguard
```
```bash
docker build -f apps/p2/Dockerfile -t trendwear .
docker run -p 7860:7860 trendwear
```

Port 7860 is the Hugging Face Spaces default, so the same image runs locally and
hosted with no change. The images copy in the pre-built demo pack; they do not
download data and they do not train models.

### Verifying them

```bash
powershell -ExecutionPolicy Bypass -File scripts/verify_containers.ps1
```

Builds both images, starts each one, waits for `/api/health`, checks the pages and
the shared assets, confirms the startup log contains no download and no training,
then stops and removes the containers. It leaves the images behind.

**Status: not yet verified in Docker.** Docker was not installed on the machine
this was built on, so the images have never been built. What *is* verified is the
exact layout they create: `scripts/stage_space.py` assembles the same tree, and
both applications were started from it, on port 7860, with the container's
`PYTHONPATH`, and answered on `/api/health`, `/api/kpis`, the pages and
`/shared/`. The remaining risk is a dependency needing a system library on slim
Debian — `pulp` ships its own CBC binary and the rest are wheels, so this should
hold, but it is untested. Run the script above and this paragraph can go.

---

## 5. Hosting

Two routes were built. **Cloud Run is the one that works on a free account**; the
Hugging Face route is kept because the images and the staging are identical and
it becomes a two-minute deploy if the account is ever upgraded.

### Why Hugging Face did not work

Hugging Face moved **Docker Spaces behind the PRO plan** ($9/month). The pricing
page lists "Host ZeroGPU, Gradio & Docker Spaces" as a PRO feature, and the Space
creation form shows the Docker SDK as paid. On a free account:

* the Docker SDK cannot be selected at creation;
* pushing a README with `sdk: docker` is accepted at the repository level but the
  Space then fails with `CONFIG_ERROR`;
* the hardware cannot be downgraded to the free `cpu-basic` tier without PRO.

Nothing in this repository is at fault: the Dockerfile, the push and the upload
all succeeded. `scripts/deploy_spaces.py` is ready if the plan changes.

### Cloud Run (the working route)

Cloud Run builds the image itself with Cloud Build, so **no local Docker is
needed** — which is just as well, because it has never been installed here.

One-off setup, all of it yours:

1. Install the gcloud CLI: <https://cloud.google.com/sdk/docs/install>
2. `gcloud auth login`
3. `gcloud config set project YOUR_PROJECT_ID`
4. Attach billing to that project. The free tier covers a demo comfortably, but
   billing has to be enabled for Cloud Run to run at all.

Then:

```bash
powershell -ExecutionPolicy Bypass -File scripts/deploy_cloudrun.ps1
```

It checks the prerequisites, enables the three APIs, and deploys both services
from the staged trees. `-App pr1` does one; `-Check` lists what is already up.

**Why the flags are what they are.** `--memory 2Gi`, because the planning context
plus three fitted models sits well above the 512 MB that Render, Koyeb and Fly
offer free — that is what ruled them out. `--cpu 2`, because the eight-plant
solve is CPU-bound. `--port 7860`, matching the Dockerfile, though the image
reads `$PORT` and would work on Cloud Run's default 8080 as well.

**Cold starts.** `--min-instances 0` means the first request after an idle period
waits 20–30 seconds while the container starts and the context loads. Open both
URLs ten minutes before the demo, or set `--min-instances 1` for the day and put
it back afterwards.

### Why not Vercel

Asked and answered, because it is the obvious first thought: Vercel's serverless
functions cap at 250 MB unzipped and the dependencies alone are **602 MB**
(scipy 109, pyarrow 86, pandas 60, xgboost 56, sklearn 41). Serverless is also
stateless, and both applications deliberately load once at startup and warm their
headline figures — the design that turned the cockpit from 7.9 s into 0.03 s.
Finally the eight-plant solve is 7.9 s against a 10 s function limit.

## 5b. Deploy to Hugging Face Spaces (needs PRO)

A Space is a git repository with a `Dockerfile` and a `README.md` carrying
Hugging Face front matter at its root. This repository has two applications, so
a staging step assembles one valid Space per application.

```bash
python scripts/stage_space.py pr1 --force
python scripts/stage_space.py p2 --force
```

That writes `build/spaces/pr1` (31 MB) and `build/spaces/p2` (2 MB), each
containing the Dockerfile as `Dockerfile`, `requirements.txt`, `packages/`, that
application's backend and `web/`, and only its own processed tables and models.
The raw datasets are not copied, and neither application ever sees the other.

Then, once per Space, create it at <https://huggingface.co/new-space> with SDK
**Docker**, and push:

```bash
cd build/spaces/pr1
git init -b main && git lfs install
git remote add origin https://huggingface.co/spaces/Nouman-20/supplyguard
git add -A && git commit -m "deploy"
git push --force origin main
```

The password prompt wants a Hugging Face **write token**, not an account
password. The 29 MB delay model goes through Git LFS, which the staged
`.gitattributes` already configures.

`.github/workflows/deploy.yml` does the same thing automatically after CI passes
on `main`, or on demand from the Actions tab. It needs two repository secrets:

| Secret | Why |
|---|---|
| `HF_TOKEN` | a Hugging Face write token |
| `KAGGLE_ACCESS_TOKEN` | to rebuild the processed tables, which are gitignored |

Without `HF_TOKEN` the job explains what is missing and stops rather than
failing red.

**Rotate both tokens after 30 September.** They were issued for this build.

---

## 6. On the day

Work down [demo-checklist.md](demo-checklist.md) on 27 September and again on
the morning of the 28th. The short version:

1. Both servers started **before** walking into the room, from the laptop.
2. All thirteen tabs already open, cockpits first.
3. The Spaces opened ten minutes earlier so they are awake.

### If a Space is asleep

It takes 30–60 seconds to wake and shows a build or loading screen. Do not wait
in silence: switch to the laptop copy, which is the primary demo anyway, and
mention the Space is the link we leave behind.

### If a Space is broken

Demo from the laptop. Nothing in the demo needs the hosted copy.

### If the laptop copy will not start

```bash
python scripts/build_demo_pack.py --check
```

- *Missing artifacts* → `python scripts/build_demo_pack.py` (four minutes).
- *Missing raw data* → `python scripts/fetch_data.py` (needs a network).
- Port already taken → `--port 8003` and open that instead.

### If a screen is blank but the API answers

A stale module in the browser. Hard-refresh (Ctrl+Shift+R). Both applications
send `Cache-Control: no-cache, must-revalidate` on the front-end paths to make
this rare.

### If an optimisation returns "infeasible"

It should not: the relaxation ladder raises the concentration cap and then
waives contract minimums, and always reports what it relaxed. If it happens,
narrow the request — one plant, two weeks — and say plainly that the constraint
set is tight for that slice. That is a real answer about a real model, and it is
better than clicking again.

### Offline fallback

Neither application needs a network once the demo pack is built. This is worth
knowing because conference Wi-Fi is not worth trusting: turn Wi-Fi off, and both
applications still start and every screen still works. Step 3 of the checklist
proves it before the day.
