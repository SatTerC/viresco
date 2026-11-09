"""Download the COSMOS-UK data this recipe runs on.

Writes ``data/cosmos.nc``, relative to this file, with xharvest. The repository
already carries that file for the default site and period, so run this only to try
another: ``python fetch_data.py SITE START END``, e.g. ``python fetch_data.py WADDN
2020-01-01 2021-12-31``. ``xharvest.cosmos.sites()`` lists every site and its period
of record.

The data is under the Open Government Licence; see
https://nerc-ceh.github.io/xharvest/providers/cosmos-uk/#citing-the-data for how to
cite it.
"""

import sys
from datetime import date
from pathlib import Path

from xharvest import cosmos

DATA_DIR = Path(__file__).parent / "data"
SITE = "CHIMN"
START = date(2021, 1, 1)
END = date(2022, 12, 31)
PARAMETERS = ["cosmos_vwc", "precip", "snow", "swin", "ta"]


def write_inputs(
    site: str = SITE, start: date = START, end: date = END, data_dir: Path = DATA_DIR
) -> Path:
    """Download ``site``'s daily data from ``start`` to ``end`` into ``data_dir``.

    A download already made is not repeated.
    """
    raw = cosmos.fetch(site, start, end, data_dir / "raw", parameters=PARAMETERS)
    return cosmos.to_netcdf(raw, data_dir / "cosmos.nc")


if __name__ == "__main__":
    site, start, end = sys.argv[1:] or (SITE, START.isoformat(), END.isoformat())
    print(write_inputs(site, date.fromisoformat(start), date.fromisoformat(end)))
