# Third-party notices

## bcpack-rs

`gta6x/bcpack.py`, `gta6x/bcpack_tables.py` and `gta6x/bcpack_data/*.json`
are ported from
[bcpack-rs](https://github.com/Ahmet-Dedeler/bcpack-rs) (Copyright (c) 2026
Ahmet Dedeler), licensed under MIT OR Apache-2.0. The full license texts are in
`LICENSES/bcpack-rs-MIT.txt` and `LICENSES/bcpack-rs-APACHE.txt`.

## Microsoft silicon-rans

The rANS model tables in `gta6x/bcpack_tables.py` and the entropy-layer decoder
in `gta6x/bcpack.py` are derived from `mdu_minirans.v` in
[microsoft/silicon-rans](https://github.com/microsoft/silicon-rans), licensed
under the MIT License, Copyright (c) Microsoft Corporation. The full notice is
in `LICENSES/bcpack-rs-THIRD_PARTY_NOTICES.md`.

## bc7decomp

`gta6x/bc7.py` and `gta6x/bc7_tables.py` are ported from
[bc7decomp.cpp](https://github.com/richgel999/bc7enc_rdo) by Richard Geldreich,
Jr., licensed under MIT OR public domain. The MIT text is in
`LICENSES/bc7decomp-MIT.txt`.

## BCPack fitted data

`gta6x/bcpack_data/bc1_window.json` and `gta6x/bcpack_data/bc1_quad_table.json`
are the fitted BC1 preset window and quadrant codebook from bcpack-rs. They
contain codec constants, not game texture bytes.
