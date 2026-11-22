#!/usr/bin/env python3
"""Native BCPack BC1/BC3/BC4/BC5 decoder (pure Python, stdlib only).

BC1 and entropy ported from bcpack-rs (MIT OR Apache-2.0, Copyright (c) 2026 Ahmet Dedeler).
The entropy layer is a port of Microsoft silicon-rans `mdu_minirans.v` (MIT).
See LICENSES/bcpack-rs-*.txt. Slow (~0.1-0.3 MB/s); use for bounded exports,
the external helper for bulk runs.

BC1 layers (BC3/4/5 use the independently fitted blocks module;
table metadata records provenance and provisional histories):
  1. Entropy: 12 rANS lanes, each a cycle-level port of the `decoder` module in
     Microsoft's MIT-licensed silicon-rans Verilog (mdu_minirans.v), with its
     exact model tables (tables.py, generated). Lanes share one byte stream:
     each clock the lanes that request a byte are served in lane order 0..11,
     at most 8 bytes per clock. Symbols leave in lockstep vectors (one per lane).
  2. Endpoints: lane 0 = back-reference distance into the last 256 blocks
     (refs before block 0 read a fixed preset window), lanes 2-7 = zigzag
     residuals of R0 G0 B0 R1 G1 B1 modulo 2^width.
  3. Indices: lanes 8-11 = 2x2 quadrants TL, TR, BL, BR; each symbol indexes
     a fixed 256-entry codebook of 2x2 patterns of BC1 2-bit codes.
  4. Output: BC1 blocks in stream order, which is the stored Gfx10 tile order.

Licensed MIT OR Apache-2.0. Tables: MIT, Copyright (c) Microsoft Corporation.
"""
from __future__ import annotations

import json
import hashlib
import os
import struct

from .tables import (BASE_TABLE, FREQ_TABLE, RF_TABLE, RN_TABLE,
                            RS_TABLE, TABLES_SHA256)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

L = 1 << 24
LEGAL = (L, L >> 8, L >> 16)
FEED_WINDOW = 8

# BC1 lane layout: alphabet_bits = symbol width - 1 (the Verilog `alphabet_bits` input)
BC1_ALPHABET_BITS = (7, 7, 4, 5, 4, 4, 5, 4, 7, 7, 7, 7)
BC1_ENDPOINT_WIDTHS = (5, 6, 5, 5, 6, 5)   # lanes 2..7 = R0 G0 B0 R1 G1 B1

IDLE, HDR0, HDR1, HDR2, PROC, DRAIN = range(6)


class BCPackError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Model (mdu_minirans.v inverse / forward paths)
# ---------------------------------------------------------------------------
class Model:
    def __init__(self, eab, q):
        self.eab, self.q = eab, q
        self.base = BASE_TABLE[eab][q]
        self.freq = FREQ_TABLE[eab][q]
        self.rf = RF_TABLE[eab][q]
        self.rs = RS_TABLE[eab][q]
        self.rn = RN_TABLE[eab][q]
        self.nseg = eab + 2           # segment k is enabled iff eab >= k - 1

    def inverse(self, cf):
        """Symbol for the low 16 state bits: comparator chain, then reciprocal divide."""
        b = self.base
        seg = 0
        for k in range(self.nseg - 1, 0, -1):
            if cf >= b[k]:
                seg = k
                break
        base_x = 0 if seg == 0 else 1 << (seg - 1)
        dist = ((cf - b[seg]) + self.rn[seg]) & 0xFFFF
        steps = (((dist * self.rf[seg]) & 0xFFFFFFFF) >> 15 >> self.rs[seg]) & 0x1FF
        return (base_x + steps) & 0x1FF

    def forward(self, sym):
        """(freq, cumulative freq) of sym; slot 0 is reserved (cf 0 -> f-1, 1)."""
        seg = sym.bit_length()
        st = 0 if seg == 0 else 1 << (seg - 1)
        fa = self.freq[seg]
        cfa = (self.base[seg] + fa * (sym - st)) & 0xFFFF
        if cfa == 0:
            return (fa - 1) & 0xFFFF, 1
        return fa, cfa


