"""Audio cache identity.

The extracted-WAV cache was keyed on the source file's bare stem, so two
different episodes both named `episode.mp3` -- the overwhelmingly common case
for podcast files kept in per-show folders -- shared one cache entry. The
second run hit the reuse check, logged "Reusing cached audio", and transcribed
the *first* episode, producing a complete, confident and entirely wrong set of
clips with no error anywhere.
"""

from __future__ import annotations

from src.providers.audio import cache_key


def _write(path, content: bytes = b"fake media bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestCacheKey:
    def test_same_filename_in_different_folders_does_not_collide(self, tmp_path):
        a = _write(tmp_path / "showA" / "episode.mp3", b"episode from show A")
        b = _write(tmp_path / "showB" / "episode.mp3", b"episode from show B")

        assert a.stem == b.stem, "precondition: the stems are identical"
        assert cache_key(a) != cache_key(b)

    def test_same_file_is_stable_across_calls(self, tmp_path):
        media = _write(tmp_path / "episode.mp3")
        assert cache_key(media) == cache_key(media)

    def test_replacing_a_file_in_place_invalidates_the_key(self, tmp_path):
        media = _write(tmp_path / "episode.mp3", b"the original recording")
        before = cache_key(media)

        # A re-download to the same path is a different recording.
        _write(media, b"a completely different and much longer recording")

        assert cache_key(media) != before

    def test_key_is_filesystem_safe(self, tmp_path):
        media = _write(tmp_path / "Ep 12: Bob's Épisode.mp3")
        key = cache_key(media)
        assert key.isalnum() and key.islower()
