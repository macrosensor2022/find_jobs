"""Skill vocabulary and skill-dimension scoring.

The vocabulary exists so the engine can report GAPS honestly: a skill is only
reported as a gap when the job actually asks for it and the candidate profile
does not contain it.
"""

from services.text_utils import word_present

# canonical name -> aliases searched in job text
SKILL_VOCABULARY = {
    # languages
    'Python': ['python'],
    'SQL': ['sql'],
    'T-SQL': ['t-sql', 'tsql', 'transact-sql'],
    'PL/SQL': ['pl/sql', 'plsql'],
    'Java': ['java'],
    'Scala': ['scala'],
    'C': ['c language'],
    'C++': ['c++', 'cpp'],
    'C#': ['c#', '.net'],
    'Go': ['golang'],
    'R': ['r language', ' r,', 'r programming'],
    'JavaScript': ['javascript', 'typescript', 'node.js'],
    'Bash': ['bash', 'shell scripting'],
    'SAS': ['sas'],
    'VBA': ['vba'],
    # cloud
    'Azure': ['azure'],
    'Azure Data Factory': ['data factory', 'adf'],
    'Azure Synapse': ['synapse'],
    'AWS': ['aws', 'amazon web services'],
    'GCP': ['gcp', 'google cloud'],
    'Snowflake': ['snowflake'],
    'Redshift': ['redshift'],
    'BigQuery': ['bigquery'],
    'Databricks': ['databricks'],
    # databases
    'SQL Server': ['sql server', 'mssql'],
    'PostgreSQL': ['postgres', 'postgresql'],
    'MySQL': ['mysql'],
    'Oracle': ['oracle db', 'oracle database'],
    'MongoDB': ['mongodb'],
    'NoSQL': ['nosql', 'dynamodb', 'cassandra'],
    # etl / orchestration
    'SSIS': ['ssis'],
    'ETL': ['etl'],
    'ELT': ['elt'],
    'dbt': ['dbt'],
    'Airflow': ['airflow'],
    'Informatica': ['informatica'],
    'Talend': ['talend'],
    'Kafka': ['kafka'],
    'Fivetran': ['fivetran'],
    'Prefect': ['prefect'],
    # big data
    'Spark': ['spark', 'pyspark'],
    'Hadoop': ['hadoop', 'hive', 'mapreduce'],
    'Flink': ['flink'],
    # bi
    'Power BI': ['power bi', 'powerbi'],
    'Tableau': ['tableau'],
    'Looker': ['looker'],
    'Qlik': ['qlik'],
    'Excel': ['advanced excel', 'excel'],
    'Alteryx': ['alteryx'],
    # ml
    'Machine Learning': ['machine learning'],
    'NLP': ['nlp', 'natural language processing'],
    'Transformers': ['transformers'],
    'BERT': ['bert'],
    'Embeddings': ['embeddings', 'vector search'],
    'TensorFlow': ['tensorflow'],
    'PyTorch': ['pytorch'],
    'scikit-learn': ['scikit-learn', 'sklearn'],
    'MLOps': ['mlops'],
    'LLM': ['llm', 'large language model'],
    # devops / tooling
    'Git': ['git'],
    'GitHub': ['github'],
    'Docker': ['docker'],
    'Kubernetes': ['kubernetes', 'k8s'],
    'Terraform': ['terraform'],
    'CI/CD': ['ci/cd', 'cicd', 'continuous integration'],
    'Azure DevOps': ['azure devops'],
    'Jenkins': ['jenkins'],
    'Linux': ['linux', 'unix'],
    # domain
    'Data Modeling': ['data modeling', 'data modelling', 'dimensional model'],
    'Data Warehousing': ['data warehouse', 'data warehousing'],
    'Data Quality': ['data quality'],
    'Data Governance': ['data governance'],
    'Data Pipelines': ['data pipeline', 'data pipelines'],
    'Statistics': ['statistics', 'statistical analysis'],
    'A/B Testing': ['a/b test', 'experimentation'],
}

# Skills that are nice-to-have rather than disqualifying when missing.
SOFT_GAP_SKILLS = {
    'Excel', 'Git', 'GitHub', 'Linux', 'Bash', 'JavaScript', 'C#', 'Go', 'VBA',
    'Jenkins', 'Qlik',
}


def _matches(aliases, text):
    return any(word_present(alias, text) for alias in aliases)


def extract_job_skills(job_text):
    """Return the canonical skills the job text actually mentions."""
    found = []
    for canonical, aliases in SKILL_VOCABULARY.items():
        if _matches(aliases, job_text):
            found.append(canonical)
    return found


def _profile_lookup(profile_skills):
    """Map lowercase profile skill name -> proficiency (1-5)."""
    out = {}
    for entry in profile_skills or []:
        if isinstance(entry, dict):
            name, prof = entry.get('name'), entry.get('proficiency', 3)
        elif isinstance(entry, (list, tuple)):
            name = entry[0]
            prof = entry[2] if len(entry) > 2 else 3
        else:
            name, prof = str(entry), 3
        if name:
            out[str(name).strip().lower()] = prof or 3
    return out


def score_skills(job_text, profile_skills):
    """Score the skills dimension 0-100 with matched/missing evidence.

    Coverage is weighted by the candidate's proficiency so that matching a
    core skill counts more than matching a peripheral one, and a missing
    nice-to-have costs less than a missing core requirement.
    """
    required = extract_job_skills(job_text)
    have = _profile_lookup(profile_skills)

    matched, missing = [], []
    matched_weight = 0.0
    missing_weight = 0.0

    for skill in required:
        proficiency = have.get(skill.lower())
        if proficiency:
            matched.append(skill)
            matched_weight += float(proficiency)
        else:
            missing.append(skill)
            missing_weight += 1.0 if skill in SOFT_GAP_SKILLS else 3.0

    if not required:
        # Nothing to match against — say so instead of inventing a score.
        return {
            'score': 50.0,
            'matched': [],
            'missing': [],
            'confidence': 'low',
            'note': 'No recognizable skill requirements found in the description',
        }

    total = matched_weight + missing_weight
    score = (matched_weight / total * 100.0) if total else 50.0

    # Breadth bonus: matching many of the candidate's strong skills is a
    # stronger signal than a single lucky keyword hit.
    if len(matched) >= 5:
        score = min(100.0, score + 8.0)
    elif len(matched) >= 3:
        score = min(100.0, score + 4.0)

    confidence = 'high' if len(required) >= 5 else 'medium' if len(required) >= 2 else 'low'
    return {
        'score': round(score, 1),
        'matched': matched,
        'missing': missing,
        'confidence': confidence,
        'note': None,
    }
