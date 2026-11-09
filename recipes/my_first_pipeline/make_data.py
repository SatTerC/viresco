"""Write stand-in inputs for the first pipeline.

Two years of daily climate at one site to ``data/daily.nc``, and the site's
properties to ``data/static.nc``, both relative to this file. The series are
deterministic, so the results are reproducible.

This is also the shape your own data needs: one file per ``[inputs.*]`` section,
a ``units`` attribute on every variable, and a time dimension with dates on it.
The other dimension, here ``site``, can be called anything.

Run it directly, or call `write_inputs` from a notebook.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

DATA_DIR = Path(__file__).parent / "data"
SEED = 42


def write_inputs(data_dir: Path = DATA_DIR) -> list[Path]:
    """Write the daily and static NetCDF files, returning their paths."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    time = pd.date_range("2021-01-01", "2022-12-31", freq="D")
    season = np.sin(2 * np.pi * (time.dayofyear.to_numpy() - 110) / 365.25)
    n = time.size

    # Rain on about half the days, more of it in winter.
    rain_day = rng.random(n) < 0.5 - 0.1 * season
    precipitation = np.where(rain_day, rng.exponential(4.0, n), 0.0)
    sunshine_fraction = np.clip(0.35 + 0.15 * season + 0.15 * rng.normal(size=n), 0, 1)
    temperature = 10.0 + 7.0 * season + 2.5 * rng.normal(size=n)

    def daily(values, units):
        return (("time", "site"), values[:, np.newaxis], {"units": units})

    def static(value, units):
        return ("site", [value], {"units": units})

    sites = {"site": ["demo"]}
    xr.Dataset(
        {
            "precipitation": daily(precipitation, "mm d-1"),
            "sunshine_fraction": daily(sunshine_fraction, "1"),
            "temperature": daily(temperature, "degC"),
        },
        coords={"time": time, **sites},
    ).to_netcdf(data_dir / "daily.nc")

    xr.Dataset(
        {
            "elevation": static(100.0, "m"),
            "latitude": static(52.0, "degrees_north"),
            "max_soil_moisture": static(150.0, "mm"),
        },
        coords=sites,
    ).to_netcdf(data_dir / "static.nc")

    return [data_dir / "daily.nc", data_dir / "static.nc"]


if __name__ == "__main__":
    for path in write_inputs():
        print(path)
