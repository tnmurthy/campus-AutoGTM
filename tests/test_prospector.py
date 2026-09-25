import json

import pytest

from agents import prospector_agent
from agents.sources.file_source import FileSource
from app.config import ConfigError, get_settings
from app.schemas.campaign import CampaignRead

CSV = """College_Code,Name,College_Type,City,State,Website,Notes
CLG-HYD-1,"Vasavi College of Engineering","Engineering Autonomous",Hyderabad,Telangana,https://vce.ac.in,"Active T&P cell"
CLG-HYD-2,"Nizam College","Degree & PG Autonomous",Hyderabad,Telangana,https://nizam.ac.in,"Strong BCA cohort"
CLG-VIZ-3,"GVP College of Engineering","Engineering Autonomous",Visakhapatnam,"Andhra Pradesh",https://gvpce.ac.in,"Coastal AP"
CLG-XXX-4,"",,,,,"row with no name"
"""


def campaign(**over) -> CampaignRead:
    base = dict(
        id="22222222-2222-2222-2222-222222222222", name="Sweep", segment_states=[], college_types=[], departments=[],
        objective="o", target_meetings_per_week=1,
        opportunity_type="hackathon", min_fit_score=70.0,
    )
    base.update(over)
    return CampaignRead(**base)


@pytest.fixture
def roster(tmp_path, monkeypatch):
    path = tmp_path / "roster.csv"
    path.write_text(CSV, encoding="utf-8")
    monkeypatch.setenv("PROSPECTOR_SOURCE", "file")
    monkeypatch.setenv("PROSPECTOR_FILE", str(path))
    get_settings.cache_clear()
    return path


class TestFileSource:
    def test_reads_a_csv_and_maps_aliased_columns(self, tmp_path):
        path = tmp_path / "r.csv"
        path.write_text(CSV, encoding="utf-8")
        leads = list(FileSource(path).fetch())

        assert [l["college_name"] for l in leads] == [
            "Vasavi College of Engineering",
            "Nizam College",
            "GVP College of Engineering",
        ]
        assert leads[0]["city"] == "Hyderabad"
        assert leads[0]["type"] == "Engineering Autonomous"

    def test_drops_a_row_with_no_institution_name(self, tmp_path):
        path = tmp_path / "r.csv"
        path.write_text(CSV, encoding="utf-8")
        assert all(l["college_name"] for l in FileSource(path).fetch())

    def test_reads_json_in_either_shape(self, tmp_path):
        bare = tmp_path / "a.json"
        bare.write_text(json.dumps([{"name": "Alpha College"}]), encoding="utf-8")
        wrapped = tmp_path / "b.json"
        wrapped.write_text(json.dumps({"records": [{"name": "Beta College"}]}), encoding="utf-8")

        assert [l["college_name"] for l in FileSource(bare).fetch()] == ["Alpha College"]
        assert [l["college_name"] for l in FileSource(wrapped).fetch()] == ["Beta College"]

    def test_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="roster not found"):
            list(FileSource(tmp_path / "nope.csv").fetch())


class TestCampaignFiltering:
    def test_filters_by_state(self, roster):
        leads = prospector_agent.discover_leads(campaign(segment_states=["Telangana"]))
        assert {l["city"] for l in leads} == {"Hyderabad"}

    def test_matches_a_type_whose_words_are_in_a_different_order(self, roster):
        # The source says "Engineering Autonomous"; a campaign may well say
        # "Autonomous Engineering". Neither string contains the other.
        leads = prospector_agent.discover_leads(
            campaign(college_types=["Autonomous Engineering"])
        )
        assert [l["college_name"] for l in leads] == [
            "Vasavi College of Engineering",
            "GVP College of Engineering",
        ]

    def test_an_empty_criterion_is_no_constraint(self, roster):
        assert len(prospector_agent.discover_leads(campaign())) == 3

    def test_combines_criteria(self, roster):
        leads = prospector_agent.discover_leads(
            campaign(segment_states=["Andhra Pradesh"], college_types=["Engineering"])
        )
        assert [l["college_name"] for l in leads] == ["GVP College of Engineering"]

    def test_a_criterion_matching_nothing_returns_nothing(self, roster):
        assert prospector_agent.discover_leads(campaign(segment_states=["Kerala"])) == []

    def test_deduplicates_by_normalised_name(self, tmp_path, monkeypatch):
        path = tmp_path / "dupes.csv"
        path.write_text(
            'Name,State\n"Vasavi College",Telangana\n"  VASAVI COLLEGE ",Telangana\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("PROSPECTOR_SOURCE", "file")
        monkeypatch.setenv("PROSPECTOR_FILE", str(path))
        get_settings.cache_clear()

        assert len(prospector_agent.discover_leads(campaign())) == 1


class TestSourceSelection:
    def test_defaults_to_the_stub_when_nothing_is_configured(self):
        get_settings.cache_clear()
        leads = prospector_agent.discover_leads(
            campaign(college_types=["Engineering"], departments=["CSE"])
        )
        assert leads[0]["college_name"] == "Example Engineering College"

    def test_falls_back_to_the_stub_when_the_source_is_broken(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROSPECTOR_SOURCE", "file")
        monkeypatch.setenv("PROSPECTOR_FILE", str(tmp_path / "absent.csv"))
        get_settings.cache_clear()

        # A dead source degrades rather than ending the campaign.
        leads = prospector_agent.discover_leads(campaign())
        assert leads[0]["college_name"] == "Example Engineering College"

    def test_rejects_an_unknown_source_name(self, monkeypatch):
        monkeypatch.setenv("PROSPECTOR_SOURCE", "telepathy")
        get_settings.cache_clear()
        with pytest.raises(ConfigError, match="PROSPECTOR_SOURCE"):
            get_settings()

    def test_datagov_needs_a_resource_and_key(self, monkeypatch):
        monkeypatch.setenv("PROSPECTOR_SOURCE", "datagov")
        get_settings.cache_clear()
        with pytest.raises(ConfigError) as exc:
            get_settings().require_datagov()
        assert "DATAGOV_RESOURCE_ID" in str(exc.value)
        assert "DATAGOV_API_KEY" in str(exc.value)

    def test_caps_the_number_of_leads(self, tmp_path, monkeypatch):
        rows = "Name,State\n" + "".join(
            f'"College {i}",Telangana\n' for i in range(prospector_agent.MAX_LEADS_PER_RUN + 40)
        )
        path = tmp_path / "many.csv"
        path.write_text(rows, encoding="utf-8")
        monkeypatch.setenv("PROSPECTOR_SOURCE", "file")
        monkeypatch.setenv("PROSPECTOR_FILE", str(path))
        get_settings.cache_clear()

        assert len(prospector_agent.discover_leads(campaign())) == prospector_agent.MAX_LEADS_PER_RUN
