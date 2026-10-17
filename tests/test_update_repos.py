import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_repos import END, START, render_table, replace_section, select_repos  # noqa: E402


def repo(name, stars=0, pushed="2026-01-01T00:00:00Z", **kw):
    base = {
        "name": name,
        "html_url": f"https://github.com/me/{name}",
        "description": f"{name} description",
        "language": "Python",
        "topics": ["robotics", "python", "ml", "extra"],
        "stargazers_count": stars,
        "pushed_at": pushed,
        "fork": False,
        "archived": False,
        "private": False,
    }
    base.update(kw)
    return base


def test_filters_profile_forks_archived_and_excluded():
    repos = [
        repo("me"),
        repo("forked", fork=True),
        repo("old", archived=True),
        repo("hidden"),
        repo("keep"),
    ]
    names = [r["name"] for r in select_repos(repos, "Me", exclude=["hidden"])]
    assert names == ["keep"]


def test_order_featured_then_stars_then_recent():
    repos = [
        repo("a", stars=0, pushed="2026-03-01T00:00:00Z"),
        repo("b", stars=5),
        repo("c", stars=0, pushed="2026-05-01T00:00:00Z"),
        repo("pinned", stars=0, pushed="2020-01-01T00:00:00Z"),
    ]
    names = [r["name"] for r in select_repos(repos, "me", featured=["pinned"])]
    assert names == ["pinned", "b", "c", "a"]


def test_limit():
    repos = [repo(f"r{i}") for i in range(20)]
    assert len(select_repos(repos, "me", limit=6)) == 6


def test_render_table_escapes_and_limits_topics():
    table = render_table([repo("x", stars=2, description="a | b")])
    assert "[**x**](https://github.com/me/x) ★2" in table
    assert "a \\| b" in table
    assert "`extra`" not in table  # only three topics


def test_render_empty():
    assert "coming soon" in render_table([])


def test_replace_section_is_idempotent():
    readme = f"intro\n{START}\nold\n{END}\nouter"
    once = replace_section(readme, "NEW")
    assert once == f"intro\n{START}\nNEW\n{END}\nouter"
    assert replace_section(once, "NEW") == once


def test_missing_markers_raise():
    with pytest.raises(ValueError):
        replace_section("no markers", "x")


def test_real_readme_has_markers():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert START in text and END in text


def test_main_end_to_end(tmp_path, monkeypatch):
    import update_repos

    readme = tmp_path / "README.md"
    readme.write_text(f"# Hi\n{START}\nold\n{END}\n", encoding="utf-8")
    api = [repo("me"), repo("ur-kinematics", stars=1), repo("forked", fork=True)]
    monkeypatch.setattr(update_repos, "fetch_repos", lambda user, token=None: api)
    monkeypatch.setenv("GITHUB_USER", "me")
    monkeypatch.setenv("FEATURED", "")
    monkeypatch.setenv("MAX_REPOS", "")
    assert update_repos.main(readme) == 0
    text = readme.read_text(encoding="utf-8")
    assert "[**ur-kinematics**](https://github.com/me/ur-kinematics) ★1" in text
    assert "forked" not in text and "old" not in text
    assert update_repos.main(readme) == 0  # second run: no change
    assert readme.read_text(encoding="utf-8") == text
