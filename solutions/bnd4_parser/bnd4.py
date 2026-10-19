"""
Reference BND4 parser and writer. NOT part of the task: never copy this into
the model's workspace. It exists to prove the test suite passes on a correct
implementation (see solutions/README.md).

Layout, as observed in the real files and the synthetic samples:

    0x00  "BND4"
    0x04  8 opaque bytes (0x09 != 0 means big-endian)
    0x0C  i32  entry count
    0x10  i64  opaque (0x40 in game files; the synthetic generator stores other values)
    0x18  8 bytes version string
    0x20  i64  entry struct size, implied by the format byte
    0x28  i64  end of the metadata: either the entry table, or the names/hash table
    0x30  u8   unicode (UTF-16 names, else Shift-JIS)
    0x31  u8   format byte, bit-reversed: 0x02 ids, 0x04|0x08 names,
               0x10 64-bit data offsets, 0x20 uncompressed size present
    0x32  u8   extended (4 = may have a hash table)
    0x33  3 opaque bytes + u32 0x34
    0x38  i64  path hash table offset, 0 if absent

    entry: u32 flags, i32 opaque, i64 comp_size, [i64 uncomp_size],
           u32|i64 data_offset, [i32 id], [u32 name_offset]

Names follow the entry table in entry order. The hash table (if any) follows,
8-aligned: i64 hashes_offset, i32 group_count, u32 opaque, group_count x
(i32 length, i32 first_index), then entry_count x (u32 hash, i32 entry_index)
sorted by group then hash. Payloads follow in entry order; non-empty ones are
aligned to the archive's alignment, empty ones sit at the current position.
"""
import struct

MAGIC = b"BND4"
HEADER_SIZE = 0x40

F_IDS = 0x02
F_NAMES = 0x04 | 0x08
F_LONG_OFFSETS = 0x10
F_UNCOMP = 0x20


class Bnd4ParseError(ValueError):
    pass


def _reverse_bits(b):
    return int(f"{b:08b}"[::-1], 2)


def _entry_size(fmt):
    size = 4 + 4 + 8
    size += 8 if fmt & F_UNCOMP else 0
    size += 8 if fmt & F_LONG_OFFSETS else 4
    size += 4 if fmt & F_IDS else 0
    size += 4 if fmt & F_NAMES else 0
    return size


def _align(pos, alignment):
    return (pos + alignment - 1) // alignment * alignment


def _path_hash(name):
    path = name.lower().replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    h = 0
    for ch in path:
        h = (h * 37 + ord(ch)) & 0xFFFFFFFF
    return h


