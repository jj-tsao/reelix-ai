import pytest

from reelix_mcp.tools.recommend import build_spec


def test_minimal_spec_defaults():
    spec = build_spec(
        query_text="  moody neo-noir  ",
        media_type="movie",
        core_genres=None,
        exclude_genres=None,
        sub_genres=None,
        core_tone=None,
        key_themes=None,
        providers=None,
        year_range=None,
    )
    assert spec.query_text == "moody neo-noir"
    assert spec.media_type.value == "movie"
    assert spec.core_genres == []
    assert spec.providers == []
    assert spec.year_range is None
    assert spec.num_recs == 8  # spec default; not exposed as a tool param


def test_full_spec_passthrough():
    spec = build_spec(
        query_text="sci-fi with grief themes",
        media_type="movie",
        core_genres=["Science Fiction"],
        exclude_genres=["Horror"],
        sub_genres=["space opera"],
        core_tone=["melancholic"],
        key_themes=["grief"],
        providers=["Netflix"],
        year_range=[1990, 1999],
    )
    assert spec.core_genres == ["Science Fiction"]
    assert spec.exclude_genres == ["Horror"]
    assert spec.year_range == (1990, 1999)
    assert spec.providers == ["Netflix"]


def test_empty_query_rejected():
    with pytest.raises(ValueError, match="query_text"):
        build_spec(
            query_text="   ",
            media_type="movie",
            core_genres=None,
            exclude_genres=None,
            sub_genres=None,
            core_tone=None,
            key_themes=None,
            providers=None,
            year_range=None,
        )


def test_year_range_normalized_when_reversed():
    spec = build_spec(
        query_text="90s thrillers",
        media_type="movie",
        core_genres=None,
        exclude_genres=None,
        sub_genres=None,
        core_tone=None,
        key_themes=None,
        providers=None,
        year_range=[1999, 1990],
    )
    assert spec.year_range == (1990, 1999)


def test_year_range_wrong_arity_rejected():
    with pytest.raises(ValueError, match="year_range"):
        build_spec(
            query_text="90s thrillers",
            media_type="movie",
            core_genres=None,
            exclude_genres=None,
            sub_genres=None,
            core_tone=None,
            key_themes=None,
            providers=None,
            year_range=[1990],
        )
