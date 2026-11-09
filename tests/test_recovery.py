"""reconcile() and the duplicate_proposal_id path, driven by a fake simulator (a kill inside the 'sending' window is too narrow to hit by chance)."""
import pytest

from controller.api import ApiError
from controller.core.engine import Controller


class FakeApi:
    def __init__(self, history=(), approvals=()):
        self.history, self.approvals, self.breakers = list(history), list(approvals), {}
    def get(self, path, **kw):
        return self.history if path.endswith("/config/history") else self.approvals


def _ctl(tmp_path, api):
    c = Controller("http://x", str(tmp_path), log=lambda r: None); c.api = api
    return c


def _sending(c, pid):
    c.st.put_proposal({"proposal_id": pid, "wf": "w", "kind": "caller_id", "status": "sending", "base_version": 1, "created_min": 0,
                       "dims": ["caller_id"], "config": {}, "meta": {}})


def test_reconcile_three_outcomes(tmp_path):
    c = _ctl(tmp_path, FakeApi(history=[{"proposal_id": "applied1"}], approvals=[{"proposal_id": "appr1", "approval_id": "apr_7"}]))
    for pid in ("applied1", "appr1", "lost1"): _sending(c, pid)
    c.reconcile()
    st = {p["proposal_id"]: (p["status"], p["approval_id"]) for p in c.st.proposals()}
    assert st == {"applied1": ("applied_auto", None), "appr1": ("pending_approval", "apr_7"), "lost1": ("abandoned", None)}
    assert c.st.db.execute("select count(*) from audit where kind='recovered'").fetchone()[0] == 3


def test_duplicate_send_resolves_instead_of_failing(tmp_path):
    c = _ctl(tmp_path, FakeApi(approvals=[{"proposal_id": "p", "approval_id": "apr_9"}]))
    _sending(c, "p")
    hit = c._landed({"wf": "w", "proposal_id": "p"})            # what submit() does when POST /approvals answers 409 duplicate_proposal_id
    assert hit == ("pending_approval", "apr_9")