_MODELS = {}


def model(eab, q):
    m = _MODELS.get((eab, q))
    if m is None:
        m = _MODELS[(eab, q)] = Model(eab, q)
    return m


# ---------------------------------------------------------------------------
# Cycle-level multi-lane decoder
# ---------------------------------------------------------------------------
class Lane:
    __slots__ = ("idx", "ab", "target", "state", "ib", "ib_full", "sym", "sym_full", "in_rem",
                 "out_rem", "p0", "p1", "hdr3", "flush", "q", "eab", "model", "done", "go",
                 "stall", "syms", "nbytes", "final", "frags", "fragment_states")

    def __init__(self, idx, ab, target):
        self.idx, self.ab, self.target = idx, ab, target
        self.state = IDLE
        self.ib = 0
        self.ib_full = False
        self.sym = 0
        self.sym_full = False
        self.in_rem = self.out_rem = 0
        self.p0 = self.p1 = 0
        self.hdr3 = self.flush = False
        self.q = self.eab = 0
        self.model = None
        self.done = False
        self.go = True
        self.stall = False
        self.syms = []
        self.nbytes = 0
        self.final = None
        self.frags = []        # (header byte, payload budget)
        self.fragment_states = []

    def need_byte(self):
        if self.ib_full:
            return False
        if self.state in (HDR0, HDR1, HDR2):
            return True
        return self.state == PROC and self.in_rem > 0

    def forward_state(self, x, sym):
        f, cf = self.model.forward(sym)
        return (f * (x >> 16) + (x & 0xFFFF) - cf) & 0xFFFFFFFF


