"""Verification suite for a from-scratch BND4 parser and writer.

Expected module: ``bnd4.py`` importable from the dataset root, exposing:

    Bnd4ParseError
    parse_header(data: bytes) -> dict
    parse_entries(data: bytes, header: dict) -> list[dict]
    build_binary(header: dict, entries: list[dict]) -> bytes

``build_binary`` must serialize the supplied header/entries, not return a
cached copy of the file that was parsed.  Header and entry dictionaries may
contain any additional keys the implementation needs.

Required keys (the only ones this suite demands):
    header["entry_count"]   int
    entry["name"]           str
    entry["data"]           bytes

Optional keys.  If the implementation exposes a key under one of these names,
it is checked for consistency; if it uses other names, nothing is checked:
    header["entry_struct_size"], header["format_flags"]   equal across real files
    entry["comp_size"]      int, must equal len(entry["data"])
    entry["uncomp_size"]    int, kept in step with the payload when mutated
    entry["data_offset"]    int, data range must lie inside the file
    entry["name_offset"]    int, must lie inside the file

Rules every test follows:
    * No format values (header size, field offsets, flag bits, encodings,
      magic value, path conventions) are hardcoded here.
    * Invalid inputs are derived from valid samples by truncating or flipping
      bytes, so each one differs from a valid file in exactly one way.
    * Invalid input must raise ``Bnd4ParseError`` and nothing else.
    * Nothing is skipped; a missing corpus is a hard error.
"""

import os
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DATASET = _HERE.parent
sys.path.insert(0, str(_DATASET))

from bnd4 import (  # noqa: E402
    Bnd4ParseError,
    build_binary,
    parse_entries,
    parse_header,
)

_CORPUS = Path(os.environ.get("BND4_DATA_DIR", _DATASET))
_SMALL_SAMPLE_LIMIT = 1024


def _require(items, what):
    if not items:
        raise RuntimeError(f"No {what} found in {_CORPUS}; refusing to run vacuously.")
    return items


VALID_SAMPLES = _require(sorted((_CORPUS / "hex_samples").glob("*.bin")), "binary samples")
REAL_FILES = _require(sorted((_CORPUS / "files").glob("*.bin")), "real game files")
SMALL_SAMPLES = _require(
    [p for p in VALID_SAMPLES if p.stat().st_size <= _SMALL_SAMPLE_LIMIT],
    f"samples of at most {_SMALL_SAMPLE_LIMIT} bytes",
)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _parse(data):
    header = parse_header(data)
    return header, parse_entries(data, header)


def _content(data):
    """The format-independent meaning of an archive."""
    header, entries = _parse(data)
    return header["entry_count"], [(e["name"], e["data"]) for e in entries]


def _assert_bytes_equal(original, rebuilt):
    if original == rebuilt:
        return
    limit = min(len(original), len(rebuilt))
    first = next((i for i in range(limit) if original[i] != rebuilt[i]), limit)
    raise AssertionError(
        "Round-trip mismatch: "
        f"original={len(original)} bytes, rebuilt={len(rebuilt)} bytes, "
        f"first difference at offset 0x{first:02x}"
    )


def _set_payload(entry, payload):
    entry["data"] = payload
    for key in ("comp_size", "uncomp_size"):
        if entry.get(key) is not None:
            entry[key] = len(payload)


def _check_entries(data, header, entries):
    """Invariants any successfully parsed archive must satisfy."""
    assert isinstance(header["entry_count"], int)
    assert header["entry_count"] == len(entries)

    for i, entry in enumerate(entries):
        name = entry["name"]
        assert isinstance(name, str), f"entry {i}: name is not a string"
        assert "\x00" not in name, f"entry {i}: name contains a NUL"

        payload = entry["data"]
        assert isinstance(payload, bytes), f"entry {i}: data is not bytes"

        comp_size = entry.get("comp_size")
        if comp_size is not None:
            assert isinstance(comp_size, int) and comp_size >= 0
            assert len(payload) == comp_size, (
                f"entry {i}: data is {len(payload)} bytes, comp_size says {comp_size}"
            )

        offset = entry.get("data_offset")
        if offset is not None:
            assert isinstance(offset, int) and offset >= 0
            assert offset + len(payload) <= len(data), (
                f"entry {i}: data range 0x{offset:x}+{len(payload)} exceeds "
                f"{len(data):#x} byte file"
            )

        name_offset = entry.get("name_offset")
        if name_offset is not None:
            assert isinstance(name_offset, int)
            assert 0 <= name_offset < len(data), (
                f"entry {i}: name_offset 0x{name_offset:x} is outside the file"
            )


