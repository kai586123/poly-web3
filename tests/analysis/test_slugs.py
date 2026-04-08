from analysis_poly.slugs import generate_market_slug_specs


def test_slug_generation_ceil_start_open_end():
    specs = generate_market_slug_specs(
        symbols=["btc"],
        intervals=[5],
        start_ts=301,
        end_ts=901,
    )
    slugs = [s.slug for s in specs]
    assert slugs == [
        "btc-updown-5m-600",
        "btc-updown-5m-900",
    ]
