"""Compose adapters once per command invocation."""

import time
import uuid
from typing import Any, Dict, Optional

from clashier import platforms
from clashier.adapters.discovery import candidates, resolve
from clashier.adapters.mihomo import Mihomo
from clashier.adapters.verge_store import VergeStore
from clashier.application.profiles import ProfileControl
from clashier.application.proxy import ProxyControl
from clashier.models import Deadline, Endpoint


class Bootstrap:
    """Lazy invocation context shared by proxy and management commands."""

    def __init__(self, config_dir: Optional[str] = None, controller: Optional[str] = None,
                 secret: Optional[str] = None, timeout: Optional[float] = None,
                 instance: Optional[str] = None, output: str = "text", no_input: bool = False):
        self._config_dir_opt = config_dir
        self._controller_opt = controller
        self._secret_opt = secret
        self.timeout = 5.0 if timeout is None else timeout
        self.explicit_timeout = timeout is not None
        self.instance = instance
        self.output = output
        self.no_input = no_input
        self.started = time.monotonic()
        self.request_id = uuid.uuid4().hex
        self.deadline = Deadline(self.timeout)
        self._store: Optional[VergeStore] = None
        self._api: Optional[Mihomo] = None
        self._endpoint: Optional[Endpoint] = None
        self._proxy: Optional[ProxyControl] = None
        self._context: Optional[Dict[str, Any]] = None

    @property
    def platform(self) -> str:
        return platforms.platform_name()

    @property
    def store(self) -> VergeStore:
        if self._store is None:
            self._store = VergeStore(platforms.locate_config_dir(self._config_dir_opt))
        return self._store

    def endpoints(self):
        """Collect configured addresses without connecting to them."""
        return candidates(self.store, self._controller_opt, self._secret_opt)

    @property
    def endpoint(self) -> Endpoint:
        if self._endpoint is None:
            self._endpoint = resolve(self.endpoints(), self.deadline, self.instance)
        return self._endpoint

    @property
    def api(self) -> Mihomo:
        if self._api is None:
            target = self.endpoint
            self._api = Mihomo(target.address, target.secret, self.timeout, deadline=self.deadline)
        return self._api

    @property
    def instance_id(self) -> str:
        return self.endpoint.instance_id

    @property
    def proxy(self) -> ProxyControl:
        if self._proxy is None:
            self._proxy = ProxyControl(self, ProfileControl(self))
            self._context = self._proxy.context()
        return self._proxy

    def context(self) -> Optional[Dict[str, Any]]:
        """Return only context already resolved during this invocation."""
        return self._context

    def renew_deadline(self, timeout: Optional[float] = None) -> None:
        """Start a new operation budget after a human prompt."""
        self.deadline = Deadline(self.timeout if timeout is None else timeout)
        if self._api is not None:
            self._api.deadline = self.deadline

    def refresh_runtime(self, *, renew_deadline: bool = True) -> None:
        """Rediscover the controller after the GUI may have replaced its runtime configuration."""
        self.close()
        self._api = None
        self._endpoint = None
        self._proxy = None
        self._context = None
        if renew_deadline:
            self.renew_deadline()

    def close(self) -> None:
        """Release any client created during the invocation."""
        if self._api:
            self._api.close()
