from pathlib import Path
from scripts.supervise_live import live_data_path

BASE = Path("/proj")


def test_whitelisted_live_files_map_into_data():
    assert live_data_path(BASE, "/data/live/heartbeat.json") == BASE / "data/live/heartbeat.json"
    assert live_data_path(BASE, "/data/paper/snapshot.json") == BASE / "data/paper/snapshot.json"
    assert live_data_path(BASE, "/data/testnet/BTCUSDT/status.json?x=1") == BASE / "data/testnet/BTCUSDT/status.json"


def test_everything_else_under_data_is_refused():
    for p in ["/data/live/BTCUSDT/book/x.parquet", "/data/testnet/../../.env", "/data/testnet/BTC%2F../status.json",
              "/.env", "/data/testnet/btcusdt/status.json", "/index.html"]:
        assert live_data_path(BASE, p) is None, p
