# Third-party notices

## bcpack-rs

The BC1 and original entropy implementation in `gta6x/bc/bcpack/decoder.py`,
`gta6x/bc/bcpack/tables.py`, `gta6x/bc/bcpack/data/bc1_window.json` and
`gta6x/bc/bcpack/data/bc1_quad_table.json` are ported from
[bcpack-rs](https://github.com/Ahmet-Dedeler/bcpack-rs) (Copyright (c) 2026
Ahmet Dedeler), licensed under MIT OR Apache-2.0. The full license texts are in
`LICENSES/bcpack-rs-MIT.txt` and `LICENSES/bcpack-rs-APACHE.txt`.

## Microsoft silicon-rans

The rANS model tables in `gta6x/bc/bcpack/tables.py` and the entropy-layer decoder
in `gta6x/bc/bcpack/decoder.py` are derived from `mdu_minirans.v` in
[microsoft/silicon-rans](https://github.com/microsoft/silicon-rans), licensed
under the MIT License, Copyright (c) Microsoft Corporation. The full notice is
in `LICENSES/bcpack-rs-THIRD_PARTY_NOTICES.md`.

## bc7decomp

`gta6x/bc/bc7.py` and `gta6x/bc/tables/bc7.py` are ported from
[bc7decomp.cpp](https://github.com/richgel999/bc7enc_rdo) by Richard Geldreich,
Jr., licensed under MIT OR public domain. The MIT text is in
`LICENSES/bc7decomp-MIT.txt`.

## bcdec

`gta6x/bc/bc6h.py` and `gta6x/bc/tables/bc6h.py` are ported from
[bcdec](https://github.com/iOrange/bcdec) by Sergii "iOrange" Kudlai, licensed
under MIT or public domain. The license text is in `LICENSES/bcdec-MIT.txt`.

## BCPack fitted data

`gta6x/bc/bcpack/data/bc1_window.json` and `gta6x/bc/bcpack/data/bc1_quad_table.json`
are the fitted BC1 preset window and quadrant codebook from bcpack-rs. They
contain codec constants, not game texture bytes.

## Native BC3/BC4/BC5 clean-room work

`gta6x/bc/bcpack/blocks.py` and `gta6x/bc/bcpack/data/bc345_tables.json` were
independently implemented/fitted from the repository specification, public
format facts and user-authorized black-box observations. Bundled table metadata records fitting counts, source-evidence limits and
provisional history entries. Local research documentation is excluded from
the published repository.
