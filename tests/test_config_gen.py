"""Tests for scaffold/config_gen.py."""

import pytest
from hamilton.settings import ENABLE_POWER_USER_MODE
from xarray_annotated import Declared, Freq

from viresco import models, temporal
from viresco.scaffold import generate_config, get_model_config
from viresco.scaffold.config_gen import (
    _analyze_model_module,
    _base_name,
    _infer_required_data,
    _label_of,
    _node_name,
)

PATH_DEFAULTS = {
    "inputs_daily": "inputs/daily.nc",
    "inputs_weekly": "inputs/weekly.nc",
    "inputs_monthly": "inputs/monthly.nc",
    "inputs_static": "inputs/static.nc",
    "outputs_daily": "outputs/daily.nc",
    "outputs_weekly": "outputs/weekly.nc",
    "outputs_monthly": "outputs/monthly.nc",
}


class TestGetModelConfig:
    def test_builtin_returns_defaults(self):
        params = get_model_config("rothc")
        assert "n_years_spinup" in params
        assert isinstance(params["n_years_spinup"], int)

    def test_unknown_module_returns_empty(self):
        assert get_model_config("nonexistent.module") == {}

    def test_custom_path_uses_last_component_as_func_prefix(self):
        # Passing the full dotted path to a known module must find the same
        # _parameters() function as passing the short name.
        params_short = get_model_config("rothc")
        params_full = get_model_config("viresco.models.rothc")
        assert params_full == params_short

    def test_module_without_matching_function_returns_empty(self):
        # viresco.models has no function named "models" → hits the return {} fallback
        assert get_model_config("viresco.models") == {}


class TestGenerateConfigCustomModules:
    """Custom modules become flat sections addressed by `_import_path`."""

    def test_custom_module_with_params_written_to_config(self):
        config = generate_config(
            builtin_models=[],
            custom_modules=["viresco.models.rothc"],
            paths=PATH_DEFAULTS,
        )
        section = config._data["rothc"]
        # A module named explicitly as a custom module still gets an
        # `_import_path`, even one viresco happens to register: `generate_config`
        # has been told to treat it as the user's own.
        assert section["_import_path"] == "viresco.models.rothc"
        assert "n_years_spinup" in section

    def test_custom_module_without_params_written_as_import_path_only(self):
        config = generate_config(
            builtin_models=[],
            custom_modules=["viresco.models"],
            paths=PATH_DEFAULTS,
        )
        assert config._data["models"] == {"_import_path": "viresco.models"}

    def test_custom_module_params_appear_in_toml_output(self):
        config = generate_config(
            builtin_models=[],
            custom_modules=["viresco.models.rothc"],
            paths=PATH_DEFAULTS,
        )
        toml_str = str(config)
        assert "[rothc]" in toml_str
        assert '_import_path = "viresco.models.rothc"' in toml_str
        assert "n_years_spinup" in toml_str


class TestFrequencyLabels:
    """A node's frequency comes from its declared `Freq`, never from its name.

    Daily and static nodes are both bare, so the name cannot tell them apart.
    """

    @pytest.mark.parametrize(
        ("freq", "label"),
        [
            (temporal.DAILY, "daily"),
            (temporal.WEEKLY, "weekly"),
            (temporal.MONTHLY, "monthly"),
            (None, None),
        ],
    )
    def test_label_of_declared_freq(self, freq, label):
        assert _label_of(freq) == label

    def test_unknown_freq_raises(self):
        with pytest.raises(ValueError, match="none of viresco's frequencies"):
            _label_of(Freq("1h"))

    @pytest.mark.parametrize(
        ("base", "label", "name"),
        [
            ("temperature", "daily", "temperature"),
            ("elevation", None, "elevation"),
            ("gpp", "weekly", "gpp_weekly"),
            ("soil_carbon", "monthly", "soil_carbon_monthly"),
        ],
    )
    def test_node_name_round_trips(self, base, label, name):
        assert _node_name(base, label) == name
        assert _base_name(name, label) == base

    def test_daily_name_keeps_a_trailing_label(self):
        # Only the coarse suffixes are stripped; a bare daily name is left alone
        # even if it happens to end in something that looks like one.
        assert _base_name("growth_weekly", "daily") == "growth_weekly"


