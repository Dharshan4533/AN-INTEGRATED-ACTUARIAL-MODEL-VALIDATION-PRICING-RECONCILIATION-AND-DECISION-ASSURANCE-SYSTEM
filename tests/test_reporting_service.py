"""
Automated Test Suite for Rate Change Assurance Reporting Service.
Verifies multi-format report generation (Markdown, HTML, structured JSON/dict),
audit trail compilation, factor attribution waterfall, and reconciliation disclosures.
"""

import pytest
from rating.spec_schema import RatingManualSpec
from backend.services.impact_analysis_service import (
    ImpactAnalysisService,
    PortfolioReconciliationReport,
    SegmentImpact,
)
from backend.services.rate_change_service import PolicyAttributionResult
from backend.services.reporting_service import reporting_service


@pytest.fixture
def sample_specs():
    old_spec = RatingManualSpec(
        manual_id="AUTO-2025-BASE",
        name="Auto 2025 Base Manual",
        version="1.0.0",
        effective_date_start="2025-01-01",
        effective_date_end="2025-12-31",
        jurisdiction="US-OH",
        filing_reference="SERFF-OH-2024-001",
        currency="USD",
        currency_precision=2,
        base_rate=500.0,
        multiplicative_factors={
            "territory": {"Urban": 1.20, "Suburban": 1.00, "Rural": 0.85},
            "driver_age_band": {"16-25": 1.50, "26-64": 1.00, "65+": 1.10},
        },
        additive_fees={"policy_fee": 25.0},
    )

    new_spec = RatingManualSpec(
        manual_id="AUTO-2026-REVISION",
        name="Auto 2026 Revision Manual",
        version="2.0.0",
        effective_date_start="2026-01-01",
        effective_date_end="2026-12-31",
        jurisdiction="US-OH",
        filing_reference="SERFF-OH-2025-10928",
        currency="USD",
        currency_precision=2,
        base_rate=525.0,
        multiplicative_factors={
            "territory": {"Urban": 1.25, "Suburban": 1.00, "Rural": 0.85},
            "driver_age_band": {"16-25": 1.45, "26-64": 1.00, "65+": 1.15},
        },
        additive_fees={"policy_fee": 30.0},
    )

    return old_spec, new_spec


@pytest.fixture
def sample_census():
    return [
        {"policy_id": "POL_001", "territory": "Urban", "driver_age_band": "16-25"},
        {"policy_id": "POL_002", "territory": "Suburban", "driver_age_band": "26-64"},
        {"policy_id": "POL_003", "territory": "Rural", "driver_age_band": "65+"},
    ]


def test_reporting_service_compile_and_markdown(sample_specs, sample_census):
    old_spec, new_spec = sample_specs
    impact_svc = ImpactAnalysisService(old_spec, new_spec)
    summary = impact_svc.reconcile_census(sample_census)

    # 1. Compile structured dossier
    dossier = reporting_service.compile_rate_change_dossier(
        summary=summary,
        old_spec=old_spec,
        new_spec=new_spec,
    )

    assert dossier["currency"] == "USD"
    assert dossier["filing_overview"]["filing_reference"] == "SERFF-OH-2025-10928"
    assert dossier["filing_overview"]["jurisdiction"] == "US-OH"
    assert dossier["portfolio_impacts"]["total_valid_policies"] == 3
    assert len(dossier["contract_b_factor_attribution"]["waterfall"]) > 0

    # 2. Generate Markdown
    md_report = reporting_service.generate_rate_change_report(
        summary=summary,
        old_spec=old_spec,
        new_spec=new_spec,
        output_format="markdown",
    )

    assert isinstance(md_report, str)
    assert "# Rate Change Assurance Filing & Audit Memorandum" in md_report
    assert "SERFF-OH-2025-10928" in md_report
    assert "ZERO RESIDUAL RECONCILED" in md_report
    assert "Contract A: Aggregate Portfolio Reconciliation Identity" in md_report
    assert "Contract B: Rating-Rule Sequential Factor Attribution Waterfall" in md_report
    assert "Base Rate" in md_report
    assert "Dislocation Percentile" in md_report


def test_reporting_service_html_generation(sample_specs, sample_census):
    old_spec, new_spec = sample_specs
    impact_svc = ImpactAnalysisService(old_spec, new_spec)
    summary = impact_svc.reconcile_census(sample_census)

    html_report = reporting_service.generate_rate_change_report(
        summary=summary,
        old_spec=old_spec,
        new_spec=new_spec,
        output_format="html",
    )

    assert isinstance(html_report, str)
    assert "<!DOCTYPE html>" in html_report
    assert "<title>Rate Change Assurance Filing & Audit Memorandum</title>" in html_report
    assert "VERIFICATION CHECKS PASSED" in html_report
    assert "SERFF-OH-2025-10928" in html_report
    assert "Exact Monetary Equality" in html_report


def test_reporting_service_dict_format_and_unsupported(sample_specs, sample_census):
    old_spec, new_spec = sample_specs
    impact_svc = ImpactAnalysisService(old_spec, new_spec)
    summary = impact_svc.reconcile_census(sample_census)

    dict_report = reporting_service.generate_rate_change_report(
        summary=summary,
        old_spec=old_spec,
        new_spec=new_spec,
        output_format="dict",
    )
    assert isinstance(dict_report, dict)
    assert "filing_overview" in dict_report
    assert "portfolio_impacts" in dict_report

    with pytest.raises(ValueError, match="Unsupported report output format"):
        reporting_service.generate_rate_change_report(summary=summary, output_format="docx")