def _parse_hex_dump(path):
    """Convert an xxd/hexdump-style text dump back into raw bytes."""
    raw = bytearray()
    for line in Path(path).read_text().splitlines():
        line = line.split("|", 1)[0].rstrip()
        match = re.match(r"^\s*[0-9a-fA-F]+:?\s+(.*)$", line)
        if not match:
            continue
        for token in match.group(1).split():
            if re.fullmatch(r"[0-9a-fA-F]+", token) and len(token) % 2 == 0:
                raw.extend(bytes.fromhex(token))
    return bytes(raw)


def _first_with_entries():
    for path in VALID_SAMPLES:
        data = _read(path)
        header, entries = _parse(data)
        if entries:
            return path, data, header, entries
    raise AssertionError("no sample archive contains any entries")


class TestCorpus:
    def test_some_sample_has_entries(self):
        """Guards the mutation tests below against passing on empty archives."""
        _first_with_entries()


class TestRoundTrip:
    """Parse and rebuild real data byte-for-byte using the candidate writer."""

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_roundtrip_samples(self, path):
        original = _read(path)
        header, entries = _parse(original)
        _assert_bytes_equal(original, build_binary(header, entries))

    @pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
    def test_roundtrip_real_game_files(self, path):
        original = _read(path)
        header, entries = _parse(original)
        _assert_bytes_equal(original, build_binary(header, entries))

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_rebuilt_output_is_a_fixed_point(self, path):
        original = _read(path)
        header, entries = _parse(original)
        rebuilt = build_binary(header, entries)
        assert _content(rebuilt) == _content(original)

        rebuilt_header, rebuilt_entries = _parse(rebuilt)
        _assert_bytes_equal(rebuilt, build_binary(rebuilt_header, rebuilt_entries))


class TestWriterUsesItsInput:
    """A writer that merely returns the bytes it parsed must fail these."""

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_renamed_entry(self, path):
        original = _read(path)
        header, entries = _parse(original)
        if not entries:
            return
        before = _content(original)[1]

        mutated = entries[0]["name"] + "_roundtrip_mutation"
        entries[0]["name"] = mutated
        rebuilt = build_binary(header, entries)
        assert rebuilt != original, "writer ignored the mutated entry name"

        names_and_data = _content(rebuilt)[1]
        assert names_and_data[0] == (mutated, before[0][1])
        assert names_and_data[1:] == before[1:]

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_replaced_payload(self, path):
        original = _read(path)
        header, entries = _parse(original)
        index = next((i for i, e in enumerate(entries) if e["data"]), None)
        if index is None:
            return
        before = _content(original)[1]

        payload = b"round-trip mutation payload\x00\xff"
        _set_payload(entries[index], payload)
        rebuilt = build_binary(header, entries)
        assert rebuilt != original, "writer ignored the mutated entry data"

        after = _content(rebuilt)[1]
        assert after[index] == (before[index][0], payload)
        assert after[:index] == before[:index]
        assert after[index + 1:] == before[index + 1:]

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_removed_entry(self, path):
        original = _read(path)
        header, entries = _parse(original)
        if not entries:
            return
        before = _content(original)[1]

        entries = entries[:-1]
        header["entry_count"] = len(entries)
        rebuilt = build_binary(header, entries)

        count, after = _content(rebuilt)
        assert count == len(before) - 1
        assert after == before[:-1]

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_added_entry(self, path):
        original = _read(path)
        header, entries = _parse(original)
        if not entries:
            return
        before = _content(original)[1]

        added = dict(entries[-1])
        added["name"] = entries[-1]["name"] + "_added"
        _set_payload(added, b"added entry payload")
        entries.append(added)
        header["entry_count"] = len(entries)
        rebuilt = build_binary(header, entries)

        count, after = _content(rebuilt)
        assert count == len(before) + 1
        assert after == before + [(added["name"], b"added entry payload")]

    def test_zero_entry_archive_from_a_valid_header(self):
        _, original, header, _ = _first_with_entries()
        header["entry_count"] = 0
        rebuilt = build_binary(header, [])
        assert rebuilt != original

        rebuilt_header, rebuilt_entries = _parse(rebuilt)
        assert rebuilt_header["entry_count"] == 0
        assert rebuilt_entries == []
        _assert_bytes_equal(rebuilt, build_binary(rebuilt_header, rebuilt_entries))


