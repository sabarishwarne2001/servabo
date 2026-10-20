"""The garbage-collector pause around a GST recompute or import (Session H): counted, always undone, never turns on a
collector somebody else had switched off."""

from __future__ import annotations

import gc
import threading

import pytest

from app.services.gst.gcpause import collector_paused

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def _restore_collector():
    was = gc.isenabled()
    yield
    gc.enable() if was else gc.disable()


def test_the_collector_is_off_inside_and_back_on_after():
    gc.enable()
    with collector_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_it_comes_back_even_when_the_section_fails():
    gc.enable()
    with pytest.raises(RuntimeError):
        with collector_paused():
            raise RuntimeError("boom")
    assert gc.isenabled()


def test_nested_and_overlapping_sections_turn_it_back_on_only_when_the_last_one_ends():
    gc.enable()
    inside, release, done = threading.Event(), threading.Event(), threading.Event()

    def other():
        with collector_paused():
            inside.set()
            release.wait(5)
        done.set()

    thread = threading.Thread(target=other)
    with collector_paused():
        thread.start()
        inside.wait(5)
        with collector_paused():
            assert not gc.isenabled()
    assert not gc.isenabled()          # the other section is still running
    release.set()
    done.wait(5)
    thread.join(5)
    assert gc.isenabled()


def test_a_collector_that_was_already_off_stays_off():
    gc.disable()
    with collector_paused():
        pass
    assert not gc.isenabled()