def _group_count(n):
    def is_prime(p):
        return p >= 2 and all(p % d for d in range(2, int(p ** 0.5) + 1))
    return next(p for p in range(n // 7, 100001) if is_prime(p))


def _hash_table(names, base, order):
    """Serialize the hash table starting at absolute offset base."""
    groups = _group_count(len(names))
    buckets = [[] for _ in range(groups)]
    for i, name in enumerate(names):
        h = _path_hash(name)
        buckets[h % groups].append((h, i))
    table, hashes, index = b"", b"", 0
    for bucket in buckets:
        bucket.sort()
        table += struct.pack(order + "ii", len(bucket), index)
        hashes += b"".join(struct.pack(order + "Ii", h, i) for h, i in bucket)
        index += len(bucket)
    hashes_at = base + 16 + len(table)
    return struct.pack(order + "qiI", hashes_at, groups, 0x00080810) + table + hashes


def _encode_name(name, unicode):
    try:
        return name.encode("utf-16-le" if unicode else "shift_jis") + (b"\0\0" if unicode else b"\0")
    except UnicodeEncodeError as exc:
        raise ValueError(f"cannot encode name {name!r}: {exc}") from None


def _read_name(data, offset, unicode):
    if unicode:
        end = offset
        while True:
            if end + 2 > len(data):
                raise Bnd4ParseError(f"unterminated name at 0x{offset:x}")
            if data[end:end + 2] == b"\0\0":
                break
            end += 2
        raw, enc = data[offset:end], "utf-16-le"
    else:
        end = data.find(b"\0", offset)
        if end < 0:
            raise Bnd4ParseError(f"unterminated name at 0x{offset:x}")
        raw, enc = data[offset:end], "shift_jis"
    try:
        return raw.decode(enc)
    except UnicodeDecodeError as exc:
        raise Bnd4ParseError(f"bad name at 0x{offset:x}: {exc}") from None


def parse_header(data):
    if len(data) < HEADER_SIZE:
        raise Bnd4ParseError(f"{len(data)} bytes is too small for a header")
    if data[:4] != MAGIC:
        raise Bnd4ParseError(f"bad magic {data[:4]!r}")
    order = ">" if data[9] else "<"
    count, unk10, version, struct_size, meta_end = struct.unpack_from(order + "iq8sqq", data, 0x0C)
    unicode, raw_fmt, extended = data[0x30], data[0x31], data[0x32]
    hash_offset, = struct.unpack_from(order + "q", data, 0x38)
    fmt = _reverse_bits(raw_fmt)
    if count < 0:
        raise Bnd4ParseError(f"negative entry count {count}")
    if struct_size != _entry_size(fmt):
        raise Bnd4ParseError(f"entry size {struct_size} does not match format 0x{raw_fmt:02x}")
    if unicode not in (0, 1):
        raise Bnd4ParseError(f"bad unicode flag {unicode}")
    if hash_offset < 0 or meta_end < 0:
        raise Bnd4ParseError("negative offset in header")
    return {
        "entry_count": count,
        "entry_struct_size": struct_size,
        "format_flags": raw_fmt,
        "big_endian": order == ">",
        "unicode": bool(unicode),
        "extended": extended,
        "has_hash_table": hash_offset != 0,
        "version": version,
        "unk04": data[4:12],
        "unk10": unk10,
        "unk33": data[0x33:0x38],
        "meta_end_after_entries": None,  # resolved by parse_entries
        "alignment": None,               # resolved by parse_entries
    }


def parse_entries(data, header):
    order = ">" if header["big_endian"] else "<"
    fmt = _reverse_bits(header["format_flags"])
    count, size = header["entry_count"], header["entry_struct_size"]
    table_end = HEADER_SIZE + count * size
    if table_end > len(data):
        raise Bnd4ParseError(f"{count} entries do not fit in {len(data)} bytes")

    entries = []
    for i in range(count):
        pos = HEADER_SIZE + i * size
        flags, unk04, comp_size = struct.unpack_from(order + "Iiq", data, pos)
        pos += 16
        uncomp_size = None
        if fmt & F_UNCOMP:
            uncomp_size, = struct.unpack_from(order + "q", data, pos)
            pos += 8
        if fmt & F_LONG_OFFSETS:
            data_offset, = struct.unpack_from(order + "q", data, pos)
            pos += 8
        else:
            data_offset, = struct.unpack_from(order + "I", data, pos)
            pos += 4
        entry_id = None
        if fmt & F_IDS:
            entry_id, = struct.unpack_from(order + "i", data, pos)
            pos += 4
        name, name_offset = "", None
        if fmt & F_NAMES:
            name_offset, = struct.unpack_from(order + "I", data, pos)
            if not table_end <= name_offset < len(data):
                raise Bnd4ParseError(f"entry {i}: name offset 0x{name_offset:x} out of range")
            name = _read_name(data, name_offset, header["unicode"])
        if comp_size < 0 or data_offset < 0 or data_offset + comp_size > len(data):
            raise Bnd4ParseError(f"entry {i}: data 0x{data_offset:x}+{comp_size} out of range")
        entries.append({
            "name": name,
            "data": data[data_offset:data_offset + comp_size],
            "flags": flags,
            "unk04": unk04,
            "id": entry_id,
            "comp_size": comp_size,
            "uncomp_size": uncomp_size,
            "data_offset": data_offset,
            "name_offset": name_offset,
        })

    # Layout details the writer needs to reproduce the file exactly.
    offsets = [e["data_offset"] for e in entries if e["data"]]
    alignment = 16
    while alignment > 1 and any(o % alignment for o in offsets):
        alignment //= 2
    meta_end, = struct.unpack_from(order + "q", data, 0x28)
    header["alignment"] = alignment
    header["meta_end_after_entries"] = meta_end == table_end
    return entries


def build_binary(header, entries):
    order = ">" if header["big_endian"] else "<"
    fmt = _reverse_bits(header["format_flags"])
    unicode = header["unicode"]
    alignment = header.get("alignment") or 1
    count = len(entries)
    table_end = HEADER_SIZE + count * _entry_size(fmt)

    names, name_offsets, pos = b"", [], table_end
    if fmt & F_NAMES:
        for e in entries:
            name_offsets.append(pos + len(names))
            names += _encode_name(e["name"], unicode)
    pos = table_end + len(names)

    hash_table, hash_offset = b"", 0
    if header["has_hash_table"]:
        hash_offset = _align(pos, 8)
        hash_table = b"\0" * (hash_offset - pos) + _hash_table(
            [e["name"] for e in entries], hash_offset, order)
    pos += len(hash_table)
    meta_end = table_end if header.get("meta_end_after_entries") else pos

    body, data_offsets = b"", []
    for e in entries:
        payload = e["data"]
        if payload:
            start = _align(pos + len(body), alignment)
            body += b"\0" * (start - pos - len(body))
        data_offsets.append(pos + len(body))
        body += payload

    out = bytearray()
    out += MAGIC + header["unk04"]
    out += struct.pack(order + "iq8sqq", count, header["unk10"], header["version"],
                       _entry_size(fmt), meta_end)
    out += bytes([int(unicode), header["format_flags"], header["extended"]]) + header["unk33"]
    out += struct.pack(order + "q", hash_offset)
    for i, e in enumerate(entries):
        out += struct.pack(order + "Iiq", e.get("flags", 0x40000000), e.get("unk04", -1), len(e["data"]))
        if fmt & F_UNCOMP:
            uncomp = e.get("uncomp_size")
            out += struct.pack(order + "q", len(e["data"]) if uncomp is None else uncomp)
        out += struct.pack(order + ("q" if fmt & F_LONG_OFFSETS else "I"), data_offsets[i])
        if fmt & F_IDS:
            out += struct.pack(order + "i", e.get("id") or 0)
        if fmt & F_NAMES:
            out += struct.pack(order + "I", name_offsets[i])
    return bytes(out + names + hash_table + body)
