from __future__ import annotations

import os
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from tui.constants import _SUPPORTED_EXTENSIONS


class _DebounceTimer:
    def __init__(self, delay: float, callback):
        self.delay = delay
        self.callback = callback
        self.timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def schedule(self, path: str):
        with self._lock:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self.callback, args=(path,))
            self.timer.daemon = True
            self.timer.start()

    def cancel(self):
        with self._lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None


class FileWatcher:
    def __init__(self, watch_dir: str, on_new_file, on_removed_file):
        self.watch_dir = os.path.realpath(watch_dir)
        self.on_new_file = on_new_file
        self.on_removed_file = on_removed_file
        self._observer = Observer()
        self._handler = _FileHandler(
            self.watch_dir, self._on_new, self._on_removed
        )
        self._seen: set[str] = set()
        self._debounce = _DebounceTimer(2.0, self._emit_new_file)
        self._lock = threading.Lock()
        self._running = False

    def _on_new(self, path: str):
        with self._lock:
            if path in self._seen:
                return
            self._seen.add(path)
        self._debounce.schedule(path)

    def _emit_new_file(self, path: str):
        if os.path.isfile(path):
            self.on_new_file(path)
        else:
            with self._lock:
                self._seen.discard(path)

    def _on_removed(self, path: str):
        with self._lock:
            self._seen.discard(path)
        self.on_removed_file(path)

    def start(self):
        if self._running:
            return
        os.makedirs(self.watch_dir, exist_ok=True)
        self._observer.schedule(self._handler, self.watch_dir, recursive=False)
        self._observer.start()
        self._running = True

    def stop(self):
        if not self._running:
            return
        self._observer.stop()
        self._observer.join()
        self._debounce.cancel()
        self._running = False


class _FileHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: str, on_new_file, on_removed_file):
        self.watch_dir = watch_dir
        self.on_new_file = on_new_file
        self.on_removed_file = on_removed_file

    def _is_ignored(self, name: str) -> bool:
        base = os.path.basename(name)
        if base.startswith(".") or base.startswith("~") or base == "Thumbs.db":
            return True
        _, ext = os.path.splitext(base)
        return ext.lower() not in _SUPPORTED_EXTENSIONS

    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if not self._is_ignored(path):
            self.on_new_file(path)

    def on_moved(self, event):
        if event.is_directory:
            return
        dest = event.dest_path
        src = event.src_path
        if not dest.startswith(self.watch_dir + os.sep) and dest != self.watch_dir:
            self.on_removed_file(src)
        elif not self._is_ignored(dest):
            if src.startswith(self.watch_dir + os.sep):
                self.on_removed_file(src)
            self.on_new_file(dest)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if path.startswith(self.watch_dir + os.sep) or path == self.watch_dir:
            self.on_removed_file(path)
