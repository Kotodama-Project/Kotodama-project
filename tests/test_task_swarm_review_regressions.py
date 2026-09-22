"""Negative review regressions; no real providers or production owner state."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import threading
try:
    import pytest
except ModuleNotFoundError:  # the core unittest gate installs only requirements-ci.txt
    import unittest
    raise unittest.SkipTest("runs under pytest in the required Task swarm validation job (requirements-task-swarm-ci.txt)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from task_swarm.protocol import SwarmError
from task_swarm.payloads import PayloadStore
from task_swarm.transport import PeerTransport
from task_swarm.mcp_server import PeerTools
from test_task_swarm_mcp import _owner
import test_task_swarm_state as state_fixtures


def peers(tmp_path, *, max_pending=16, max_messages=512, payload_store=None):
    owner = _owner(tmp_path)
    clock = lambda: 1_700_000_000.0
    a = PeerTools(owner, 'actor-a', 1, 'invocation-a', clock=clock, payload_store=payload_store)
    a.transport = PeerTransport(a._storage_selection['mailbox'], a.owner.read_binding, a.owner.authorize,
                                clock=clock, max_pending=max_pending, max_messages=max_messages)
    b = PeerTools(owner, 'actor-b', 1, 'invocation-b', clock=clock, transport=a.transport, payload_store=a.payloads)
    return a, b


def payload_files(a):
    return list(a.payloads.payload_root.glob('*.json'))


@pytest.mark.parametrize('outcome', ['needs_data', 'identity_conflict'])
def test_non_candidate_and_legacy_acceptance_replay_are_refused(outcome):
    fixture = state_fixtures.SwarmStateTests(); fixture.setUp()
    try:
        state = fixture.state(); state.create_run(fixture.plan())
        attempt = state.claim('run-demo', 'worker-a')
        state.report(attempt['token'], 'result-a', 'c'*64, outcome, 'runtime-a')
        with pytest.raises(SwarmError, match='NON_CANDIDATE_RESULT'):
            state.accept('run-demo', 'work', 'c'*64, 'verified-a', 'owner')
        with closing(sqlite3.connect(fixture.db)) as db, db:
            assert db.execute("SELECT state FROM jobs WHERE job_id='work'").fetchone()[0] == 'reported'
            # Model an old DB containing a pre-fix invalid accepted row.
            db.execute("UPDATE attempts SET state='accepted' WHERE token=?", (attempt['token'],))
            db.execute("UPDATE jobs SET state='accepted',accepted_digest=?,verification_ref='verified-a' WHERE job_id='work'", ('c'*64,))
        with pytest.raises(SwarmError, match='NON_CANDIDATE_RESULT'):
            state.accept('run-demo', 'work', 'c'*64, 'verified-a', 'owner')
    finally:
        fixture.tearDown()


def test_candidate_acceptance_is_still_idempotent():
    fixture = state_fixtures.SwarmStateTests(); fixture.setUp()
    try:
        state=fixture.state(); state.create_run(fixture.plan()); attempt=state.claim('run-demo','worker-a')
        state.report(attempt['token'],'result-a','c'*64,'candidate','runtime-a')
        first=state.accept('run-demo','work','c'*64,'verified-a','owner')
        assert state.accept('run-demo','work','c'*64,'verified-a','owner') == first
    finally:
        fixture.tearDown()


def test_rejected_sends_and_conflicting_replays_never_add_files(tmp_path):
    a,b=peers(tmp_path,max_pending=1)
    first=a.peer_send('actor-b','accepted content','accepted')
    before={p.name:p.read_bytes() for p in payload_files(a)}
    for i in range(80):
        with pytest.raises(SwarmError,match='BACKPRESSURE'):
            a.peer_send('actor-b',f'rejected unique content {i}',f'rejected-{i}')
    with pytest.raises(SwarmError,match='IDEMPOTENCY_CONFLICT'):
        a.peer_send('actor-b','different body','accepted')
    assert {p.name:p.read_bytes() for p in payload_files(a)} == before
    assert b.peer_receive()['messages'][0]['text']=='accepted content'
    assert a.peer_send('actor-b','accepted content','accepted')['message_id']==first['message_id']


def test_failed_publication_retains_quota_is_not_delivered_and_retries_same_id(tmp_path):
    a,b=peers(tmp_path,max_pending=1); original=a.payloads.put
    def fail(*args): raise SwarmError('PAYLOAD_STORAGE_ERROR','synthetic write failure')
    a.payloads.put=fail
    with pytest.raises(SwarmError,match='PAYLOAD_STORAGE_ERROR'):
        a.peer_send('actor-b','body','retry')
    message=a._message_id('task-1','actor-a','retry')
    assert a.peer_status(message)['state']=='payload_pending'
    assert b.peer_receive()['messages']==[]
    assert payload_files(a)==[]
    with pytest.raises(SwarmError,match='BACKPRESSURE'):
        a.peer_send('actor-b','other','other')
    with closing(sqlite3.connect(a.transport.db_path)) as db, db:
        digest=db.execute('SELECT payload_digest FROM messages WHERE message_id=?',(message,)).fetchone()[0]
    with pytest.raises(SwarmError,match='PAYLOAD_UNAVAILABLE'):
        b.peer_ack(message,digest)
    a.payloads.put=original
    assert a.peer_send('actor-b','body','retry')['message_id']==message
    assert a.peer_status(message)['state']=='stored'
    assert b.peer_receive()['messages'][0]['text']=='body'
    assert len(payload_files(a))==1


def test_crash_after_file_write_has_durable_admission_and_does_not_duplicate(tmp_path):
    a,b=peers(tmp_path); original=a.payloads.put
    def crash(*args):
        original(*args)
        raise SystemExit('synthetic process boundary')
    a.payloads.put=crash
    with pytest.raises(SystemExit): a.peer_send('actor-b','body','crash')
    assert len(payload_files(a))==1
    assert b.peer_receive()['messages']==[]
    # Separate adapter + SQLite connections model a process reopen.
    reopened=PeerTools(a.owner.path if hasattr(a.owner,'path') else tmp_path/'owner.json',
                       'actor-a',1,'invocation-a',clock=lambda:1_700_000_000.0)
    reopened.peer_send('actor-b','body','crash')
    assert len(payload_files(reopened))==1
    assert b.peer_receive()['messages'][0]['text']=='body'


def test_concurrent_unique_sends_cannot_overrun_admission(tmp_path):
    a,b=peers(tmp_path,max_pending=3,max_messages=3)
    def send(i):
        try: return a.peer_send('actor-b',f'body {i}',f'key-{i}')
        except SwarmError as e: return e.code
    with ThreadPoolExecutor(max_workers=12) as pool: results=list(pool.map(send,range(60)))
    assert sum(isinstance(r,dict) for r in results)==3
    assert set(r for r in results if isinstance(r,str)) <= {'BACKPRESSURE','QUOTA_EXCEEDED'}
    assert len(payload_files(a))==3
    assert len(b.peer_receive()['messages'])==3


def test_parallel_replay_publishes_one_immutable_shared_payload(tmp_path):
    a,b=peers(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values=list(pool.map(lambda _:a.peer_send('actor-b','same body','same-key'),range(24)))
    assert len({r['message_id'] for r in values})==1
    assert len(payload_files(a))==1
    assert len(b.peer_receive()['messages'])==1


def test_shared_content_is_not_deleted_by_later_rejection(tmp_path):
    a,b=peers(tmp_path,max_pending=2)
    a.peer_send('actor-b','shared','one'); a.peer_send('actor-b','shared','two')
    assert len(payload_files(a))==1
    with pytest.raises(SwarmError,match='BACKPRESSURE'): a.peer_send('actor-b','shared','three')
    assert [r['text'] for r in b.peer_receive()['messages']]==['shared','shared']


def test_reply_without_ack_does_not_publish_and_pending_reply_is_not_success(tmp_path):
    a,b=peers(tmp_path); first=a.peer_send('actor-b','question','question')
    with pytest.raises(SwarmError,match='MISSING_ACK'): b.peer_reply(first['message_id'],'answer','answer')
    assert len(payload_files(a))==1
    b.peer_ack(first['message_id'],first['payload_digest']); original=b.payloads.put
    def fail(*args): raise SwarmError('PAYLOAD_STORAGE_ERROR','synthetic write failure')
    b.payloads.put=fail
    with pytest.raises(SwarmError): b.peer_reply(first['message_id'],'answer','answer')
    assert a.peer_status(first['message_id'])['state']=='acked'
    assert a.peer_status(first['message_id'])['reply_ids']==[]
    assert a.peer_receive()['messages']==[]
    b.payloads.put=original
    reply=b.peer_reply(first['message_id'],'answer','answer')
    assert a.peer_receive()['messages'][0]['message_id']==reply['message_id']


def test_current_permission_is_rechecked_before_publication(tmp_path):
    a,b=peers(tmp_path); transport=a.transport; original=transport._publish_pending
    def revoke(parsed,publish,*,action):
        owner_file=tmp_path/'owner.json'; document=json.loads(owner_file.read_text())
        document['actors']['actor-a']['peers']=[]; owner_file.write_text(json.dumps(document))
        return original(parsed,publish,action=action)
    transport._publish_pending=revoke
    with pytest.raises(SwarmError): a.peer_send('actor-b','must not publish','revoked')
    assert payload_files(a)==[]


def test_payload_root_limits_are_persistent_and_do_not_erase_shared_content(tmp_path):
    store=PayloadStore(tmp_path/'payloads',max_payloads=1,max_storage_bytes=100)
    first=store.put('body',[])
    assert store.put('body',[])==first
    for reopened in [store,PayloadStore(tmp_path/'payloads')]:
        with pytest.raises(SwarmError,match='PAYLOAD_STORAGE_QUOTA'): reopened.put('other',[])
    assert store.get(*first)['text']=='body'
    with pytest.raises(SwarmError,match='PAYLOAD_LIMIT_CHANGED'):
        PayloadStore(tmp_path/'payloads',max_payloads=2).put('body',[])


def test_payload_budget_does_not_trust_directory_entry_link_counts(tmp_path, monkeypatch):
    # Windows reports st_nlink=0 from DirEntry.stat(); accounting must read the
    # real link count instead of refusing every existing payload file.
    import os as real_os
    from task_swarm import payload_budget as budget
    original_scandir=real_os.scandir
    class Entry:
        def __init__(self, entry): self._entry=entry; self.path=entry.path; self.name=entry.name
        def stat(self, *, follow_symlinks=True):
            info=self._entry.stat(follow_symlinks=follow_symlinks)
            return real_os.stat_result((info.st_mode, 0, 0, 0, info.st_uid, info.st_gid, info.st_size, 0, 0, 0))
    class Entries:
        def __init__(self, path): self._iterator=original_scandir(path)
        def __enter__(self): return (Entry(entry) for entry in self._iterator)
        def __exit__(self, *exc): self._iterator.close()
    monkeypatch.setattr(budget.os, 'scandir', Entries)
    store=PayloadStore(tmp_path/'payloads',max_payloads=2,max_storage_bytes=1000)
    first=store.put('first',[]); second=store.put('second',[])
    assert store.get(*first)['text']=='first' and store.get(*second)['text']=='second'
    with pytest.raises(SwarmError,match='PAYLOAD_STORAGE_QUOTA'): store.put('third',[])


def test_parallel_payload_stores_share_one_capacity_limit(tmp_path):
    root=tmp_path/'payloads'; base=PayloadStore(root,max_payloads=3,max_storage_bytes=1000)
    base.put('seed',[])
    def put(i):
        try: return PayloadStore(root).put(f'body {i}',[])
        except SwarmError as e: return e.code
    with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(put,range(40)))
    assert sum(isinstance(v,tuple) for v in results)==2
    assert len(list(base.payload_root.glob('*.json')))==3


def test_payload_byte_limit_rejects_before_writing(tmp_path):
    raw,_=PayloadStore.canonical_bytes('body',[])
    store=PayloadStore(tmp_path/'payloads',max_payloads=4,max_storage_bytes=len(raw))
    first=store.put('body',[])
    with pytest.raises(SwarmError,match='PAYLOAD_STORAGE_QUOTA'): store.put('larger body',[])
    assert len(list(store.payload_root.glob('*.json')))==1
    assert store.get(*first)['text']=='body'


def test_actual_process_exit_between_payload_and_ready_is_recoverable(tmp_path):
    import os
    import subprocess
    a,b=peers(tmp_path)
    code="""