class TestStructuralConsistency:
    """Parsed data must be internally consistent with the source bytes."""

    @pytest.mark.parametrize("path", VALID_SAMPLES, ids=lambda p: p.name)
    def test_sample_invariants(self, path):
        data = _read(path)
        header, entries = _parse(data)
        _check_entries(data, header, entries)

    @pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
    def test_real_file_invariants(self, path):
        data = _read(path)
        header, entries = _parse(data)
        _check_entries(data, header, entries)


class TestCrossFileConsistency:
    """All real game archives come from the same format variant."""

    def test_real_files_share_structure(self):
        magics = set()
        key_sets = set()
        shared = {"entry_struct_size": set(), "format_flags": set()}

        for path in REAL_FILES:
            data = _read(path)
            assert len(data) >= 4, f"{path.name}: too small to contain a header"
            magics.add(data[:4])
            header = parse_header(data)
            key_sets.add(frozenset(header))
            for key, values in shared.items():
                if key in header:
                    values.add(header[key])

        assert len(magics) == 1, f"multiple magic values: {magics}"
        assert len(key_sets) == 1, f"headers expose different keys: {key_sets}"
        for key, values in shared.items():
            assert len(values) <= 1, f"multiple {key} values: {values}"


class TestErrorHandling:
    """Invalid input must raise Bnd4ParseError, never a different exception."""

    @pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 8, 16, 32])
    def test_truncated_header_raises(self, size):
        data = _read(VALID_SAMPLES[0])[:size]
        with pytest.raises(Bnd4ParseError):
            parse_header(data)

    def test_bad_magic_raises(self):
        data = bytearray(_read(VALID_SAMPLES[0]))
        data[:4] = b"XXXX"
        with pytest.raises(Bnd4ParseError):
            parse_header(bytes(data))

    def test_truncation_that_loses_a_payload_raises(self):
        """Cutting one byte off the end of the last payload must be detected."""
        _, data, header, entries = _first_with_entries()
        ends = [
            e["data_offset"] + len(e["data"])
            for e in entries
            if e.get("data_offset") is not None and e["data"]
        ]
        if not ends:
            return
        with pytest.raises(Bnd4ParseError):
            _parse(data[:max(ends) - 1])

    @pytest.mark.parametrize("path", SMALL_SAMPLES, ids=lambda p: p.name)
    def test_every_truncation_raises_or_loses_nothing(self, path):
        """Each prefix of a valid file either fails cleanly or means the same thing."""
        original = _read(path)
        expected = _content(original)
        raised = 0
        for length in range(len(original)):
            try:
                result = _content(original[:length])
            except Bnd4ParseError:
                raised += 1
                continue
            except Exception as exc:
                pytest.fail(f"cut at {length}: {type(exc).__name__}: {exc}")
            assert result == expected, f"cut at {length} parsed to different content"
        assert raised > 0, "no truncation was rejected"

    @pytest.mark.parametrize("mask", [0xFF, 0x80], ids=lambda m: f"xor{m:02x}")
    @pytest.mark.parametrize("path", SMALL_SAMPLES, ids=lambda p: p.name)
    def test_every_corrupted_byte_fails_cleanly_or_stays_consistent(self, path, mask):
        """Flipping any one byte must raise Bnd4ParseError or still parse sanely."""
        original = _read(path)
        for index in range(len(original)):
            data = bytearray(original)
            data[index] ^= mask
            data = bytes(data)
            try:
                header, entries = _parse(data)
            except Bnd4ParseError:
                continue
            except Exception as exc:
                pytest.fail(f"byte {index} ^ {mask:#04x}: {type(exc).__name__}: {exc}")
            _check_entries(data, header, entries)


class TestHexDumpConsistency:
    """The textual dump and the raw game file must describe the same bytes."""

    def test_hex_dump_is_a_prefix_of_a_real_file_and_parses_the_same(self):
        raw = _parse_hex_dump(_CORPUS / "hex_samples" / "real_bnd4_header.hex")
        assert raw, "could not decode any bytes from the hex dump"

        matches = [p for p in REAL_FILES if _read_prefix(p, len(raw)) == raw]
        assert matches, "hex dump does not match the beginning of any real game file"

        dumped = parse_header(raw)
        for path in matches:
            assert parse_header(_read(path)) == dumped, path.name


def _read_prefix(path, size):
    with open(path, "rb") as f:
        return f.read(size)
