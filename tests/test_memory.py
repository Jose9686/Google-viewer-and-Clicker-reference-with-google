"""
Memory tests -- the "read & remember" store. All offline, no browser.

Covers learning from text (sentence chunking + dedupe), BM25 recall (the right
note wins, distinctive words drive the match, stemming bridges singular/plural),
cross-source answers, empty recall, and save/load persistence.
"""

import os
import tempfile

from _helpers import fixtures_dir  # noqa: F401,E402  (adds repo to sys.path)

from google_agent.memory import Memory


PHOTO_L1 = "Photosynthesis is how green plants convert sunlight into energy. It happens in the leaves."
PHOTO_L2 = "Photosynthesis needs carbon dioxide, water and light. It produces glucose and oxygen."
PHOTO_L3 = "The reaction happens inside tiny structures called chloroplasts."


def _stocked():
    m = Memory()
    m.learn_page("http://c/lesson1", "Lesson 1", PHOTO_L1)
    m.learn_page("http://c/lesson2", "Lesson 2", PHOTO_L2)
    m.learn_page("http://c/lesson3", "Lesson 3", PHOTO_L3)
    return m


def test_learn_chunks_into_sentences():
    m = Memory()
    added = m.learn_page("u", "T", PHOTO_L2)
    assert added == 2                      # two sentences
    assert len(m) == 2
    assert all(n.source_url == "u" for n in m.notes)


def test_learn_skips_short_fragments():
    m = Memory(min_words=4)
    added = m.learn_text("Next. Go. This sentence is definitely long enough to keep.")
    assert added == 1                      # only the long sentence survives


def test_dedupe_same_note_from_same_source():
    m = Memory()
    m.learn_page("u", "T", "This exact sentence should only be stored once here.")
    m.learn_page("u", "T", "This exact sentence should only be stored once here.")
    assert len(m) == 1


def test_recall_surfaces_the_right_note():
    m = _stocked()
    top = m.recall("what does photosynthesis produce", k=1)
    assert top and "glucose" in top[0].note.text.lower()


def test_recall_stemming_matches_singular_plural():
    m = Memory()
    m.learn_text("The plant absorbs many nutrients from the soil each day.")
    # query uses singular "nutrient"; note has plural "nutrients".
    top = m.recall("nutrient absorbed by plant", k=1)
    assert top, "stemming should let 'nutrient' match 'nutrients'"


def test_recall_ranks_distinctive_terms_higher():
    m = _stocked()
    # "chloroplasts" is unique to lesson 3 -> that note must win.
    top = m.recall("chloroplasts", k=1)
    assert top and "chloroplasts" in top[0].note.text.lower()


def test_answer_reports_sources_and_corroboration():
    m = _stocked()
    ans = m.answer("what does photosynthesis produce")
    assert ans.recalls
    assert ans.corroborating_sources >= 1
    assert ans.sources


def test_recall_empty_when_unknown_topic():
    m = _stocked()
    assert m.recall("quantum entanglement of black holes") == []
    ans = m.answer("quantum entanglement of black holes")
    assert "haven't learned" in ans.text.lower()


def test_save_and_load_roundtrip():
    m = _stocked()
    path = os.path.join(tempfile.gettempdir(), "mem_roundtrip_test.json")
    try:
        m.save(path)
        loaded = Memory.load(path)
        assert len(loaded) == len(m)
        assert loaded.sources() == m.sources()
        # recall still works after reload
        top = loaded.recall("glucose and oxygen", k=1)
        assert top and "glucose" in top[0].note.text.lower()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_load_missing_file_is_empty_not_error():
    loaded = Memory.load(os.path.join(tempfile.gettempdir(), "does_not_exist_xyz.json"))
    assert len(loaded) == 0


if __name__ == "__main__":
    from _run import run_module
    run_module(globals())
