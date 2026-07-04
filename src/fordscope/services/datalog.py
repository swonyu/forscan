"""Live-data logging — poll Mode 01 PIDs over time and emit CSV.

The clock and sleep are injectable so logging is deterministic under test (no real
waiting). A PID the vehicle doesn't support (or can't decode) logs as an empty cell
rather than aborting the whole run.
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from ..obd.pids import PID_TABLE, PidResult
from ..obd.client import ObdError


@dataclass
class LogRow:
    t: float
    values: Dict[int, Optional[PidResult]] = field(default_factory=dict)


class DataLogger:
    def __init__(
        self,
        client,
        pids: Sequence[int],
        *,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.client = client
        self.pids = list(pids)
        self._clock = clock or time.time
        self._sleep = sleep or time.sleep

    def sample(self) -> LogRow:
        row = LogRow(self._clock())
        for pid in self.pids:
            try:
                row.values[pid] = self.client.current_data(pid)
            except (ObdError, KeyError, ValueError):
                row.values[pid] = None  # unsupported / undecodable -> blank cell
        return row

    def run(self, samples: int, interval: float = 0.0) -> List[LogRow]:
        rows: List[LogRow] = []
        for i in range(samples):
            rows.append(self.sample())
            if interval > 0 and i < samples - 1:
                self._sleep(interval)
        return rows


def column_header(pid: int) -> str:
    d = PID_TABLE.get(pid)
    return f"{d.name} ({d.unit})" if d else f"PID_{pid:02X}"


def rows_to_csv(rows: Sequence[LogRow], pids: Sequence[int]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["t"] + [column_header(p) for p in pids])
    for r in rows:
        cells = [f"{r.t:.3f}"]
        for p in pids:
            v = r.values.get(p)
            cells.append("" if v is None else v.value)
        writer.writerow(cells)
    return out.getvalue()


def write_csv_file(rows: Sequence[LogRow], pids: Sequence[int], path: str) -> None:
    with open(path, "w", newline="") as fh:
        fh.write(rows_to_csv(rows, pids))
