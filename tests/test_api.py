import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import (
    green_wave_max_coverage,
    green_wave_offset_diagnostics,
    green_wave_slot_offsets,
    green_wave_windows,
)
from app.schemas import (
    GreenWaveRequest,
    Intersection,
    OffsetDiagnosticsRequest,
    SlotOffsetRequest,
)


def make_request(payload):
    return GreenWaveRequest.model_validate(payload)


def test_api_returns_windows_payload():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 300,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 30, "travel": 0},
                {"cycle": 60, "offset": 30, "green_start": 0, "green_end": 30, "travel": 30},
            ],
        }
    )
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [
        [0, 30], [60, 90], [120, 150], [180, 210], [240, 270],
    ]


def test_api_empty_array_on_no_solution():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10, "travel": 0},
                {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 30, "travel": 0},
            ],
        }
    )
    assert green_wave_windows(req) == []


def test_reject_invalid_cycle():
    with pytest.raises(ValidationError):
        Intersection(cycle=0, offset=0, green_start=0, green_end=10, travel=0)


def test_reject_negative_travel():
    with pytest.raises(ValidationError):
        Intersection(cycle=60, offset=0, green_start=0, green_end=10, travel=-1)


def test_reject_offset_outside_cycle():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 60, "green_start": 0, "green_end": 10, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_green_endpoint_outside_cycle():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 60, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_range_over_one_hour():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 3601,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_too_many_intersections():
    with pytest.raises(ValidationError):
        make_request(
            {
                "depart_from": 0,
                "depart_to": 60,
                "intersections": [
                    {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10}
                    for _ in range(9)
                ],
            }
        )


def test_reject_empty_intersections():
    with pytest.raises(ValidationError):
        make_request({"depart_from": 0, "depart_to": 60, "intersections": []})


# ---------- travel_max 波动行驶时间 ----------

def test_travel_max_shrinks_windows():
    # 绿灯 [20,40)，行驶时间 [0,10]：窗口由 20 秒收缩为 10 秒
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 120,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 20,
                 "green_end": 40, "travel": 0, "travel_max": 10}
            ],
        }
    )
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [[20, 30], [80, 90]]


def test_travel_max_defaults_to_travel():
    base = {
        "cycle": 60, "offset": 0, "green_start": 20, "green_end": 40,
        "travel": 5,
    }
    req = make_request(
        {"depart_from": 0, "depart_to": 120, "intersections": [base]}
    )
    req2 = make_request(
        {"depart_from": 0, "depart_to": 120,
         "intersections": [{**base, "travel_max": 5}]}
    )
    assert green_wave_windows(req) == green_wave_windows(req2)


def test_reject_travel_max_less_than_travel():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 20, "travel_max": 19}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_reject_travel_max_over_86400():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0, "travel_max": 86401}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_travel_max_86400_boundary_accepted():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "intersections": [
                # 整周期常绿：波动再大也不受影响
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 0, "travel": 0, "travel_max": 86400}
            ],
        }
    )
    req.validate_ranges()
    windows = green_wave_windows(req)
    assert [[w.start, w.end] for w in windows] == [[0, 60]]


# ---------- POST /api/green-wave/max-coverage ----------

def test_max_coverage_payload_overlap():
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 120,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 40, "travel": 0},
                {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 50, "travel": 0},
            ],
        }
    )
    resp = green_wave_max_coverage(req)
    assert resp.max_coverage == 2
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [
        [20, 40], [80, 100],
    ]


def test_max_coverage_zero_returns_complete_range():
    req = make_request(
        {
            "depart_from": 10,
            "depart_to": 70,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 40,
                 "travel": 0, "travel_max": 30}
            ],
        }
    )
    resp = green_wave_max_coverage(req)
    assert resp.max_coverage == 0
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [[10, 70]]


def test_max_coverage_reuses_request_validation():
    # 与 /windows 相同的跨字段校验：发车范围超过 3600 秒仍返回 422。
    req = make_request(
        {
            "depart_from": 0,
            "depart_to": 3601,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 10, "travel": 0}
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        green_wave_max_coverage(req)
    assert exc.value.status_code == 422


def test_max_coverage_route_is_in_openapi():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/green-wave/max-coverage" in paths
    assert "post" in paths["/api/green-wave/max-coverage"]


# ---------- POST /api/green-wave/offset-diagnostics ----------

def make_diag_request(payload):
    return OffsetDiagnosticsRequest.model_validate(payload)


def test_offset_diagnostics_payload_plain_green():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 20,
            "green_end": 40,
            "observations": [
                {"arrival_time": 0, "observed_green": True},
                {"arrival_time": 5, "observed_green": True},
            ],
        }
    )
    resp = green_wave_offset_diagnostics(req)
    # arrival=0 观测绿 ⇔ offset∈[20,40)；arrival=5 观测绿 ⇔ offset∈[15,35)
    # 零错配集合为两者之交 [20,35)
    assert resp.min_mismatches == 0
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [[20, 35]]


def test_offset_diagnostics_payload_wrapping_optimal_set():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 50,
            "green_end": 10,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        }
    )
    resp = green_wave_offset_diagnostics(req)
    assert resp.min_mismatches == 0
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [
        [0, 10], [50, 60]
    ]


def test_offset_diagnostics_min_mismatches_positive():
    # 常绿路口但观测到红灯：任何 offset 都错 1 条
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 30,
            "green_end": 30,
            "observations": [{"arrival_time": 9, "observed_green": False}],
        }
    )
    resp = green_wave_offset_diagnostics(req)
    assert resp.min_mismatches == 1
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [[0, 60]]


