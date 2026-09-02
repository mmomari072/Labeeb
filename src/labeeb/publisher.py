"""
Pluggable EventPublisher and LiveObserver API for non-blocking simulation lifecycle events.
Supports JSONL streaming, disabled/offline mode, bounded async failure isolation,
sensitive data redaction, in-memory ring buffering with replay, and live observers.
"""

import collections
import copy
import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Union

from .exceptions import LabeebError

logger = logging.getLogger(__name__)


class PublisherError(LabeebError):
    """Raised when an event publisher operation fails unrecoverably."""


class LiveObserver:
    """
    Non-blocking live variable and lifecycle observer hook.
    Guarantees that observer failures or long plotting tasks never interrupt
    or mutate simulation execution.
    """

    def __init__(self, callback: Callable[[Dict[str, Any]], Any], name: Optional[str] = None) -> None:
        self.callback = callback
        self.name = name or getattr(callback, "__name__", "live_observer")

    def notify(self, event: Dict[str, Any]) -> None:
        """Deliver an event snapshot to the observer with complete failure isolation."""
        try:
            # Pass a deepcopy to ensure observers cannot mutate event payloads or simulation data
            isolated_event = copy.deepcopy(event)
            if hasattr(self.callback, "notify") and callable(self.callback.notify):
                self.callback.notify(isolated_event)
            elif callable(self.callback):
                self.callback(isolated_event)
        except Exception as exc:
            logger.warning("LiveObserver '%s' raised an exception: %s", self.name, exc)