def decode_lanes(data, alphabet_bits, targets, window=FEED_WINDOW, source=None,
                 *, strict=False):
    """Run the lanes over one shared byte stream.

    data: the chunk bytes (trailing zero padding allowed). source: optional
    callable(lane_index) -> next byte, used by the synthetic encoder to learn
    the interleave order (then `data` is ignored and the order is recorded).
    Returns dict(syms, consumed, cycles, lanes, order). Raises BCPackError
    unless every lane finished with a legal end state. ``strict`` additionally
    checks fragment convergence and symbol bounds for the BC3/4/5 profile.
    The legacy BC1 caller retains its original state handling.
    """
    n = len(alphabet_bits)
    if (not 1 <= n <= 12 or len(targets) != n
            or any(type(t) is not int or t <= 0 for t in targets)
            or any(type(ab) is not int or not 0 <= ab < len(BASE_TABLE)
                   for ab in alphabet_bits)
            or type(window) is not int or not 1 <= window <= FEED_WINDOW):
        raise BCPackError("invalid lane configuration")
    lanes = [Lane(i, alphabet_bits[i], targets[i]) for i in range(n)]
    slots = [False] * n
    pos = 0
    end = len(data) if source is None else 1 << 62
    order = []
    cycle = 0
    max_cycles = 64 * (sum(targets) + (len(data) if source is None else 0)) + 1000
    last_prog, last_change = None, 0
    while cycle < max_cycles:
        # phase 0: forward update, byte feed (lane order, <= window per clock), symbol hand-off
        served = 0
        for ln in lanes:
            sym_ready = not slots[ln.idx]
            blocked_out = ln.sym_full and not sym_ready
            need = ln.need_byte()
            req = need and not blocked_out
            valid = req and served < window and pos < end
            ln.stall = (need and not valid) or blocked_out
            if ln.stall:
                continue
            if ln.state in (PROC, DRAIN):
                ln.p0 = ln.forward_state(ln.p1, ln.sym) if ln.sym_full else ln.p1
            if valid:
                if source is None:
                    ln.ib = data[pos]
                else:
                    ln.ib = source(ln.idx)
                    order.append(ln.idx)
                pos += 1
                served += 1
                ln.nbytes += 1
                ln.ib_full = True
            if ln.sym_full:
                slots[ln.idx] = True
                ln.syms.append(ln.sym)
                ln.sym_full = False
        # phase 1: header FSM, renormalisation, symbol decode
        for ln in lanes:
            if ln.stall:
                continue
            st = ln.state
            if st == IDLE:
                if ln.go:
                    ln.go = False
                    ln.state = HDR0
                    ln.out_rem = ln.target
                    ln.p0 = ln.p1 = 0
            elif st == HDR0:
                if ln.ib_full:
                    b = ln.ib
                    ln.ib_full = False
                    ln.in_rem = 0
                    ln.state = HDR1
                    ln.q = b & 15
                    ln.hdr3 = bool(b & 0x20)
                    ln.flush = bool(b & 0x10)
                    e = ln.ab - (b >> 6)
                    if strict and not 0 <= e < len(BASE_TABLE):
                        raise BCPackError("lane %d: unsupported symbol width %d"
                                          % (ln.idx, e + 1))
                    if e < 0:
                        e &= 15
                    ln.eab = e if e < 10 else 9
                    ln.frags.append([b, None])
                    if ln.eab > 8:
                        raise BCPackError("lane %d: header selects alphabet index %d" % (ln.idx, ln.eab))
            elif st == HDR1:
                if ln.ib_full:
                    ln.ib_full = False
                    ln.model = model(ln.eab, ln.q)
                    if ln.hdr3:
                        ln.in_rem = ln.ib
                        ln.state = HDR2
                    else:
                        ln.in_rem = ln.ib + 1
                        ln.state = PROC
                        ln.frags[-1][1] = ln.in_rem
            elif st == HDR2:
                if ln.ib_full:
                    ln.ib_full = False
                    ln.in_rem = ((ln.ib << 8) | (ln.in_rem & 0xFF)) + 257
                    ln.frags[-1][1] = ln.in_rem
                    ln.state = PROC
            else:  # PROC or DRAIN
                will = st == PROC and ln.p0 < L and ln.in_rem > 0 and ln.ib_full
                x = (((ln.p0 & 0xFFFFFF) << 8) | ln.ib) if will else ln.p0
                nsf = x > L and ln.out_rem > 0
                new_out = ln.out_rem - 1 if nsf else ln.out_rem
                ln.p1 = x
                ln.out_rem = new_out
                if nsf:
                    if strict and (x & 0xFFFF) == 0:
                        raise BCPackError("lane %d: reserved rANS slot zero" % ln.idx)
                    ln.sym = ln.model.inverse(x & 0xFFFF)
                    if strict and not 0 <= ln.sym < (1 << (ln.eab + 1)):
                        raise BCPackError("lane %d: symbol outside alphabet" % ln.idx)
                ln.sym_full = nsf
                if st == PROC:
                    if will:
                        ln.in_rem -= 1
                        ln.ib_full = False
                    if ln.in_rem == 0:
                        if new_out > 0:
                            if x == L:
                                ln.fragment_states.append(x)
                                ln.state = HDR0
                                if ln.flush:
                                    ln.p1 = 0
                            else:
                                ln.state = DRAIN
                        else:
                            ln.done = True
                            ln.state = IDLE
                            ln.final = ln.forward_state(x, ln.sym) if nsf else x
                            ln.fragment_states.append(ln.final)
                elif x <= L:
                    if strict and ln.flush and x not in LEGAL:
                        raise BCPackError("lane %d: flushed fragment did not converge" % ln.idx)
                    ln.fragment_states.append(x)
                    if new_out > 0:
                        ln.state = HDR0
                        if ln.flush:
                            ln.p0 = ln.p1 = 0
                    else:
                        ln.done = True
                        ln.state = IDLE
                        ln.final = ln.forward_state(x, ln.sym) if nsf else x
        # lockstep symbol vector: released when every still-active lane has a symbol
        active = [i for i in range(n) if not (lanes[i].done and not lanes[i].sym_full and not slots[i])]
        if any(slots) and all(slots[i] for i in active):
            slots = [False] * n
        cycle += 1
        if all(ln.done and not ln.sym_full for ln in lanes):
            bad = [ln.idx for ln in lanes if ln.final not in LEGAL]
            if bad:
                raise BCPackError("lanes %s ended in an illegal state" % bad)
            if strict:
                for ln in lanes:
                    if (len(ln.syms) != ln.target or ln.out_rem != 0
                            or ln.in_rem != 0 or ln.ib_full
                            or len(ln.frags) != len(ln.fragment_states)):
                        raise BCPackError("lane %d: element/byte count mismatch" % ln.idx)
            return dict(syms=[ln.syms for ln in lanes], consumed=pos, cycles=cycle, order=order,
                        lanes=[dict(nbytes=ln.nbytes, final=ln.final, frags=ln.frags,
                                    fragment_states=ln.fragment_states) for ln in lanes])
        prog = (pos, sum(len(ln.syms) for ln in lanes), sum(ln.state for ln in lanes))
        if prog != last_prog:
            last_prog, last_change = prog, cycle
        elif cycle - last_change > 64:
            raise BCPackError("no progress (stream truncated or invalid BCPack) at byte %d" % pos)
    raise BCPackError("cycle limit reached")


