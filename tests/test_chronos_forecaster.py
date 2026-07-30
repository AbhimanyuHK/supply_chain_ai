from app.forecast.chronos_forecaster import forecast_series_batch


def test_forecast_series_batch_empty_input_returns_empty():
    assert forecast_series_batch([], prediction_length=7) == []


def test_forecast_series_batch_shapes_and_non_negative():
    series_list = [
        [2.0, 3, 1, 4, 2, 5, 3, 2, 4, 1, 3, 2, 5, 4, 3, 2, 1, 4, 3, 2, 5, 3, 4, 2, 1, 3, 4, 2, 5, 3],
        [0.0] * 30,
    ]

    results = forecast_series_batch(series_list, prediction_length=5)

    assert len(results) == 2
    for result in results:
        assert set(result.keys()) == {"low", "median", "high"}
        for key in ("low", "median", "high"):
            assert len(result[key]) == 5
            assert all(v >= 0.0 for v in result[key])
        assert all(lo <= med <= hi for lo, med, hi in zip(result["low"], result["median"], result["high"]))


def test_forecast_series_batch_respects_batch_size_chunking():
    # 3 series with batch_size=1 forces 3 separate pipeline.predict calls;
    # result count/order should be unaffected by chunking.
    series_list = [[1.0, 2, 3, 4, 5] * 4 for _ in range(3)]

    results = forecast_series_batch(series_list, prediction_length=3, batch_size=1)

    assert len(results) == 3
    for result in results:
        assert len(result["median"]) == 3
