"""
LangSmith Stats Backend — Single-file FastAPI server
======================================================
Securely proxies LangSmith data to your frontend.

Setup:
    pip install fastapi uvicorn langsmith python-dotenv

Run:
    export LANGSMITH_API_KEY="ls__..."   # or put it in a .env file
    python langsmith_backend.py
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

try:
    from langsmith import Client
except ImportError:
    raise SystemExit(
        "langsmith SDK not found. Install it with:  pip install langsmith"
    )

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="LangSmith Stats Proxy", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten this in production
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── LangSmith client (lazy-initialised so startup always succeeds) ─────────
_client: Client | None = None

def get_client() -> Client:
    global _client
    if _client is None:
        api_key = os.getenv("LANGSMITH_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="LANGSMITH_API_KEY environment variable is not set.",
            )
        _client = Client(api_key=api_key)
    return _client


# ── Helper utilities ───────────────────────────────────────────────────────
def _safe(value: Any, default=0):
    """Return value if truthy, else default."""
    return value if value is not None else default


def _format_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── /api/stats endpoint ────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    """
    Returns a JSON payload containing:
      - summary  : aggregate totals across all projects
      - projects : per-project stats (token usage, run counts, latency, cost)
      - runs     : the 50 most recent runs for the default/first project,
                   formatted for the dashboard table and latency chart
    """
    client = get_client()

    # ── 1. Fetch all projects with stats ───────────────────────────────────
    try:
        projects_raw = list(client.list_projects(include_stats=True))
    except Exception as exc:
        log.error("Failed to list projects: %s", exc)
        raise HTTPException(status_code=502, detail=f"LangSmith error: {exc}")

    if not projects_raw:
        return {
            "summary": _empty_summary(),
            "projects": [],
            "runs": [],
            "latency_chart": [],
            "token_chart": [],
        }

    # ── 2. Build per-project objects ───────────────────────────────────────
    projects = []
    total_tokens = 0
    total_cost = 0.0
    total_runs = 0
    latency_sum = 0.0
    latency_count = 0

    for p in projects_raw:
        # LangSmith returns stats as a nested dict inside the project object.
        # Attribute names may vary by SDK version — use .get() defensively.
        stats: dict = {}
        if hasattr(p, "stats") and p.stats:
            stats = p.stats if isinstance(p.stats, dict) else {}

        prompt_tokens   = _safe(stats.get("total_prompt_tokens"))
        completion_tokens = _safe(stats.get("total_completion_tokens"))
        tokens          = prompt_tokens + completion_tokens
        cost            = float(_safe(stats.get("total_cost"), 0.0))
        run_count       = _safe(stats.get("run_count", getattr(p, "run_count", 0)))
        avg_latency_ms  = float(_safe(stats.get("latency_p50"), 0.0))   # median latency in ms
        error_rate      = float(_safe(stats.get("error_rate"), 0.0))

        total_tokens += tokens
        total_cost   += cost
        total_runs   += run_count
        if avg_latency_ms:
            latency_sum   += avg_latency_ms
            latency_count += 1

        projects.append({
            "id":               str(p.id),
            "name":             p.name,
            "run_count":        run_count,
            "prompt_tokens":    prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":     tokens,
            "cost_usd":         round(cost, 6),
            "avg_latency_ms":   round(avg_latency_ms, 2),
            "error_rate_pct":   round(error_rate * 100, 2),
            "created_at":       _format_iso(getattr(p, "created_at", None)),
        })

    overall_latency = (latency_sum / latency_count) if latency_count else 0.0

    summary = {
        "total_tokens":   total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "total_runs":     total_runs,
        "avg_latency_ms": round(overall_latency, 2),
        "project_count":  len(projects),
    }

    # ── 3. Fetch recent runs from the first (default) project ──────────────
    default_project = projects_raw[0]
    runs_out = []
    latency_chart = []   # [{label, latency_ms}]
    token_chart   = []   # [{label, prompt, completion}]

    try:
        since = datetime.now(tz=timezone.utc) - timedelta(days=7)
        raw_runs = list(
            client.list_runs(
                project_name=default_project.name,
                start_time=since,
                limit=50,
                order="desc",
            )
        )
    except Exception as exc:
        log.warning("Could not fetch runs: %s", exc)
        raw_runs = []

    icons = {
        "llm":        "ri-robot-line",
        "chain":      "ri-link-m",
        "tool":       "ri-tools-line",
        "retriever":  "ri-search-line",
        "embedding":  "ri-braces-line",
        "prompt":     "ri-chat-3-line",
    }

    for r in raw_runs:
        run_type   = getattr(r, "run_type", "llm") or "llm"
        start      = getattr(r, "start_time", None)
        end        = getattr(r, "end_time", None)
        latency_ms = None
        if start and end:
            latency_ms = round((end - start).total_seconds() * 1000, 1)

        usage = {}
        if hasattr(r, "prompt_tokens"):
            usage = {
                "prompt_tokens":     _safe(r.prompt_tokens),
                "completion_tokens": _safe(r.completion_tokens),
                "total_tokens":      _safe(r.total_tokens),
            }
        elif hasattr(r, "token_usage") and r.token_usage:
            u = r.token_usage
            usage = {
                "prompt_tokens":     _safe(u.get("prompt_tokens")),
                "completion_tokens": _safe(u.get("completion_tokens")),
                "total_tokens":      _safe(u.get("total_tokens")),
            }

        # Truncate run name for display
        name = getattr(r, "name", "") or "Unnamed Run"
        short_id = str(r.id)[:8] + "..." + str(r.id)[-6:]

        status = "Done"
        if getattr(r, "error", None):
            status = "Error"
        elif end is None:
            status = "Running"

        run_obj = {
            "id":          str(r.id),
            "short_id":    short_id,
            "name":        name,
            "run_type":    run_type,
            "icon":        icons.get(run_type, "ri-flashlight-line"),
            "status":      status,
            "start_time":  _format_iso(start),
            "end_time":    _format_iso(end),
            "latency_ms":  latency_ms,
            "usage":       usage,
            "cost_usd":    round(float(_safe(getattr(r, "total_cost", 0))), 6),
        }
        runs_out.append(run_obj)

        # Chart data points (last 20 for readability)
        if len(latency_chart) < 20 and latency_ms is not None:
            label = start.strftime("%m/%d %H:%M") if start else "?"
            latency_chart.append({"label": label, "latency_ms": latency_ms})

        if len(token_chart) < 20 and usage:
            label = start.strftime("%m/%d %H:%M") if start else "?"
            token_chart.append({
                "label":      label,
                "prompt":     usage.get("prompt_tokens", 0),
                "completion": usage.get("completion_tokens", 0),
            })

    # Reverse so charts read oldest → newest
    latency_chart.reverse()
    token_chart.reverse()

    return {
        "summary":       summary,
        "projects":      projects,
        "runs":          runs_out,
        "latency_chart": latency_chart,
        "token_chart":   token_chart,
    }


def _empty_summary() -> dict:
    return {
        "total_tokens":   0,
        "total_cost_usd": 0.0,
        "total_runs":     0,
        "avg_latency_ms": 0.0,
        "project_count":  0,
    }


# ── Health check ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("langsmith_backend:app", host="0.0.0.0", port=8000, reload=True)