# Reference solutions

**Do not copy this folder into the model's workspace.** It holds the answers.

These exist to prove each test suite is fair: a correct implementation passes everything,
and broken ones fail.

## Checking a suite against its solution

Fetch the data first (see [../DATA.md](../DATA.md)), then:

```
cd bnd4_parser
PYTHONPATH=../solutions/bnd4_parser pytest tests -v
```

Expected result: 138 passed.

## Broken variants the BND4 suite catches

| broken variant | failures |
|---|---|
| writer returns the original bytes | 41 |
| no bounds check on payloads | 25 |
| wrong exception type on a short header | 17 |
| Shift-JIS names read as UTF-16 | 16 |
| payloads not aligned | 10 (real files only) |
| hash table not written | 10 (real files only) |
