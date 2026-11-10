from job_crawler.config import Settings
from job_crawler.pipeline import search_plan


def test_search_plan_adds_any_experience_roles():
    s = Settings(_env_file=None, desired_roles="백엔드,Java", any_experience_roles="SI, SM")
    assert search_plan(s) == [("백엔드", True), ("Java", True), ("SI", False), ("SM", False)]


def test_search_plan_defaults():
    s = Settings(_env_file=None, desired_roles="", any_experience_roles="")
    assert search_plan(s) == [("", True)]