def test_offset_diagnostics_accepts_negative_arrival_time():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 20,
            "green_end": 40,
            "observations": [{"arrival_time": -1, "observed_green": True}],
        }
    )
    resp = green_wave_offset_diagnostics(req)
    assert resp.min_mismatches == 0
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [[21, 41]]


def test_offset_diagnostics_rejects_zero_cycle():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 0,
                "green_start": 0,
                "green_end": 10,
                "observations": [{"arrival_time": 0, "observed_green": True}],
            }
        )


def test_offset_diagnostics_rejects_cycle_over_86400():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 86401,
                "green_start": 0,
                "green_end": 10,
                "observations": [{"arrival_time": 0, "observed_green": True}],
            }
        )


def test_offset_diagnostics_rejects_green_start_outside_cycle():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 60,
            "green_end": 10,
            "observations": [{"arrival_time": 0, "observed_green": True}],
        }
    )
    with pytest.raises(HTTPException) as exc:
        req.validate_ranges()
    assert exc.value.status_code == 422


def test_offset_diagnostics_rejects_negative_green_end():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 60,
                "green_start": 0,
                "green_end": -1,
                "observations": [{"arrival_time": 0, "observed_green": True}],
            }
        )


def test_offset_diagnostics_rejects_empty_observations():
    with pytest.raises(ValidationError):
        make_diag_request(
            {"cycle": 60, "green_start": 0, "green_end": 10, "observations": []}
        )


def test_offset_diagnostics_rejects_too_many_observations():
    with pytest.raises(ValidationError):
        make_diag_request(
            {
                "cycle": 60,
                "green_start": 0,
                "green_end": 10,
                "observations": [
                    {"arrival_time": i, "observed_green": True}
                    for i in range(2001)
                ],
            }
        )


def test_offset_diagnostics_accepts_2000_observations_boundary():
    req = make_diag_request(
        {
            "cycle": 60,
            "green_start": 0,
            "green_end": 0,  # 常绿
            "observations": [
                {"arrival_time": i, "observed_green": True}
                for i in range(2000)
            ],
        }
    )
    req.validate_ranges()
    resp = green_wave_offset_diagnostics(req)
    assert resp.min_mismatches == 0
    assert [[w.start, w.end] for w in resp.optimal_intervals] == [[0, 60]]


def test_offset_diagnostics_route_is_in_openapi():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/green-wave/offset-diagnostics" in paths
    assert "post" in paths["/api/green-wave/offset-diagnostics"]


# ---------- POST /api/green-wave/slot-offsets ----------

def make_slot_request(payload):
    return SlotOffsetRequest.model_validate(payload)


def test_slot_offsets_payload_basic():
    req = make_slot_request(
        {
            "depart_from": 0,
            "depart_to": 10,
            "adjustable_index": 1,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 0, "travel": 0},  # 固定常绿
                {"cycle": 60, "offset": 25, "green_start": 20,
                 "green_end": 40, "travel": 0},  # 可调
            ],
        }
    )
    resp = green_wave_slot_offsets(req)
    assert resp.adjustable_index == 1
    assert [[w.start, w.end] for w in resp.feasible_intervals] == [[20, 31]]
    assert resp.suggested_offset == 25


def test_slot_offsets_wrapping_intervals():
    req = make_slot_request(
        {
            "depart_from": 52,
            "depart_to": 57,
            "adjustable_index": 0,
            "intersections": [
                {"cycle": 60, "offset": 3, "green_start": 50,
                 "green_end": 10, "travel": 0},
            ],
        }
    )
    resp = green_wave_slot_offsets(req)
    assert [[w.start, w.end] for w in resp.feasible_intervals] == [
        [0, 14], [58, 60],
    ]
    # 原 offset=3 本身就在可行区间 [0,14) 内
    assert resp.suggested_offset == 3


def test_slot_offsets_empty_gives_null_suggestion():
    req = make_slot_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "adjustable_index": 1,
            "intersections": [
                # 固定路口绿灯只有 [0,30)，无法整段覆盖 [0,60)
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0},
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 0, "travel": 0},
            ],
        }
    )
    resp = green_wave_slot_offsets(req)
    assert resp.feasible_intervals == []
    assert resp.suggested_offset is None


def test_slot_offsets_rejects_index_out_of_range():
    req = make_slot_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "adjustable_index": 2,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0},
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0},
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        green_wave_slot_offsets(req)
    assert exc.value.status_code == 422


def test_slot_offsets_rejects_negative_index():
    with pytest.raises(ValidationError):
        make_slot_request(
            {
                "depart_from": 0,
                "depart_to": 60,
                "adjustable_index": -1,
                "intersections": [
                    {"cycle": 60, "offset": 0, "green_start": 0,
                     "green_end": 30, "travel": 0},
                ],
            }
        )


def test_slot_offsets_reuses_422_validation():
    # 沿用既有路口与发车范围校验：offset 越界仍是 422
    req = make_slot_request(
        {
            "depart_from": 0,
            "depart_to": 60,
            "adjustable_index": 0,
            "intersections": [
                {"cycle": 60, "offset": 60, "green_start": 0,
                 "green_end": 30, "travel": 0},
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        green_wave_slot_offsets(req)
    assert exc.value.status_code == 422

    # 发车范围超过 3600 秒仍是 422
    req2 = make_slot_request(
        {
            "depart_from": 0,
            "depart_to": 3601,
            "adjustable_index": 0,
            "intersections": [
                {"cycle": 60, "offset": 0, "green_start": 0,
                 "green_end": 30, "travel": 0},
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        green_wave_slot_offsets(req2)
    assert exc.value.status_code == 422


def test_slot_offsets_route_is_in_openapi():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/green-wave/slot-offsets" in paths
    assert "post" in paths["/api/green-wave/slot-offsets"]
