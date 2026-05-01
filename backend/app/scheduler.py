"""TrackedScheduler — copy of the template wrapper. APScheduler with run history."""

from __future__ import annotations

import asyncio
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Deque

from apscheduler.schedulers.asyncio import AsyncIOScheduler

HISTORY_PER_JOB = 50


@dataclass
class JobRun:
    started_at: str
    ended_at: str | None
    status: str
    duration_ms: int | None
    error: str | None


@dataclass
class JobInfo:
    name: str
    trigger: str
    func_qualname: str
    history: Deque[JobRun] = field(default_factory=lambda: deque(maxlen=HISTORY_PER_JOB))


class TrackedScheduler:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.scheduler = AsyncIOScheduler()
        self.jobs: dict[str, JobInfo] = {}
        self._funcs: dict[str, Callable[..., Awaitable[Any] | Any]] = {}
        self._on_failed: list[Callable[[str, BaseException], Any]] = []
        self._on_completed: list[Callable[[str], Any]] = []

    def interval(self, name: str, **trigger_kwargs: Any):
        def decorator(func):
            self._register(name, func, "interval", trigger_kwargs)
            return func
        return decorator

    def cron(self, name: str, **trigger_kwargs: Any):
        def decorator(func):
            self._register(name, func, "cron", trigger_kwargs)
            return func
        return decorator

    def on_job_failed(self, fn: Callable[[str, BaseException], Any]) -> Callable:
        self._on_failed.append(fn)
        return fn

    def on_job_completed(self, fn: Callable[[str], Any]) -> Callable:
        self._on_completed.append(fn)
        return fn

    def start(self) -> None:
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    async def run_now(self, name: str) -> None:
        if name not in self._funcs:
            raise KeyError(name)
        asyncio.create_task(self._invoke(name))

    def status(self) -> list[dict]:
        out = []
        for name, info in self.jobs.items():
            job = self.scheduler.get_job(name)
            next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
            out.append({
                "name": name,
                "trigger": info.trigger,
                "next_run": next_run,
                "history": [asdict(r) for r in info.history],
            })
        return out

    def _register(
        self,
        name: str,
        func: Callable[..., Awaitable[Any] | Any],
        trigger_type: str,
        trigger_kwargs: dict,
    ) -> None:
        if name in self.jobs:
            raise ValueError(f"Duplicate job name: {name}")
        trigger_desc = f"{trigger_type}({', '.join(f'{k}={v}' for k, v in trigger_kwargs.items())})"
        self.jobs[name] = JobInfo(name=name, trigger=trigger_desc, func_qualname=f"{func.__module__}.{func.__qualname__}")
        self._funcs[name] = func
        self.scheduler.add_job(self._invoke, trigger=trigger_type, id=name, args=[name], **trigger_kwargs)

    async def _invoke(self, name: str) -> None:
        func = self._funcs[name]
        started = datetime.now(timezone.utc)
        run = JobRun(started_at=started.isoformat(), ended_at=None, status="running", duration_ms=None, error=None)
        self.jobs[name].history.append(run)
        try:
            result = func()
            if asyncio.iscoroutine(result):
                await result
            ended = datetime.now(timezone.utc)
            run.ended_at = ended.isoformat()
            run.duration_ms = int((ended - started).total_seconds() * 1000)
            run.status = "success"
            for hook in self._on_completed:
                try:
                    hook(name)
                except Exception:
                    pass
        except BaseException as e:
            ended = datetime.now(timezone.utc)
            run.ended_at = ended.isoformat()
            run.duration_ms = int((ended - started).total_seconds() * 1000)
            run.status = "failed"
            run.error = traceback.format_exc()
            for hook in self._on_failed:
                try:
                    hook(name, e)
                except Exception:
                    pass
