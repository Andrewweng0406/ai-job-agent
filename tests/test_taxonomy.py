from app.matching.taxonomy import RoleTaxonomy
from app.models.enums import JobFamily


def test_taxonomy_classifies_configured_title(tmp_path):
    taxonomy_file = tmp_path / "taxonomy.yaml"
    taxonomy_file.write_text(
        """
accepted_job_families:
  DATA_ANALYTICS:
    persona: DATA
    title_keywords:
      - data analyst
""",
        encoding="utf-8",
    )
    taxonomy = RoleTaxonomy.from_yaml(taxonomy_file)
    assert taxonomy.classify_title("New Grad Data Analyst") == JobFamily.DATA_ANALYTICS
    assert taxonomy.classify_title("Office Manager") == JobFamily.UNKNOWN