class EventPublisher(ABC):
    """
    Abstract Base Class for simulation event publishers.
    """

    def __init__(
        self,
        enabled: bool = True,
        max_buffer_size: int = 1000,
        redact_keys: Optional[Sequence[str]] = None,
    ) -> None:
        self.enabled: bool = enabled
        self.max_buffer_size: int = max(1, max_buffer_size)
        self.redact_keys: set = set(redact_keys) if redact_keys else set()
        self._buffer: Deque[Dict[str, Any]] = collections.deque(maxlen=self.max_buffer_size)
        self._observers: List[Any] = []
        self._lock = threading.RLock()

    def add_observer(self, observer: Any) -> "EventPublisher":
        """Attach a live observer to receive published events."""
        with self._lock:
            if isinstance(observer, LiveObserver):
                obs = observer
            elif hasattr(observer, "notify") and callable(observer.notify):
                obs = observer
            else:
                obs = LiveObserver(observer)
            if obs not in self._observers:
                self._observers.append(obs)
        return self

    def _redact(self, data: Any) -> Any:
        """Recursively redact configured sensitive keys."""
        if not self.redact_keys:
            return data
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if k in self.redact_keys:
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = self._redact(v)
            return redacted
        elif isinstance(data, list):
            return [self._redact(item) for item in data]
        return data

    def _normalize_event(self, event: Any) -> Dict[str, Any]:
        """Convert ExecutionEvent or dictionary into a normalized JSON-compatible dict."""
        if hasattr(event, "to_dict") and callable(event.to_dict):
            record = event.to_dict()
        elif isinstance(event, dict):
            record = copy.deepcopy(event)
        else:
            record = {"raw_event": str(event)}

        if self.redact_keys:
            record = self._redact(record)
        return record

    def publish(self, event: Any) -> None:
        """
        Publish an event record. Bounded failure isolation ensures this call
        never raises exceptions to the caller.
        """
        if not self.enabled:
            return

        try:
            record = self._normalize_event(event)
            with self._lock:
                self._buffer.append(record)
                observers = list(self._observers)

            # Dispatch to live observers
            for observer in observers:
                observer.notify(record)

            self._publish_impl(record)
        except Exception as exc:
            logger.warning("EventPublisher failed to publish event: %s", exc)

    @abstractmethod
    def _publish_impl(self, record: Dict[str, Any]) -> None:
        """Subclass implementation for backend event output."""

    def get_buffered_events(self) -> List[Dict[str, Any]]:
        """Return a snapshot list of currently buffered events."""
        with self._lock:
            return list(self._buffer)

    def replay(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Replay all buffered events to a target callback."""
        events = self.get_buffered_events()
        for evt in events:
            try:
                callback(copy.deepcopy(evt))
            except Exception as exc:
                logger.warning("Replay callback raised exception: %s", exc)

    def flush(self) -> None:
        """Flush any pending events to storage."""

    def close(self) -> None:
        """Clean up publisher resources."""
        self.flush()


class NullEventPublisher(EventPublisher):
    """No-op publisher for offline/disabled mode."""

    def __init__(self) -> None:
        super().__init__(enabled=False, max_buffer_size=1)

    def _publish_impl(self, record: Dict[str, Any]) -> None:
        pass


class JsonlEventPublisher(EventPublisher):
    """
    Appends structured events to a JSONL file with thread safety and directory creation.
    """

    def __init__(
        self,
        path: Union[str, Path],
        enabled: bool = True,
        max_buffer_size: int = 1000,
        redact_keys: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(enabled=enabled, max_buffer_size=max_buffer_size, redact_keys=redact_keys)
        self.path: Path = Path(path)
        self._file_lock = threading.Lock()

    def _publish_impl(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, sort_keys=True)
            with self._file_lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as exc:
            logger.warning("JsonlEventPublisher failed to write to '%s': %s", self.path, exc)


class CompositeEventPublisher(EventPublisher):
    """Dispatches events across multiple child publishers with failure isolation."""

    def __init__(
        self,
        publishers: Sequence[EventPublisher],
        enabled: bool = True,
        max_buffer_size: int = 1000,
        redact_keys: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(enabled=enabled, max_buffer_size=max_buffer_size, redact_keys=redact_keys)
        self.publishers: List[EventPublisher] = list(publishers)

    def _publish_impl(self, record: Dict[str, Any]) -> None:
        for pub in self.publishers:
            try:
                pub.publish(record)
            except Exception as exc:
                logger.warning("CompositeEventPublisher child raised exception: %s", exc)

    def flush(self) -> None:
        for pub in self.publishers:
            try:
                pub.flush()
            except Exception:
                pass

    def close(self) -> None:
        for pub in self.publishers:
            try:
                pub.close()
            except Exception:
                pass


class WebSocketEventPublisher(EventPublisher):
    """
    Optional WebSocket event transport adapter.
    Publishes streaming lifecycle and execution events to a WebSocket endpoint
    asynchronously with bounded buffering, failure isolation, and reconnection support.
    """

    def __init__(
        self,
        url: str,
        enabled: bool = True,
        max_buffer_size: int = 1000,
        redact_keys: Optional[Sequence[str]] = None,
        reconnect_interval_seconds: float = 2.0,
        timeout: float = 2.0,
        transport_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        super().__init__(enabled=enabled, max_buffer_size=max_buffer_size, redact_keys=redact_keys)
        import queue

        self.url: str = url
        self.reconnect_interval_seconds: float = reconnect_interval_seconds
        self.timeout: float = timeout
        self.transport_factory = transport_factory
        self._transport: Optional[Any] = None
        self._queue: queue.Queue = queue.Queue(maxsize=self.max_buffer_size)
        self._running: bool = False
        self._worker_thread: Optional[threading.Thread] = None

        if self.enabled:
            self._start_worker()

    def _start_worker(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="WebSocketEventPublisherWorker"
        )
        self._worker_thread.start()

    def _get_transport(self) -> Optional[Any]:
        if self._transport is not None:
            return self._transport
        if self.transport_factory is not None:
            try:
                self._transport = self.transport_factory(self.url)
                return self._transport
            except Exception as exc:
                logger.debug("WebSocket transport factory failed: %s", exc)
                return None
        return None

    def _worker_loop(self) -> None:
        import queue

        while self._running:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                transport = self._get_transport()
                if transport is not None and hasattr(transport, "send"):
                    msg = json.dumps(item, sort_keys=True)
                    transport.send(msg)
            except Exception as exc:
                logger.debug("WebSocket publish failed: %s", exc)
                self._transport = None
            finally:
                self._queue.task_done()

    def _publish_impl(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        import queue

        try:
            self._queue.put_nowait(record)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(record)
            except Exception:
                pass

    def flush(self) -> None:
        try:
            self._queue.join()
        except Exception:
            pass

    def close(self) -> None:
        self._running = False
        if self._transport is not None and hasattr(self._transport, "close"):
            try:
                self._transport.close()
            except Exception:
                pass
        self._transport = None


class RedisStreamEventPublisher(EventPublisher):
    """
    Optional Redis Streams event transport adapter.
    Publishes streaming lifecycle and execution events to a Redis Stream via XADD
    asynchronously with non-blocking queue dispatch, configurable socket timeouts,
    connection failure isolation, dependency safety, and bounded ring buffering.
    """

    def __init__(
        self,
        stream_key: str = "labeeb:events",
        url: str = "redis://localhost:6379/0",
        enabled: bool = True,
        max_buffer_size: int = 1000,
        maxlen: Optional[int] = None,
        redact_keys: Optional[Sequence[str]] = None,
        socket_timeout: float = 1.0,
        socket_connect_timeout: float = 1.0,
        client_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        super().__init__(enabled=enabled, max_buffer_size=max_buffer_size, redact_keys=redact_keys)
        import queue

        self.stream_key: str = stream_key
        self.url: str = url
        self.maxlen: Optional[int] = maxlen
        self.socket_timeout: float = socket_timeout
        self.socket_connect_timeout: float = socket_connect_timeout
        self.client_factory = client_factory
        self._client: Optional[Any] = None
        self._queue: queue.Queue = queue.Queue(maxsize=self.max_buffer_size)
        self._running: bool = False
        self._worker_thread: Optional[threading.Thread] = None

        if self.enabled:
            self._start_worker()

    def _start_worker(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="RedisStreamEventPublisherWorker"
        )
        self._worker_thread.start()

    def _get_client(self) -> Optional[Any]:
        if self._client is not None:
            return self._client
        if self.client_factory is not None:
            try:
                self._client = self.client_factory(self.url)
                return self._client
            except Exception as exc:
                logger.debug("Redis client factory failed: %s", exc)
                return None
        try:
            import redis

            self._client = redis.from_url(
                self.url,
                socket_timeout=self.socket_timeout,
                socket_connect_timeout=self.socket_connect_timeout,
            )
            return self._client
        except ImportError:
            logger.debug("redis-py is not installed; skipping Redis stream publish.")
            return None
        except Exception as exc:
            logger.debug("Redis connection to '%s' failed: %s", self.url, exc)
            return None

    def _worker_loop(self) -> None:
        import queue

        while self._running:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                client = self._get_client()
                if client is not None and hasattr(client, "xadd"):
                    payload = json.dumps(item, sort_keys=True)
                    kwargs: Dict[str, Any] = {"maxlen": self.maxlen} if self.maxlen is not None else {}
                    client.xadd(self.stream_key, {"payload": payload}, **kwargs)
            except Exception as exc:
                logger.debug("RedisStreamEventPublisher XADD worker failed: %s", exc)
                self._client = None
            finally:
                self._queue.task_done()

    def _publish_impl(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        import queue

        try:
            self._queue.put_nowait(record)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(record)
            except Exception:
                pass

    def flush(self) -> None:
        try:
            self._queue.join()
        except Exception:
            pass

    def close(self) -> None:
        self._running = False
        if self._client is not None and hasattr(self._client, "close"):
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