class TestGenerateConfigBuiltinModels:
    """generate_config with builtin model names populates inputs/outputs/resample."""

    def test_splash_generates_input_section(self):
        config = generate_config(
            builtin_models=["splash"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        data = config._data
        assert "inputs" in data

    def test_splash_produces_daily_outputs(self):
        config = generate_config(
            builtin_models=["splash"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        data = config._data
        assert "outputs" in data
        assert "daily" in data["outputs"]
        daily_vars = data["outputs"]["daily"]["vars"]
        assert any(
            "soil_moisture" in v or "evapotranspiration" in v or "runoff" in v
            for v in daily_vars
        )

    def test_rothc_generates_model_section_with_params(self):
        config = generate_config(
            builtin_models=["rothc"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        section = config._data["rothc"]
        # viresco registers rothc with catena, so the section resolves by name
        # alone and must carry no `_import_path`.
        assert "_import_path" not in section
        assert "n_years_spinup" in section

    def test_pmodel_generates_model_section(self):
        config = generate_config(
            builtin_models=["pmodel"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        assert "pmodel" in config._data
        assert "_import_path" not in config._data["pmodel"]

    def test_sgam_section_holds_its_daily_disturbance_setting(self):
        # Disturbance detection runs daily inside the weekly SGAM module, so its
        # setting is in `[sgam]` and its daily output is written.
        config = generate_config(
            builtin_models=["sgam"], custom_modules=[], paths=PATH_DEFAULTS
        )._data
        assert config["sgam"]["growing_season_limit"] == 10.0
        assert "disturbances" in config["outputs"]["daily"]["vars"]

    def test_unset_settings_stay_out_of_the_config(self):
        # TOML has no null, so a setting defaulting to None cannot be written.
        assert "reference_kphio" not in get_model_config("pmodel")

    def test_static_input_section_opts_out_of_suffix(self):
        # Static variables are consumed under bare names, so the generated
        # section must override catena's default `_<label>` node-name suffix.
        config = generate_config(
            builtin_models=["rothc"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        assert config._data["inputs"]["static"]["suffix"] == ""

    def test_daily_and_static_are_told_apart_by_freq(self):
        # Both are bare names; only the declared `Freq` separates them.
        inputs = generate_config(
            builtin_models=["splash"], custom_modules=[], paths=PATH_DEFAULTS
        )._data["inputs"]
        assert "temperature" in inputs["daily"]["vars"]
        assert "elevation" in inputs["static"]["vars"]
        assert "temperature" not in inputs["static"]["vars"]

    def test_daily_sections_and_resamples_use_bare_names(self):
        data = generate_config(
            builtin_models=["splash", "pmodel", "sgam", "rothc"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )._data
        assert data["inputs"]["daily"]["suffix"] == ""
        assert data["outputs"]["daily"]["suffix"] == ""
        assert "suffix" not in data["inputs"]["weekly"]
        assert "suffix" not in data["outputs"]["weekly"]
        sources = {entry["from"] for entry in data["resample"]}
        assert "daily" not in sources
        assert "" in sources

    def test_resample_entries_carry_an_explicit_freq(self):
        config = generate_config(
            builtin_models=["splash", "pmodel"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )
        for entry in config._data.get("resample", []):
            assert entry["freq"], entry
            assert "from" in entry
            assert "to" in entry

    def test_disturbances_get_their_own_max_resample(self):
        """SGAM wants the weekly maximum of `disturbances`, never its mean.

        A mean dilutes one short event by the quiet days around it, and nothing
        downstream catches it: the units agree and the pipeline runs.
        """
        resamples = generate_config(
            builtin_models=["splash", "pmodel", "sgam", "rothc"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )._data["resample"]
        holding = [entry for entry in resamples if "disturbances" in entry["vars"]]
        assert holding == [
            {
                "vars": ["disturbances"],
                "from": "",
                "to": "weekly",
                "freq": "7D",
                "aggfunc": "max",
            }
        ]
        means = [entry for entry in resamples if "aggfunc" not in entry]
        assert means
        assert all("disturbances" not in entry["vars"] for entry in means)

    def test_variable_shared_across_frequencies_is_loaded_once(self):
        """A variable wanted at several frequencies is loaded at the finest.

        SGAM's disturbance detection wants daily `temperature`, SGAM weekly and
        RothC monthly. It is loaded daily only, and coarsened step by step.
        """
        data = generate_config(
            builtin_models=["sgam", "rothc"],
            custom_modules=[],
            paths=PATH_DEFAULTS,
        )._data
        loaded_at = {
            label
            for label, section in data["inputs"].items()
            if "temperature" in section["vars"]
        }
        assert loaded_at == {"daily"}
        hops = {
            (entry["from"], entry["to"])
            for entry in data["resample"]
            if "temperature" in entry["vars"]
        }
        assert hops == {("", "weekly"), ("weekly", "monthly")}


class TestInferRequiredData:
    """_infer_required_data categorises inputs and outputs by frequency."""

    def test_splash_produces_daily_outputs_key(self):
        result = _infer_required_data(["splash"])
        assert "outputs_daily" in result
        assert len(result["outputs_daily"]) > 0

    def test_pmodel_produces_daily_outputs(self):
        result = _infer_required_data(["pmodel"])
        assert "gpp_flux" in result["outputs_daily"]
        assert not result["outputs_weekly"]

    def test_pmodel_drivers_are_loaded_daily(self):
        result = _infer_required_data(["pmodel"])
        drivers = {"co2", "fapar", "ppfd", "pressure", "temperature", "vpd"}
        assert drivers <= set(result["inputs_daily"])
        assert not result["inputs_weekly"]

    def test_bridge_source_finer_than_wanted_is_coarsened_first(self):
        """SGAM's weekly GPP and LUE come from the daily P-model.

        The source is resampled to weekly by a mean, and the bridge applied to
        that, rather than the bridge giving up and the input being loaded.
        """
        result = _infer_required_data(["pmodel", "sgam"])
        assert {"gpp_flux", "lue_photon", "iwue"} <= set(
            result["resample_daily_to_weekly"]
        )
        bridges = {node["name"]: node for node in result["bridges"]}
        assert bridges["gpp_weekly"]["inputs"] == ["gpp_flux_weekly"]
        assert bridges["lue_weekly"]["inputs"] == ["lue_photon_weekly"]
        loaded = {
            var
            for key in ("inputs_daily", "inputs_weekly", "inputs_monthly")
            for var in result[key]
        }
        assert {"gpp", "lue", "iwue"}.isdisjoint(loaded)

    def test_result_has_all_expected_keys(self):
        result = _infer_required_data(["splash"])
        for key in (
            "inputs_daily",
            "inputs_weekly",
            "inputs_monthly",
            "inputs_static",
            "resample_daily_to_weekly",
            "resample_daily_to_monthly",
            "resample_weekly_to_monthly",
            "outputs_daily",
            "outputs_weekly",
            "outputs_monthly",
        ):
            assert key in result, f"Missing key: {key}"

    def test_grid_vars_not_in_inputs(self):
        result = _infer_required_data(["splash"])
        all_inputs = (
            result["inputs_daily"]
            + result["inputs_weekly"]
            + result["inputs_monthly"]
            + result["inputs_static"]
        )
        assert "latitude" not in all_inputs
        assert "longitude" not in all_inputs


class TestUnitDiscovery:
    """`_analyze_model_module` reads every declared unit off a model.

    It silently found none when xarray-annotated moved from bare-string units to
    `Unit` markers, which changed the generated config without failing a test.
    """

    @pytest.mark.parametrize(
        ("model", "node", "unit"),
        [
            ("splash", "temperature", "degC"),
            ("splash", "soil_moisture", "mm"),
            ("pmodel", "gpp_flux", "ug m-2 s-1"),
            ("sgam", "leaf_pool_weekly", "g m-2"),
            ("rothc", "soil_organic_carbon_monthly", "t ha-1"),
        ],
    )
    def test_reads_input_and_output_units(self, model, node, unit):
        declared: dict[str, Declared] = {}
        _analyze_model_module(
            getattr(models, model), {ENABLE_POWER_USER_MODE: True}, declared
        )
        declaration = declared.get(node)
        assert declaration is not None
        assert declaration.unit is not None
        assert declaration.unit.unit == unit
