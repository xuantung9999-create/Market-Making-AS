"""Day 5: live Binance recorder for best bid/ask (bookTicker) and trades (aggTrade).

The public archive has trades but no spot order book, so start this early and let it
run: by Day 12-13 you will have real top-of-book data to check the backtest against.

Usage (from the repo root; leave the terminal open, Ctrl+C to stop):
    python -m mm.recorder --symbol BTCUSDT
    python -m mm.recorder --symbol BTCUSDT --hours 6
    python -m mm.recorder --symbols ANKRUSDT,SKLUSDT,ARBUSDT,BTCUSDT      (v2: one socket, many coins)
    python -m mm.recorder --symbols-file config/candidates.txt

Writes small parquet part files every --flush seconds:
    data/live/<SYMBOL>/book/<SYMBOL>_book_<unix_ms>.parquet
        recv_us, update_id, bid, bid_qty, ask, ask_qty
    data/live/<SYMBOL>/trades/<SYMBOL>_trades_<unix_ms>.parquet
        recv_us, ts_us, price, qty, side          (same columns as mm.data + recv_us)
Load a folder back with ``load_live(folder)``.

Notes
- Spot bookTicker messages carry no exchange timestamp, so recv_us (your clock) is the
  time axis for the book. Trades carry the exchange time (ts_us) too; ts_us - recv_us
  gives you a rough latency estimate for free.
- Binance closes connections after 24 h; the recorder reconnects automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import pandas as pd

WS_URL = "wss://stream.binance.com:9443/stream?streams={s}@bookTicker/{s}@aggTrade"
BOOK_COLUMNS = ["recv_us", "update_id", "bid", "bid_qty", "ask", "ask_qty"]
LIVE_TRADE_COLUMNS = ["recv_us", "ts_us", "price", "qty", "side"]


def now_us() -> int:
    return time.time_ns() // 1000


def parse_book(d: dict, recv_us: int) -> tuple:
    """bookTicker payload: {"u": id, "s": sym, "b": bid, "B": bid_qty, "a": ask, "A": ask_qty}"""
    return (recv_us, int(d["u"]), float(d["b"]), float(d["B"]), float(d["a"]), float(d["A"]))


def parse_trade(d: dict, recv_us: int) -> tuple:
    """aggTrade payload: {"p": price, "q": qty, "T": trade time ms, "m": buyer is maker, ...}"""
    return (recv_us, int(d["T"]) * 1000, float(d["p"]), float(d["q"]), -1 if d["m"] else 1)


class Recorder:
    def __init__(self, symbol: str, out: str | Path = "data/live", flush_s: float = 60.0):
        self.symbol = symbol.upper()
        self.root = Path(out) / self.symbol
        self.flush_s = flush_s
        self.book: list[tuple] = []
        self.trades: list[tuple] = []
        self.n_book = self.n_trades = 0
        self._last_flush = time.monotonic()

    def handle(self, raw: str, recv_us: int) -> None:
        msg = json.loads(raw)
        stream, d = msg.get("stream", ""), msg.get("data", {})
        if stream.endswith("@bookTicker"):
            self.book.append(parse_book(d, recv_us))
        elif stream.endswith("@aggTrade"):
            self.trades.append(parse_trade(d, recv_us))

    def flush(self) -> None:
        stamp = now_us() // 1000
        for name, rows, cols in (("book", self.book, BOOK_COLUMNS),
                                 ("trades", self.trades, LIVE_TRADE_COLUMNS)):
            if not rows:
                continue
            folder = self.root / name
            folder.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame(rows, columns=cols)
            if name == "trades":
                df["side"] = df["side"].astype("int8")
            df.to_parquet(folder / f"{self.symbol}_{name}_{stamp}.parquet", index=False)
        self.n_book += len(self.book)
        self.n_trades += len(self.trades)
        self.book, self.trades = [], []
        self._last_flush = time.monotonic()
        print(f"[{time.strftime('%H:%M:%S')}] saved: {self.n_book:,} book updates, "
              f"{self.n_trades:,} trades so far", flush=True)

    def maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_s:
            self.flush()

    async def run(self, hours: float | None = None) -> None:
        import websockets  # imported here so the parsers can be tested without it

        url = WS_URL.format(s=self.symbol.lower())
        deadline = None if hours is None else time.monotonic() + hours * 3600
        backoff = 1.0
        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                        print(f"connected: {url}", flush=True)
                        backoff = 1.0
                        async for raw in ws:
                            self.handle(raw, now_us())
                            self.maybe_flush()
                            if deadline is not None and time.monotonic() >= deadline:
                                break
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                    print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        finally:
            self.flush()


def combined_url(symbols: list[str]) -> str:
    """One combined-stream URL carrying bookTicker and aggTrade for every symbol."""
    streams = "/".join(f"{s.lower()}@bookTicker/{s.lower()}@aggTrade" for s in symbols)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


class MultiRecorder:
    """v2: record several symbols over one websocket.

    Each symbol keeps its own ``Recorder`` buffer, so the files on disk are exactly the
    single-symbol layout (data/live/<SYMBOL>/book|trades/...). Messages for streams we did
    not subscribe to (or control messages) are ignored.
    """

    def __init__(self, symbols: list[str], out: str | Path = "data/live", flush_s: float = 60.0):
        self.symbols = [s.upper() for s in symbols]
        self.recorders = {s: Recorder(s, out, flush_s) for s in self.symbols}
        self.flush_s = flush_s
        self._last_flush = time.monotonic()

    def handle(self, raw: str, recv_us: int) -> None:
        msg = json.loads(raw)
        stream = msg.get("stream", "")
        if "@" not in stream:
            return
        sym, kind = stream.split("@", 1)
        rec = self.recorders.get(sym.upper())
        if rec is None:
            return
        d = msg.get("data", {})
        if kind == "bookTicker":
            rec.book.append(parse_book(d, recv_us))
        elif kind == "aggTrade":
            rec.trades.append(parse_trade(d, recv_us))

    def flush(self) -> None:
        for rec in self.recorders.values():
            if rec.book or rec.trades:
                rec.flush()
        self._last_flush = time.monotonic()

    def maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_s:
            self.flush()

    async def run(self, hours: float | None = None) -> None:
        import websockets

        url = combined_url(self.symbols)
        deadline = None if hours is None else time.monotonic() + hours * 3600
        backoff = 1.0
        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                        print(f"connected: {len(self.symbols)} symbols: {', '.join(self.symbols)}", flush=True)
                        backoff = 1.0
                        async for raw in ws:
                            self.handle(raw, now_us())
                            self.maybe_flush()
                            if deadline is not None and time.monotonic() >= deadline:
                                break
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                    print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        finally:
            self.flush()


def read_symbols_file(path: str | Path) -> list[str]:
    """One symbol per line; blank lines and # comments ignored."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.upper())
    return out


def load_live(folder: str | Path) -> pd.DataFrame:
    """Concatenate all part files in a book/ or trades/ folder, sorted by receive time."""
    parts = sorted(Path(folder).glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"no parquet files in {folder}")
    return pd.concat(map(pd.read_parquet, parts), ignore_index=True).sort_values(
        "recv_us", kind="stable").reset_index(drop=True)


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m mm.recorder")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--hours", type=float, default=None, help="stop after this long (default: run until Ctrl+C)")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--flush", type=float, default=60.0, help="seconds between saves")
    ap.add_argument("--symbols", default=None, help="comma-separated list (v2 multi-symbol mode)")
    ap.add_argument("--symbols-file", default=None, help="file with one symbol per line")
    args = ap.parse_args(argv)
    if args.symbols or args.symbols_file:
        syms = read_symbols_file(args.symbols_file) if args.symbols_file else args.symbols.split(",")
        rec = MultiRecorder([s.strip() for s in syms if s.strip()], args.out, args.flush)
    else:
        rec = Recorder(args.symbol, args.out, args.flush)
    try:
        asyncio.run(rec.run(args.hours))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    _main()
