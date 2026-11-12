"""Optional pandas view of domain candles; monetary fields retain Decimal objects."""

from dataclasses import asdict

import pandas as pd


def candles_frame(candles):
    frame = pd.DataFrame(
        [asdict(bar) for bar in candles],
        columns=["open_time", "open", "high", "low", "close", "volume"],
    )
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    return frame.set_index("open_time")
