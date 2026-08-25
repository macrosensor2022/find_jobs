# Data Sources — Sponsorship & E-Verify Intelligence

This document lists the external datasets used by JobTracker's OPT-focused
employer lookup. **None of these files are committed to the repo** — they
live in `data/` which is gitignored. Download them locally and load via CLI.

---

## 1. E-Verify Employer List

| Field | Value |
|-------|-------|
| **Publisher** | USCIS (U.S. Citizenship and Immigration Services) |
| **URL** | https://www.e-verify.gov/about-e-verify/e-verify-data/how-to-find-participating-employers |
| **Format** | CSV (one row per employer enrollment) |
| **Key columns** | Company Name, City, State |
| **Refresh cadence** | Quarterly recommended |
| **Local path** | `data/everify_employers.csv` |

### Load command

```bash
python -m scrapers.sponsorship_data --load-everify data/everify_employers.csv
# Add --clear to replace existing records
```

---

## 2. H-1B Employer Data Hub (USCIS)

| Field | Value |
|-------|-------|
| **Publisher** | USCIS |
| **URL** | https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub |
| **Format** | CSV download (fiscal year, employer, approvals, denials) |
| **Key columns** | Employer, Fiscal Year, Initial Approvals, Initial Denials |
| **Refresh cadence** | Annually (new fiscal-year data released ~Q1) |
| **Local path** | `data/h1b_employer_hub.csv` |

### Load command

```bash
python -m scrapers.sponsorship_data --load-lca data/h1b_employer_hub.csv
```

---

## 3. LCA Disclosure Data (DOL OFLC) — optional / supplemental

| Field | Value |
|-------|-------|
| **Publisher** | US Department of Labor, OFLC |
| **URL** | https://www.dol.gov/agencies/eta/foreign-labor/performance |
| **Format** | XLSX / CSV quarterly disclosure files |
| **Key columns** | Employer Name, Prevailing Wage, Wage Level |
| **Notes** | Larger and more granular than the USCIS hub; includes wage data. Use if you want median-wage and wage-level enrichment. |
| **Local path** | `data/lca_disclosure.csv` |

### Load command

```bash
python -m scrapers.sponsorship_data --load-lca data/lca_disclosure.csv
```

---

## Column auto-detection

The CSV loader auto-detects columns by matching common header names
(case-insensitive). If your file uses a different header, either rename
the column or extend the `_EV_NAME` / `_LCA_NAME` lists in
`scrapers/sponsorship_data.py`.

---

## 4. Census CBSA Crosswalk (city → metro)

| Field | Value |
|-------|-------|
| **Publisher** | U.S. Census Bureau |
| **URL** | https://www.census.gov/geographies/reference-files/time-series/demo/metro-micro/delineation-files.html |
| **File** | List 2 — Principal Cities of Metropolitan and Micropolitan Statistical Areas (July 2023) |
| **Local path** | `data/list2_2023.xlsx` |
| **Used for** | Canonical city/state → CBSA metro mapping for location opportunity scoring |

```bash
# After placing list2_2023.xlsx and DOL LCA XLSX under data/:
python -m scrapers.sponsorship_data --load-lca data/LCA_Dislclosure_Data_FY2026_Q2.xlsx --rebuild-opportunity
python scripts/show_metro_opportunity.py
```

DE SOCs scored: `15-1243`, `15-2051`, `15-1211`.

---

## Disclaimer

> Sponsorship and E-Verify data is sourced from public US government datasets
> and may be out of date. This tool surfaces information only and is not legal
> advice — confirm details with your DSO and an immigration attorney.

*Last updated: June 2026*