def decode_symbols(chunk, blocks):
    """BC1 chunk -> 12 lane symbol lists (each `blocks` long). Checks that every
    byte after the last consumed one is zero padding."""
    r = decode_lanes(chunk, BC1_ALPHABET_BITS, [blocks] * 12)
    if any(chunk[r["consumed"]:]):
        raise BCPackError("non-zero bytes after the end of the stream (%d of %d consumed)"
                          % (r["consumed"], len(chunk)))
    return r["syms"], r


def decode_codec_symbols(chunk: bytes, codec: int, out_size: int):
    """Decode the public BC3/4/5 entropy profile, without rebuilding blocks.

    Returns ``(symbols, diagnostics)``; the latter includes consumed bytes and
    each lane's byte count, fragment headers and terminal state. No history or
    index-codebook assumptions are made here.
    """
    from .spec import CODECS, element_count

    count = element_count(codec, out_size)
    if not isinstance(chunk, bytes):
        raise BCPackError("chunk must be bytes")
    widths = CODECS[codec]["default_widths"]
    result = decode_lanes(chunk, tuple(w - 1 for w in widths), [count] * 12,
                          strict=True)
    if any(chunk[result["consumed"]:]):
        raise BCPackError("non-zero bytes after the end of the stream (%d of %d consumed)"
                          % (result["consumed"], len(chunk)))
    return result["syms"], result


def decode_chunk(chunk: bytes, codec: int, out_size: int) -> bytes:
    """BC3/4/5 payload -> exact BCn blocks in stored Gfx10 tile order.

    Malformed streams, unsupported profiles and unfitted entries raise
    ValueError; reconstruction never substitutes a default for missing data.
    """
    from .blocks import assemble

    syms, _ = decode_codec_symbols(chunk, codec, out_size)
    return assemble(syms, codec, out_size)


# ---------------------------------------------------------------------------
# BC1 semantics
# ---------------------------------------------------------------------------
def load_window(path=os.path.join(DATA, "bc1_window.json")):
    """256 preset endpoint tuples (unfitted slots read as zeros) + fitted mask."""
    with open(path, encoding="utf-8") as handle:
        d = json.load(handle)
    win = [(0, 0, 0, 0, 0, 0)] * 256
    fitted = [False] * 256
    for s, e in enumerate(d["slots"]):
        if e is not None:
            win[s] = tuple(e["value"])
            fitted[s] = True
    return win, fitted


