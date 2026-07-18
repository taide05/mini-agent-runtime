from uuid import uuid4

from app.services.session_service import walk_parent_chain, assemble_messages_from_chain


class FakeNode:
    def __init__(self, id, parent_id, role, content):
        self.id = id
        self.parent_id = parent_id
        self.role = role
        self.content = content


class FakeDB:
    def __init__(self, nodes_by_id):
        self._nodes = nodes_by_id

    def query(self, model):
        return self

    def filter(self, condition):
        return self

    def first(self):
        return None

    def all(self):
        return []


def test_assemble_no_parent():
    db = FakeDB({})
    msgs = assemble_messages_from_chain(db, None, "Hello", "You are helpful.")
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "You are helpful."}
    assert msgs[1] == {"role": "user", "content": "Hello"}


def test_assemble_empty_system_prompt():
    db = FakeDB({})
    msgs = assemble_messages_from_chain(db, None, "Hi", "")
    assert len(msgs) == 1
    assert msgs[0] == {"role": "user", "content": "Hi"}
