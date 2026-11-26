"""Shared helpers for lab MCP modules (status, schemas, result shape)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import mcp_ui
import oslab


def obj(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def check(args, allowed, required=()):
    unknown = set(args) - set(allowed)
    if unknown:
        raise oslab.PlanError("Unexpected argument(s): {0}".format(", ".join(sorted(unknown))), code="INVALID_ARGS")
    missing = [key for key in required if args.get(key) in (None, "")]
    if missing:
        raise oslab.PlanError("Missing argument(s): {0}".format(", ".join(missing)), code="INVALID_ARGS")


def lab_status(root: str, lab: str) -> dict:
    host = oslab.host_info(root)
    host = {**host, "root": root}
    return oslab.lab_status(lab, host)


def result(value):
    return mcp_ui.result(value)


def annotate_ro(tools):
    for tool in tools:
        if "annotations" not in tool:
            tool["annotations"] = mcp_ui.annotations(read_only=True, idempotent=True)
    return tools


def console_port() -> int:
    raw = os.environ.get("OSLAB_CONSOLE_PORT", "5050")
    try:
        port = int(raw)
    except ValueError as exc:
        raise oslab.PlanError("OSLAB_CONSOLE_PORT is not a number: {0}".format(raw),
                              code="INVALID_ARGS") from exc
    if not 0 < port < 65536:
        raise oslab.PlanError("OSLAB_CONSOLE_PORT out of range: {0}".format(port), code="INVALID_ARGS")
    return port


def list_console_jobs(root: str, lab: str | None = None) -> dict:
    """List lab jobs from the running console, or a local JobService fallback."""
    port = console_port()
    try:
        with urllib.request.urlopen("http://127.0.0.1:{0}/api/jobs".format(port), timeout=2) as reply:
            data = json.loads(reply.read().decode("utf-8"))
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        if not isinstance(jobs, list):
            jobs = []
        if lab:
            jobs = [job for job in jobs if job.get("lab") == lab]
        return {"jobs": jobs, "source": "console", "port": port}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        service = oslab.JobService(root)
        jobs = service.list()
        if lab:
            jobs = [job for job in jobs if job.get("lab") == lab]
        return {
            "jobs": jobs,
            "source": "local",
            "port": port,
            "note": "Console on 127.0.0.1:{0} is not reachable; showing local JobService rows (often empty).".format(port),
        }


def get_console_job(root: str, job_id: str, lab: str | None = None) -> dict:
    """Poll one job from the console, or the local JobService fallback."""
    port = console_port()
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:{0}/api/jobs/{1}".format(port, job_id), timeout=2
        ) as reply:
            job = json.loads(reply.read().decode("utf-8"))
        if lab and job.get("lab") != lab:
            raise oslab.PlanError("Job {0} is not a {1} lab job".format(job_id, lab), code="NOT_FOUND")
        return {"job": job, "source": "console", "port": port}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise oslab.PlanError("Job not found: {0}".format(job_id), code="NOT_FOUND") from exc
        raise oslab.PlanError("Console job poll failed: {0}".format(exc.code), code="CONSOLE") from exc
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        service = oslab.JobService(root)
        job = service.get(job_id)
        if job is None:
            raise oslab.PlanError(
                "Job not found locally and console on 127.0.0.1:{0} is not reachable".format(port),
                code="NOT_FOUND",
            )
        payload = job.to_dict(logs=True)
        if lab and payload.get("lab") != lab:
            raise oslab.PlanError("Job {0} is not a {1} lab job".format(job_id, lab), code="NOT_FOUND")
        return {"job": payload, "source": "local", "port": port}
