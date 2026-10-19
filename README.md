# Binary format RE tasks

Test suites for training models to reverse-engineer binary formats. The model writes the
parser; the tests check it by round-tripping real and synthetic files, not by comparing
against hardcoded values.

## bnd4_parser

Write `bnd4_parser/bnd4.py`. The required interface is in the docstring of
`bnd4_parser/tests/test_bnd4.py`.

## Setup

The real game files aren't included (they're copyrighted). Extract them from your own
copy of the game, then fetch them in. See [DATA.md](DATA.md).

```
python3 fetch_data.py --from /path/to/extracted/chr
cd bnd4_parser && pytest tests -v
```

`solutions/` holds reference answers for checking the suites. Keep it out of the model's
workspace. See [solutions/README.md](solutions/README.md).
