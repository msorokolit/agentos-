"""Short-term memory: in-memory FakeRedis + degraded path."""

from __future__ import annotations

from uuid import uuid4

from memory_svc.short_term import ShortTermStore


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, list] = {}

    def pipeline(self):
        return _Pipe(self)

    def lrange(self, key, start, stop):
        lst = self.store.get(key, [])
        if start < 0:
            start = max(0, len(lst) + start)
        if stop < 0:
            stop = len(lst) + stop
        return lst[start : stop + 1]

    def delete(self, key):
        self.store.pop(key, None)


class _Pipe:
    def __init__(self, p):
        self.p = p
        self.ops = []

    def rpush(self, key, item):
        self.ops.append(("push", key, item))
        return self

    def ltrim(self, key, lo, hi):
        self.ops.append(("trim", key, lo, hi))
        return self

    def expire(self, key, ttl):
        self.ops.append(("exp", key, ttl))
        return self

    def llen(self, key):
        self.ops.append(("len", key))
        return self

    def execute(self):
        out = []
        for op in self.ops:
            if op[0] == "push":
                self.p.store.setdefault(op[1], []).append(op[2])
                out.append(len(self.p.store[op[1]]))
            elif op[0] == "trim":
                _, k, lo, hi = op
                lst = self.p.store.get(k, [])
                if lo < 0:
                    lo = max(0, len(lst) + lo)
                if hi < 0:
                    hi = len(lst) + hi
                self.p.store[k] = lst[lo : hi + 1]
                out.append(True)
            elif op[0] == "exp":
                out.append(True)
            elif op[0] == "len":
                out.append(len(self.p.store.get(op[1], [])))
        return out


def test_noop_when_redis_missing():
    s = ShortTermStore(None)
    ws, sess = uuid4(), uuid4()
    assert s.append(workspace_id=ws, session_id=sess, role="user", content="x") == 0
    assert s.get(workspace_id=ws, session_id=sess) == []
    s.clear(workspace_id=ws, session_id=sess)


def test_append_and_get_with_fake_redis():
    s = ShortTermStore(FakeRedis(), default_ttl=60)
    ws, sess = uuid4(), uuid4()
    s.append(workspace_id=ws, session_id=sess, role="user", content="hi")
    s.append(workspace_id=ws, session_id=sess, role="assistant", content="ho")
    items = s.get(workspace_id=ws, session_id=sess)
    assert [i["role"] for i in items] == ["user", "assistant"]
    assert [i["content"] for i in items] == ["hi", "ho"]


def test_append_caps_messages():
    s = ShortTermStore(FakeRedis(), default_ttl=60)
    ws, sess = uuid4(), uuid4()
    for i in range(10):
        s.append(
            workspace_id=ws,
            session_id=sess,
            role="user",
            content=str(i),
            max_messages=3,
        )
    items = s.get(workspace_id=ws, session_id=sess)
    assert [i["content"] for i in items] == ["7", "8", "9"]
