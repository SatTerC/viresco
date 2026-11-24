"""Tests for synthetic data generation and pipeline inputs."""

import numpy as np
import pytest
import xarray as xr
from catena import dry_run
from catena.config import Config
from catena.scaffold import generate_config

from viresco.testing.data_gen import generate_synthetic_data


class TestSyntheticDataGeneration:
    """Tests for synthetic data generation."""

    def test_daily_time_dimension(self, daily_ds):
        """Test daily dataset has correct time dimension."""
        assert len(daily_ds.time) == 365

    def test_weekly_time_dimension(self, weekly_ds):
        """Test weekly dataset has approximately 52 weeks for 365 days."""
        n_weeks = len(weekly_ds.time)
        assert 50 <= n_weeks <= 54

    def test_monthly_time_dimension(self, monthly_ds):
        """Test monthly dataset has correct time dimension."""
        assert len(monthly_ds.time) == 12

    def test_spatial_grid(self, daily_ds):
        """Test spatial grid dimensions."""
        assert daily_ds.sizes["y"] == 2
        assert daily_ds.sizes["x"] == 2

    def test_daily_variables(self, daily_ds):
        """Test daily dataset contains expected variables."""
        expected_vars = {
            "temperature",
            "precipitation",
            "sunshine_fraction",
            "lai_obs",
            "gpp_obs",
            "co2",
            "fapar",
            "ppfd",
            "pressure",
            "vpd",
        }
        assert set(daily_ds.data_vars) == expected_vars

    def test_weekly_variables(self, weekly_ds):
        """Test weekly dataset contains exactly the variables the config asks for."""
        assert set(weekly_ds.data_vars) == {"dummy_variable"}

    def test_monthly_variables(self, monthly_ds):
        """Each section holds only its own variables, not every temporal one."""
        assert set(monthly_ds.data_vars) == {"dummy_variable"}

    def test_static_variables(self, static_ds):
        """Test static dataset contains expected variables."""
        expected_vars = {
            "elevation",
            "latitude",
            "plant_type",
            "max_soil_moisture",
            "clay_content",
            "soil_depth",
            "organic_carbon_stocks",
            "root_pool_init",
            "leaf_pool_init",
            "stem_pool_init",
        }
        assert set(static_ds.data_vars) == expected_vars


class TestSyntheticDataValues:
    """Tests for synthetic data values."""

    def test_temperature_range(self, daily_ds):
        """Test temperature is in reasonable range for UK."""
        temp = daily_ds.temperature.values
        assert np.nanmin(temp) > -20
        assert np.nanmax(temp) < 40

    def test_precipitation_non_negative(self, daily_ds):
        """Test precipitation is non-negative."""
        precip = daily_ds.precipitation.values
        assert np.nanmin(precip) >= 0

    def test_sunshine_fraction_valid(self, daily_ds):
        """Test sunshine fraction is between 0 and 1."""
        sunshine = daily_ds.sunshine_fraction.values
        assert np.nanmin(sunshine) >= 0
        assert np.nanmax(sunshine) <= 1

    def test_lai_valid(self, daily_ds):
        """Test LAI is non-negative."""
        lai = daily_ds.lai_obs.values
        assert np.nanmin(lai) >= 0

    def test_gpp_non_negative(self, daily_ds):
        """Test GPP is non-negative."""
        gpp = daily_ds.gpp_obs.values
        assert np.nanmin(gpp) >= 0

    def test_plant_type_valid(self, static_ds):
        """Plant types are the models' encoding: 0=tree, 1=grass, 2=shrub, 3=crop."""
        assert np.all(np.isin(static_ds.plant_type.values, [0, 1, 2, 3]))

    def test_elevation_reasonable(self, static_ds):
        """Test elevation is in reasonable range."""
        elev = static_ds.elevation.values
        assert np.nanmin(elev) >= 0
        assert np.nanmax(elev) < 1000

    def test_crs_metadata(self, daily_ds, static_ds):
        """Every variable points at one CF latitude-longitude grid mapping."""
        for ds in (daily_ds, static_ds):
            mapping = ds["crs"].attrs
            assert mapping["grid_mapping_name"] == "latitude_longitude"
            for name, var in ds.data_vars.items():
                if name != "crs":
                    grid_mapping = var.encoding.get("grid_mapping") or var.attrs.get(
                        "grid_mapping"
                    )
                    assert grid_mapping == "crs", name


class TestFromCatenaInit:
    """The data generator fills a config `catena init` writes, whatever its labels."""

    def test_one_section_of_daily_and_static_variables(self, tmp_path):
        generated = generate_config(["splash"], base=tmp_path)
        generated.dump(tmp_path / "config.toml")
        config = Config.load(tmp_path / "config.toml").parse()
        generate_synthetic_data(config, grid=(1, 1), n_days=60)

        inputs = xr.open_dataset(tmp_path / "inputs.nc")
        assert inputs["temperature"].dims[0] == "time"
        assert "time" not in inputs["elevation"].dims
        report = dry_run(tmp_path / "config.toml")
        assert [stage for stage in report.stages if stage.status == "failed"] == []

    def test_a_coarse_variable_is_found_by_its_declared_freq(self, tmp_path):
        """`temperature_weekly` is weekly in any section, generated from `temperature`."""
        config = Config(
            {
                "sgam": {},
                "inputs": {
                    "anything": {
                        "path": "weekly.nc",
                        "suffix": "",
                        "vars": ["temperature_weekly"],
                    },
                },
            },
            base=tmp_path,
        ).parse()
        generate_synthetic_data(config, grid=(1, 1), n_days=60)
        weekly = xr.open_dataset(tmp_path / "weekly.nc")["temperature_weekly"]
        assert 8 <= weekly.sizes["time"] <= 10
        assert weekly.attrs["units"] == "degC"

    def test_a_section_at_two_frequencies_is_refused(self, tmp_path):
        generated = generate_config(["splash", "sgam"], base=tmp_path)
        config = Config(generated.data, base=tmp_path).parse()
        with pytest.raises(ValueError, match="several frequencies"):
            generate_synthetic_data(config, grid=(1, 1), n_days=60)
