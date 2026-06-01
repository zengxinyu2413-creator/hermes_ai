"""Tests for SeenStore Protocol + InMemoryStore + FileStore — CX3~CX7."""

from __future__ import annotations

from pathlib import Path

import pytest
from nautilus_trader.model.identifiers import ClientOrderId

from hermes.execution.order_id import OrderIdFactory
from hermes.execution.seen_store import FileStore, InMemoryStore, SeenStore


# ---------------------------------------------------------------------------
# CX4 — InMemoryStore: zero disk, zero network
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    def test_cx4_empty_load(self):
        store = InMemoryStore()
        assert store.load() == set()

    def test_cx4_add_and_load(self):
        store = InMemoryStore()
        store.add("ID-A")
        store.add("ID-B")
        assert store.load() == {"ID-A", "ID-B"}

    def test_cx4_load_returns_copy(self):
        store = InMemoryStore()
        store.add("ID-A")
        snapshot = store.load()
        snapshot.add("ID-INTRUDER")
        assert "ID-INTRUDER" not in store.load()

    def test_cx4_protocol_satisfied(self):
        assert isinstance(InMemoryStore(), SeenStore)


# ---------------------------------------------------------------------------
# CX5 — FileStore roundtrip via tmp_path
# ---------------------------------------------------------------------------


class TestFileStore:
    def test_cx5_roundtrip(self, tmp_path: Path):
        store_path = tmp_path / "seen.txt"
        store_a = FileStore(store_path)
        ids = {f"HRM-{i}-abc" for i in range(10)}
        for oid in ids:
            store_a.add(oid)

        store_b = FileStore(store_path)
        assert store_b.load() == ids

    def test_cx5_missing_file_returns_empty(self, tmp_path: Path):
        store = FileStore(tmp_path / "nonexistent.txt")
        assert store.load() == set()

    def test_cx5_empty_lines_ignored(self, tmp_path: Path):
        p = tmp_path / "seen.txt"
        p.write_text("ID-1\n\nID-2\n\n", encoding="utf-8")
        assert FileStore(p).load() == {"ID-1", "ID-2"}

    def test_cx5_no_workspace_residual(self, tmp_path: Path):
        store_path = tmp_path / "seen.txt"
        store = FileStore(store_path)
        store.add("HRM-999-xyz")
        # file exists inside tmp_path only — tmp_path is pytest-managed, not workspace
        assert store_path.exists()
        assert not Path("seen.txt").exists()

    def test_cx5_protocol_satisfied(self, tmp_path: Path):
        assert isinstance(FileStore(tmp_path / "f.txt"), SeenStore)


# ---------------------------------------------------------------------------
# CX3 — Cross-restart idempotent roundtrip (simulated via two factory instances)
# ---------------------------------------------------------------------------


class TestCrossRestartRoundtrip:
    def test_cx3_factory_b_recognises_factory_a_ids(self, tmp_path: Path):
        store_path = tmp_path / "seen.txt"
        factory_a = OrderIdFactory(store=FileStore(store_path))
        ids = [factory_a.generate() for _ in range(5)]

        factory_b = OrderIdFactory(store=FileStore(store_path))
        for coid in ids:
            assert factory_b.is_seen(coid), f"{coid.value!r} not found after reload"

    def test_cx3_factory_b_does_not_see_new_ids(self, tmp_path: Path):
        store_path = tmp_path / "seen.txt"
        factory_a = OrderIdFactory(store=FileStore(store_path))
        factory_a.generate()

        factory_b = OrderIdFactory(store=FileStore(store_path))
        fresh = ClientOrderId("HRM-0-notpersisted")
        assert not factory_b.is_seen(fresh)

    def test_cx3_register_also_persists(self, tmp_path: Path):
        store_path = tmp_path / "seen.txt"
        factory_a = OrderIdFactory(store=FileStore(store_path))
        external = ClientOrderId("EXT-0-registeredexternally")
        factory_a.register(external)

        factory_b = OrderIdFactory(store=FileStore(store_path))
        assert factory_b.is_seen(external)


# ---------------------------------------------------------------------------
# CX6 — Idempotent semantics: first-seen non-dup / second-seen dup / off-by-one
# ---------------------------------------------------------------------------


class TestIdempotentSemantics:
    def test_cx6_first_seen_not_dup(self):
        factory = OrderIdFactory(store=InMemoryStore())
        coid = factory.generate()
        # is_seen returns True for first-generated (not "dup", just seen)
        assert factory.is_seen(coid)

    def test_cx6_second_seen_is_dup(self):
        factory = OrderIdFactory(store=InMemoryStore())
        coid = factory.generate()
        # Registering again: store.add called twice, still in seen
        factory.register(coid)
        assert factory.is_seen(coid)

    def test_cx6_off_by_one_unseen_id_is_false(self):
        factory = OrderIdFactory(store=InMemoryStore())
        factory.generate()
        not_registered = ClientOrderId("HRM-0-offbyone")
        assert not factory.is_seen(not_registered)

    def test_cx6_none_store_behaviour_identical_to_baseline(self):
        """CX1/CX6: store=None must match pre-store baseline byte-for-byte."""
        factory = OrderIdFactory()  # no store arg
        coid = factory.generate()
        assert factory.is_seen(coid)
        assert not factory.is_seen(ClientOrderId("HRM-0-neverregistered"))

    def test_cx6_seen_seed_still_works_with_store(self):
        """CX6: existing 'seen' seed param unaffected by adding store param."""
        store = InMemoryStore()
        factory = OrderIdFactory(seen={"SEED-1"}, store=store)
        assert factory.is_seen(ClientOrderId("SEED-1"))


# ---------------------------------------------------------------------------
# CX7 — LC-EXEC-5 documentation check (static — ensures comment not deleted)
# ---------------------------------------------------------------------------


class TestLC5Documentation:
    def test_cx7_lc_exec5_in_seen_store_module(self):
        import hermes.execution.seen_store as mod

        src = mod.__doc__ or ""
        assert "LC-EXEC-5" in src, "LC-EXEC-5 documentation missing from seen_store module"

    def test_cx7_filestore_class_doc_mentions_lc_exec5(self):
        from hermes.execution.seen_store import FileStore as FS

        doc = FS.__doc__ or ""
        assert "LC-EXEC-5" in doc, "FileStore docstring must document LC-EXEC-5"