def load_quad_table(path=os.path.join(DATA, "bc1_quad_table.json")):
    """symbol -> codes (TL, TR, BL, BR) of a 2x2 pixel group."""
    with open(path, encoding="utf-8") as handle:
        d = json.load(handle)
    return [tuple(e["codes"]) for e in sorted(d["entries"], key=lambda e: e["sym"])]


def back_distance(v):
    """Lane 0 symbol -> distance: unzigzag(v) mod 256 (0 = no reference)."""
    return (v >> 1) if not (v & 1) else 255 - (v >> 1)


def unzigzag(v):
    return -((v + 1) >> 1) if v & 1 else v >> 1


def endpoints(syms, window, fitted=None):
    """Lanes 0, 2-7 -> list of (R0, G0, B0, R1, G1, B1) per block, plus the number of
    blocks whose reference chain reaches an unfitted window slot."""
    n = len(syms[0])
    l0 = syms[0]
    res = [syms[2 + k] for k in range(6)]
    mods = [1 << w for w in BC1_ENDPOINT_WIDTHS]
    E = [None] * n
    tainted = [False] * n
    zero = (0, 0, 0, 0, 0, 0)
    for i in range(n):
        d = back_distance(l0[i])
        t = False
        if d == 0:
            P = zero
        elif d <= i:
            P = E[i - d]
            t = tainted[i - d]
        else:
            slot = (i - d) & 255
            P = window[slot]
            t = fitted is not None and not fitted[slot]
        E[i] = tuple((P[k] + unzigzag(res[k][i])) % mods[k] for k in range(6))
        tainted[i] = t
    return E, sum(tainted)


QUAD_ORIGIN = ((0, 0), (2, 0), (0, 2), (2, 2))   # (x, y) of TL, TR, BL, BR groups
GROUP_PIXEL = ((0, 0), (1, 0), (0, 1), (1, 1))   # codes order inside a group


def quad_masks(table):
    """symbol -> 32-bit index-word contribution for each of the 4 quadrants."""
    out = []
    for q, (ox, oy) in enumerate(QUAD_ORIGIN):
        row = []
        for codes in table:
            w = 0
            for k, (dx, dy) in enumerate(GROUP_PIXEL):
                x, y = ox + dx, oy + dy
                w |= codes[k] << (2 * (4 * y + x))
            row.append(w)
        out.append(row)
    return out


def assemble_bc1(syms, window, table, fitted=None):
    E, tainted = endpoints(syms, window, fitted)
    masks = quad_masks(table)
    out = bytearray()
    for i, e in enumerate(E):
        c0 = (e[0] << 11) | (e[1] << 5) | e[2]
        c1 = (e[3] << 11) | (e[4] << 5) | e[5]
        idx = masks[0][syms[8][i]] | masks[1][syms[9][i]] | masks[2][syms[10][i]] | masks[3][syms[11][i]]
        out += struct.pack("<HHI", c0, c1, idx)
    return bytes(out), tainted


def decode_bc1(chunk, blocks, window=None, table=None):
    """BCPack BC1 chunk bytes -> BC1 blocks (8 bytes each, stream / Gfx10 order)."""
    if window is None:
        window, fitted = load_window()
    else:
        fitted = None
    table = table or load_quad_table()
    syms, _ = decode_symbols(chunk, blocks)
    data, _ = assemble_bc1(syms, window, table, fitted)
    return data


def tables_ok() -> bool:
    """Check the vendored rANS model tables against their published checksum."""
    tables = (BASE_TABLE, FREQ_TABLE, RF_TABLE, RS_TABLE, RN_TABLE)
    text = "".join(",".join(str(v) for e in table for q in e for v in q) + "\n"
                   for table in tables)
    return hashlib.sha256(text.encode()).hexdigest() == TABLES_SHA256