import os,sys
from task_swarm.mcp_server import PeerTools
p=PeerTools(sys.argv[1],'actor-a',1,'invocation-a',clock=lambda:1_700_000_000.0)
original=p.payloads.put
def crash(*args):
    original(*args)
    os._exit(77)
p.payloads.put=crash
p.peer_send('actor-b','crash fixture','hard-exit')
"""
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path/'owner.json')],
                          env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'runtime')},timeout=10)
    assert result.returncode==77
    assert b.peer_receive()['messages']==[]
    assert len(payload_files(a))==1
    receipt=a.peer_send('actor-b','crash fixture','hard-exit')
    assert receipt['payload_state']=='ready'
    assert len(payload_files(a))==1
    assert b.peer_receive()['messages'][0]['message_id']==receipt['message_id']


def test_legacy_transport_schema_is_migrated_without_reclassifying_old_messages(tmp_path):
    from task_swarm.transport import _SCHEMA
    owner=_owner(tmp_path)
    db=tmp_path/'storage'/'mailbox.sqlite'; db.parent.mkdir(parents=True)
    legacy=_SCHEMA.replace("    payload_state TEXT NOT NULL DEFAULT 'ready' CHECK(payload_state IN ('pending','ready')),\n",'')
    with closing(sqlite3.connect(db)) as conn, conn: conn.executescript(legacy)
    a=PeerTools(owner,'actor-a',1,'invocation-a',clock=lambda:1_700_000_000.0)
    receipt=a.peer_send('actor-b','migration fixture','migration')
    assert receipt['payload_state']=='ready'
    with closing(sqlite3.connect(db)) as conn, conn:
        assert 'payload_state' in {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
