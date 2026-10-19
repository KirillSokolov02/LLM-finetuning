# Test data

The real-file tests run against files from ELDEN RING. Those files are copyrighted, so
this repository does not contain them. You extract them from your own copy of the game,
and `fetch_data.py` copies them in and checks each one against `data_manifest.json`.
Both destinations are listed in `.gitignore`.

## What is needed

### `bnd4_parser/files/` — 10 animation binders

All of them come from the `Data3` archive. Each must be **decrypted and decompressed**,
not the raw `.dcx` as stored in the archive.

| dest | archive path | size (bytes) |
|---|---|---|
| `c0000_anibnd.bin` | `/chr/c0000.anibnd.dcx` | 68,192,570 |
| `c0000_a00_hi_anibnd.bin` | `/chr/c0000_a00_hi.anibnd.dcx` | 21,557,252 |
| `c0000_a00_lo_anibnd.bin` | `/chr/c0000_a00_lo.anibnd.dcx` | 307,636 |
| `c0000_a00_md_anibnd.bin` | `/chr/c0000_a00_md.anibnd.dcx` | 1,715,364 |
| `c0000_a0x_anibnd.bin` | `/chr/c0000_a0x.anibnd.dcx` | 5,028,276 |
| `c0000_a1x_anibnd.bin` | `/chr/c0000_a1x.anibnd.dcx` | 8,355,428 |
| `c0000_a2x_anibnd.bin` | `/chr/c0000_a2x.anibnd.dcx` | 15,749,956 |
| `c0000_a3x_anibnd.bin` | `/chr/c0000_a3x.anibnd.dcx` | 19,105,364 |
| `c0000_a4x_anibnd.bin` | `/chr/c0000_a4x.anibnd.dcx` | 9,806,964 |
| `c0000_a5x_anibnd.bin` | `/chr/c0000_a5x.anibnd.dcx` | 2,465,172 |

The SHA-256 of each file is in `data_manifest.json`. The hashes pin one game build;
another patch may produce different files, and `fetch_data.py` will reject them.

### `bnd4_parser/hex_samples/real_bnd4_header.hex` — derived

A text hex dump of the first 512 bytes of `c0000_a00_hi_anibnd.bin`. `fetch_data.py`
generates it, so you don't need to supply it.

## Getting the files

1. Unpack `chr/` from `Data3.bdt`/`Data3.bhd` with any tool that decrypts the archive
   index and decompresses DCX (Oodle Kraken). The binders must end up decompressed.
2. Put them in one directory. Any of the names in each entry's `accepted_names` works,
   e.g. `c0000_a00_hi.anibnd`.
3. Run:

   ```
   python3 fetch_data.py --from /path/to/that/dir --dry-run   # verify only
   python3 fetch_data.py --from /path/to/that/dir             # copy into place
   python3 fetch_data.py --check                              # re-verify later
   ```

The test suite raises an error rather than skipping when this data is missing, so a run
without data can never count as a pass.
