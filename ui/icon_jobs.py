"""Background focus-icon generation: a small job queue that runs image calls
off the GUI thread and applies the result to the ProjectModel on it.

Why a runner on the GUI thread: the model must request icons EARLY (right
after ids and titles are fixed) and keep building while they render, because
each image takes 10-30 s. ``generate_icons`` therefore returns immediately;
this object owns the queue, keeps at most :data:`MAX_CONCURRENT` workers
alive, and — being a QObject living on the GUI thread — receives the
workers' signals as queued slots, so ``model.update_focus`` (which repaints
the canvas) never runs off-thread. Failures never raise into the GUI: they
become a ``failed`` job the model reads back through ``icon_jobs``.

Why daemon ``threading.Thread`` rather than ``run_in_thread`` (QThread): an
image call can block for a minute, and Qt 6 aborts the whole process
("QThread: Destroyed while thread is still running") if such a thread is
still alive when its owner goes away — i.e. closing the app mid-generation
would crash on exit. A daemon Python thread is simply abandoned at exit; the
worker QObject's signals still queue onto the GUI thread exactly as from a
QThread.
"""
from __future__ import annotations

import base64
import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from core.agent_loop import TransportError
from core.icon_gen import ImageConfig, OpenRouterImages

from .icon_image import EmptyImageError, process_icon

MAX_CONCURRENT = 2
STATES = ("queued", "running", "done", "failed")


def _default_generate(prompt: str, cfg: ImageConfig):
    return OpenRouterImages().generate(prompt, cfg)


class _IconWorker(QObject):
    """One icon: prompt -> image bytes -> keyed 95×85 PNG. Emits exactly one of
    ``done`` / ``failed``, then ``finished``. Never raises off-thread."""

    done = Signal(str, str, object)   # focus_id, base64 PNG, cost_usd | None
    failed = Signal(str, str)         # focus_id, reason
    ended = Signal(str)               # focus_id — lets the runner free the slot
    finished = Signal()

    def __init__(self, focus_id: str, prompt: str, cfg: ImageConfig, generate, process) -> None:
        super().__init__()
        self._focus_id = focus_id
        self._prompt = prompt
        self._cfg = cfg
        self._generate = generate
        self._process = process

    @Slot()
    def run(self) -> None:
        try:
            image = self._generate(self._prompt, self._cfg)
            png = self._process(image.png_bytes)
            cost = getattr(image, "cost_usd", None)
        except TransportError as exc:
            self.failed.emit(self._focus_id, exc.message)
        except EmptyImageError as exc:
            self.failed.emit(self._focus_id, str(exc))
        except Exception as exc:  # defensive — a worker must never die silently
            self.failed.emit(self._focus_id, f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(self._focus_id, base64.b64encode(png).decode("ascii"), cost)
        finally:
            self.ended.emit(self._focus_id)
            self.finished.emit()


class IconJobRunner(QObject):
    """``queue(items, cfg)`` enqueues ``{focus_id, subject, prompt}`` dicts;
    ``status()`` is the ``icon_jobs`` payload. ``generate`` / ``process`` are
    injectable so tests use a fake image source and no network."""

    icon_ready = Signal(str)          # focus_id
    icon_failed = Signal(str, str)    # focus_id, reason
    jobs_changed = Signal()

    def __init__(self, model, parent=None, generate=None, process=None,
                 max_concurrent: int = MAX_CONCURRENT) -> None:
        super().__init__(parent)
        self._model = model
        self._generate = generate or _default_generate
        self._process = process or process_icon
        self._max = max(1, int(max_concurrent))
        self._jobs: dict = {}         # focus_id -> job record (insertion = queue order)
        self._prompts: dict = {}      # focus_id -> prompt (kept out of status())
        self._cfg: "ImageConfig | None" = None
        self._workers: dict = {}      # focus_id -> (worker, thread) while running

    # ----- api -----
    def queue(self, items: list, cfg: ImageConfig) -> list:
        """Enqueue; returns the job records created. A focus that is already
        queued or running is skipped (see ``active_ids``); a finished one is
        re-queued, replacing its old record."""
        self._cfg = cfg
        created = []
        for item in items:
            fid = str(item.get("focus_id") or "")
            if not fid or fid in self.active_ids():
                continue
            job = {"focus_id": fid, "subject": str(item.get("subject") or ""),
                   "state": "queued", "reason": "", "cost_usd": None,
                   "started": None, "finished": None}
            self._jobs.pop(fid, None)
            self._jobs[fid] = job
            self._prompts[fid] = str(item.get("prompt") or "")
            created.append(dict(job))
        self.jobs_changed.emit()
        self._pump()
        return created

    def active_ids(self) -> set:
        return {fid for fid, j in self._jobs.items() if j["state"] in ("queued", "running")}

    def jobs(self) -> list:
        return [dict(j) for j in self._jobs.values()]

    def status(self) -> dict:
        jobs = self.jobs()
        summary = {state: sum(1 for j in jobs if j["state"] == state) for state in STATES}
        cost = sum(j["cost_usd"] for j in jobs if isinstance(j.get("cost_usd"), (int, float)))
        return {"jobs": jobs, "summary": summary, "cost_usd": round(cost, 4)}

    # ----- scheduling -----
    def _pump(self) -> None:
        for fid, job in self._jobs.items():
            if len(self._workers) >= self._max:
                return
            if job["state"] != "queued" or self._cfg is None:
                continue
            self._start(fid, job)

    def _start(self, fid: str, job: dict) -> None:
        job["state"] = "running"
        job["started"] = time.time()
        worker = _IconWorker(fid, self._prompts.get(fid, ""), self._cfg,
                             self._generate, self._process)
        # Bound @Slot methods only: a lambda has no thread affinity and would
        # run on the worker thread, touching the model and starting threads there.
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.ended.connect(self._on_ended)
        thread = threading.Thread(target=worker.run, name=f"icon-{fid}", daemon=True)
        self._workers[fid] = (worker, thread)   # keeps the QObject alive until `ended`
        thread.start()

    # ----- results (GUI thread: queued slots on a GUI-thread QObject) -----
    @Slot(str, str, object)
    def _on_done(self, fid: str, png_b64: str, cost) -> None:
        job = self._jobs.get(fid)
        if job is None:
            return
        job.update(state="done", cost_usd=cost, finished=time.time())
        # Stored exactly like a hand-imported custom icon (base64 PNG); the
        # sprite name is dropped so the exporter emits the generated one.
        self._model.update_focus(fid, iconData=png_b64, icon="")
        self.icon_ready.emit(fid)
        self.jobs_changed.emit()

    @Slot(str, str)
    def _on_failed(self, fid: str, reason: str) -> None:
        job = self._jobs.get(fid)
        if job is None:
            return
        job.update(state="failed", reason=reason, finished=time.time())
        self.icon_failed.emit(fid, reason)
        self.jobs_changed.emit()

    @Slot(str)
    def _on_ended(self, fid: str) -> None:
        self._workers.pop(fid, None)
        self._pump()
