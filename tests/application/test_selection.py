"""Assert effects and failure recovery through the application interface."""

from types import SimpleNamespace

import pytest

from clashier.application.proxy import ProxyControl
from clashier.errors import ControllerError, OperationError
from clashier.models import Deadline, ProxyGroup, SelectRequest


class Runtime:
    def __init__(self):
        self.selected = "A"
        self.kind = "Selector"
        self.writes = []
        self.error = None
        self.readable = True

    def read_group(self, name):
        if not self.readable:
            raise ControllerError("connection lost")
        return ProxyGroup(name, self.kind, self.selected, ["A", "B"])

    def select(self, group, proxy):
        self.selected = proxy
        self.writes.append(proxy)
        if self.error:
            self.error()


class Memory:
    def __init__(self):
        self.uid = "profile"
        self.selected = "A"
        self.failed = False

    def prepare(self):
        pass

    def profile_uid(self):
        return self.uid

    def save(self, group, name, expected_uid):
        if self.failed:
            raise OperationError("PERSISTENCE_FAILED", "disk is read-only")
        if self.uid != expected_uid:
            raise OperationError("STALE_CONTEXT", "profile changed")
        changed = self.selected != name
        self.selected = name
        return {"status": "saved", "changed": changed}


@pytest.fixture
def operation():
    runtime, memory = Runtime(), Memory()
    session = SimpleNamespace(api=runtime, instance_id="core", deadline=Deadline(5))
    return ProxyControl(session, memory), runtime, memory


def test_profile_failure_reports_live_effect_and_can_be_completed(operation):
    control, runtime, memory = operation
    memory.failed = True
    request = SelectRequest("G", "B", persist=True, if_current="A")
    with pytest.raises(OperationError) as caught:
        control.select(request)
    assert caught.value.code == "PERSISTENCE_FAILED"
    assert caught.value.data["status"] == "partial"
    assert caught.value.data["after"] == "B"
    assert caught.value.data["live_status"] == "verified"
    assert caught.value.needs_reconcile is True
    memory.failed = False
    result = control.select(request)
    assert result["persistence"]["status"] == "saved"
    assert memory.selected == "B"
    assert runtime.writes == ["B"]


def test_unknown_write_result_is_not_reported_as_failure_without_effect(operation):
    control, runtime, memory = operation

    def lost_response():
        runtime.readable = False
        raise ControllerError("read timeout", request_sent=True)

    runtime.error = lost_response
    with pytest.raises(OperationError) as caught:
        control.select(SelectRequest("G", "B", persist=True))
    assert caught.value.code == "OUTCOME_UNKNOWN"
    assert caught.value.data["status"] == "unknown"
    assert caught.value.safe_to_retry is False
    assert caught.value.needs_reconcile is True
    assert runtime.writes == ["B"]
    assert memory.selected == "A"


def test_response_timeout_is_reconciled_with_a_read(operation):
    control, runtime, _ = operation

    def timeout():
        raise ControllerError("read timeout", request_sent=True)

    runtime.error = timeout
    result = control.select(SelectRequest("G", "B"))
    assert result["status"] == "applied"
    assert result["after"] == "B"
    assert runtime.writes == ["B"]


def test_context_and_old_value_are_checked_before_any_write(operation):
    control, runtime, _ = operation
    with pytest.raises(OperationError, match="context changed"):
        control.select(SelectRequest("G", "B", context={"instance_id": "other", "profile_uid": "profile"}))
    with pytest.raises(OperationError) as caught:
        control.select(SelectRequest("G", "B", if_current="old-value"))
    assert caught.value.code == "PRECONDITION_FAILED"
    assert runtime.writes == []


def test_automatic_groups_are_not_treated_as_selectors(operation):
    control, runtime, _ = operation
    runtime.kind = "URLTest"
    with pytest.raises(OperationError) as caught:
        control.select(SelectRequest("G", "B"))
    assert caught.value.code == "UNSUPPORTED_OPERATION"
    assert runtime.writes == []


def test_persist_requires_a_profile_before_put(operation):
    control, runtime, memory = operation
    memory.uid = None
    with pytest.raises(OperationError) as caught:
        control.select(SelectRequest("G", "B", persist=True))
    assert caught.value.code == "UNSUPPORTED_OPERATION"
    assert runtime.writes == []


def test_profile_change_after_put_is_reported_as_partial(operation):
    control, runtime, memory = operation
    runtime.error = lambda: setattr(memory, "uid", "other-profile")
    with pytest.raises(OperationError) as caught:
        control.select(SelectRequest("G", "B", persist=True))
    assert caught.value.code == "PERSISTENCE_FAILED"
    assert caught.value.data["after"] == "B"
    assert memory.selected == "A"
