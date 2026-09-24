"""可调路口 offset 寻优核心算法测试：含逐 offset × 逐秒暴力对照。"""

import random

from app.greenwave import (
    _feasible_slot_offsets_for_intersection,
    _nearest_ring_offset,
    compute_slot_offsets,
)


def it(name=None, **kw):
    # 默认 green_start == green_end 表示整周期常绿，所有取值均满足 schema 约束。
    return {"cycle": 60, "offset": 0, "green_start": 0, "green_end": 0,
            "travel": 0, **kw}


def feasible_at(node, t, offset):
    """整数出发 t、给定 offset 下，行驶时间取 [T,Tmax] 任意实数是否都遇绿。

    与 test_greenwave.py 中的逐秒参考实现一致：抵达闭区间
    [t+T+o, t+Tmax+o] 必须整体落入展开时间轴上某个绿灯半开分量内。
    """
    c = node["cycle"]
    gs, ge = node["green_start"], node["green_end"]
    t0, t1 = node["travel"], node.get("travel_max", node["travel"])
    arrive_lo = t + t0 + offset
    arrive_hi = t + t1 + offset
    if gs == ge:
        return True
    for q in range(arrive_lo // c - 2, arrive_lo // c + 4):
        if gs < ge:
            a, b = q * c + gs, q * c + ge
        else:  # 跨零点：连续分量 [qC+gs, (q+1)C+ge)
            a, b = q * c + gs, (q + 1) * c + ge
        if a <= arrive_lo and arrive_hi < b:
            return True
    return False


def brute_feasible_offsets(node, lo, hi):
    """逐 offset × 逐整数出发秒的参考可行集合，压缩为极大半开整数区间。"""
    feasible = []
    for offset in range(node["cycle"]):
        if all(feasible_at(node, t, offset) for t in range(lo, hi)):
            feasible.append(offset)

    intervals = []
    run = None
    for offset in feasible:
        if run is None:
            run = [offset, offset + 1]
        elif offset == run[1]:
            run[1] = offset + 1
        else:
            intervals.append(run)
            run = [offset, offset + 1]
    if run is not None:
        intervals.append(run)
    return intervals


def brute_suggestion(intervals, original, cycle):
    best = None
    for start, end in intervals:
        for offset in range(start, end):
            delta = abs(offset - original)
            distance = min(delta, cycle - delta)
            key = (distance, offset)
            if best is None or key < best[0]:
                best = (key, offset)
    return None if best is None else best[1]


# ---------- 手工用例：基本收缩 ----------

def test_plain_green_shrunk_by_whole_slot():
    # 绿灯 [20,40)、行驶 0、范围 [0,10)：每个整数秒 0..9 都在绿灯内
    # ⇔ offset ∈ [20,31)（右端 40-10=30，半开 [20,31)）
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 0, 0, 0, 10)
    assert got == [[20, 31]]


def test_slot_length_equals_green_length_single_offset():
    # 绿灯 [20,40) 长 20，范围长度也是 20：只有 offset=20 一个整数可行
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 0, 0, 0, 20)
    assert got == [[20, 21]]


def test_slot_longer_than_green_yields_empty():
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 0, 0, 0, 21)
    assert got == []


def test_travel_shifts_offset_windows():
    # 绿灯 [20,40)、行驶 15、范围 [100,110)（长度 10）：
    # r=(100+15+o)%60 ∈ [20,31) ⇔ o ∈ [25,36)
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 15, 15, 100, 110)
    assert got == [[25, 36]]


def test_wrapping_green_feasible_set_wraps_zero():
    # 跨零点绿灯 [50,60)∪[0,10) 连续长 20，范围长 5、行驶 0：
    # 连续弧起点相位 r ∈ [50,66)（绕零点）⇔ offset ∈ [0,6) ∪ [50,60)
    got = _feasible_slot_offsets_for_intersection(60, 50, 10, 0, 0, 0, 5)
    assert got == [[0, 6], [50, 60]]


def test_wrapping_green_set_wraps_zero_with_rotation():
    # 同上但 depart_from=55：o ≡ r-55 (mod 60)，[50,66) 与相邻周期余量
    # 共同旋转后为 [0,11) ∪ [55,60)
    got = _feasible_slot_offsets_for_intersection(60, 50, 10, 0, 0, 55, 60)
    assert got == [[0, 11], [55, 60]]


def test_wrapping_green_two_pieces():
    # 连续长 20、范围长 5、depart_from=52：余量旋转 -52 ⇒ [0,14) ∪ [58,60)
    got = _feasible_slot_offsets_for_intersection(60, 50, 10, 0, 0, 52, 57)
    assert got == [[0, 14], [58, 60]]


def test_always_green_returns_whole_cycle():
    got = _feasible_slot_offsets_for_intersection(
        60, 0, 0, 0, 86400, 100, 200
    )
    assert got == [[0, 60]]


def test_half_open_endpoint_excluded():
    # 绿灯 [20,30)、范围长 10：offset=20 时 t=0..9 遇绿（t=9 相位 29）；
    # offset=20 唯一可行；offset=21 时 t=9 相位 30 为红
    got = _feasible_slot_offsets_for_intersection(60, 20, 30, 0, 0, 0, 10)
    assert got == [[20, 21]]


def test_slack_and_slot_shrink_together():
    # 绿灯 [20,60) 长 40，行驶 [0,10]（slack=10），范围长度 20：
    # 波动收缩 [20,50)，再整段收缩：整数起点相位 ∈ [20,31)
    got = _feasible_slot_offsets_for_intersection(60, 20, 0, 0, 10, 0, 20)
    assert got == [[20, 31]]


def test_wrapping_green_slack_continuous_before_slot_shrink():
    # 跨零点 [50,60)∪[0,10) 连续长 20，行驶 [0,10] 收缩为 [50,60) 长 10，
    # 范围长度 5：整数起点相位 r ∈ [50,56) ⇔ offset ∈ [50,56)。
    # 若错误地拆成两段分别收缩会得到空集——本用例守护该语义。
    got = _feasible_slot_offsets_for_intersection(60, 50, 10, 0, 10, 0, 5)
    assert got == [[50, 56]]


def test_slack_eats_whole_green_yields_empty():
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 0, 20, 0, 5)
    assert got == []


def test_cycle_of_one_second():
    # 周期 1 常绿：唯一 offset=0 永远可行
    got = _feasible_slot_offsets_for_intersection(1, 0, 0, 0, 0, 0, 10)
    assert got == [[0, 1]]


def test_range_spanning_multiple_cycles_plain_green():
    # 绿灯 [20,40) 长 20 < 范围长度 120：整段不可能全部落在绿灯 ⇒ 空
    got = _feasible_slot_offsets_for_intersection(60, 20, 40, 0, 0, 0, 120)
    assert got == []


# ---------- 建议值 ----------

def test_suggestion_prefers_original_offset():
    intervals, suggestion = compute_slot_offsets(
        [it(cycle=60, offset=25, green_start=20, green_end=40, travel=0)],
        0, 0, 10,
    )
    assert intervals == [[20, 31]]
    assert suggestion == 25  # 原 offset 本身可行


def test_suggestion_nearest_ring_distance():
    # 可行 [20,31)，原 offset=2：环形最近为 20（正向距离 18，比经零点近）
    nodes = [it(cycle=60, offset=2, green_start=20, green_end=40, travel=0)]
    intervals, suggestion = compute_slot_offsets(nodes, 0, 0, 10)
    assert intervals == [[20, 31]]
    assert suggestion == 20


def test_suggestion_ring_distance_across_zero():
    # 可行 [20,31)，原 offset=50：经零点到 30 距离 20，正向到 20 距离 30
    nodes = [it(cycle=60, offset=50, green_start=20, green_end=40, travel=0)]
    intervals, suggestion = compute_slot_offsets(nodes, 0, 0, 10)
    assert intervals == [[20, 31]]
    assert suggestion == 30


def test_suggestion_equidistant_takes_smaller():
    # C=60，可行 {2, 8}（两段单点），原 offset=5：距离同为 3，取 2
    assert _nearest_ring_offset([[2, 3], [8, 9]], 5, 60) == 2


def test_suggestion_across_zero():
    # 可行 [58,60)∪[0,2)，原 offset=0 可行取 0
    assert _nearest_ring_offset([[0, 2], [58, 60]], 0, 60) == 0
    # 原 offset=29：到 1 距离 28 最小
    assert _nearest_ring_offset([[0, 2], [58, 60]], 29, 60) == 1
    # 原 offset=59 本身就在 [58,60) 内：距离 0
    assert _nearest_ring_offset([[0, 2], [58, 60]], 59, 60) == 59
    # 原 offset=57：到 58 距离 1，比经零点到 0 的距离 3 近
    assert _nearest_ring_offset([[0, 2], [58, 60]], 57, 60) == 58
    # 原 offset=2（恰在 [0,2) 右端点外）：最近为 1
    assert _nearest_ring_offset([[0, 2], [58, 60]], 2, 60) == 1


def test_suggestion_empty_set_is_none():
    assert _nearest_ring_offset([], 0, 60) is None


# ---------- 多路口：固定路口约束 ----------

def test_fixed_intersection_must_cover_whole_range():
    # 固定路口绿灯 [0,30) 周期 60、行驶 0：范围 [0,120) 不能整段覆盖
    # （30..60、90..120 为红），可行集直接为空。
    nodes = [
        it(cycle=60, offset=0, green_start=0, green_end=30, travel=0),
        it(cycle=60, offset=0, green_start=0, green_end=0, travel=0),
    ]
    intervals, suggestion = compute_slot_offsets(nodes, 1, 0, 120)
    assert intervals == []
    assert suggestion is None


def test_fixed_intersection_full_range_ok():
    # 固定常绿路口 + 可调 [20,40) 路口：等价于单路口结果
    nodes = [
        it(cycle=60, offset=0, green_start=0, green_end=0, travel=0),
        it(cycle=60, offset=25, green_start=20, green_end=40, travel=0),
    ]
    intervals, suggestion = compute_slot_offsets(nodes, 1, 0, 10)
    assert intervals == [[20, 31]]
    assert suggestion == 25


def test_adjustable_intersection_only():
    nodes = [it(cycle=60, offset=0, green_start=10, green_end=50, travel=5)]
    intervals, suggestion = compute_slot_offsets(nodes, 0, 0, 30)
    # 波动 0、范围长 30：r=(5+o)%60 ∈ [10,21) ⇔ o ∈ [5,16)
    assert intervals == [[5, 16]]
    assert suggestion == 5


def test_fixed_node_blocks_even_though_adjustable_always_green():
    nodes = [
        it(cycle=60, offset=0, green_start=0, green_end=30, travel=0),
        it(cycle=60, offset=0, green_start=0, green_end=0, travel=0),
    ]
    # 范围 [0,30) 恰好整段在固定路口绿灯内：可调常绿 ⇒ 全周期可行
    intervals, suggestion = compute_slot_offsets(nodes, 1, 0, 30)
    assert intervals == [[0, 60]]
    assert suggestion == 0
    # 范围 [0,31) 固定路口 t=30 为红：空集
    assert compute_slot_offsets(nodes, 1, 0, 31) == ([], None)


def test_fixed_intersection_with_adjacent_merged_windows():
    # 固定路口绿灯跨零点 [50,60)∪[0,40)（连续长 50），行驶 0：
    # 范围 [0,30) 整段可行（在 [0,40) 内）；范围 [0,60) 则因 40..50 红灯失败
    nodes = [
        it(cycle=60, offset=0, green_start=50, green_end=40, travel=0),
        it(cycle=60, offset=7, green_start=0, green_end=0, travel=0),
    ]
    intervals, suggestion = compute_slot_offsets(nodes, 1, 0, 30)
    assert intervals == [[0, 60]]
    assert suggestion == 7
    assert compute_slot_offsets(nodes, 1, 0, 60) == ([], None)


# ---------- 随机暴力对照 ----------

def test_matches_brute_force_random():
    random.seed(20260924)
    for _ in range(500):
        c = random.randint(1, 60)
        gs = random.randint(0, c - 1)
        ge = random.randint(0, c - 1)
        travel = random.randint(0, 60)
        tmax = travel
        if random.random() < 0.5:
            tmax = travel + random.randint(0, 20)
        length = random.randint(1, 120)
        lo = random.randint(0, 120)
        hi = lo + length
        node = it(cycle=c, green_start=gs, green_end=ge,
                  travel=travel, travel_max=tmax)
        got = _feasible_slot_offsets_for_intersection(
            c, gs, ge, travel, tmax, lo, hi
        )
        expected = brute_feasible_offsets(node, lo, hi)
        assert got == expected, node

        original = random.randint(0, c - 1)
        assert _nearest_ring_offset(got, original, c) == brute_suggestion(
            got, original, c
        )


def test_matches_brute_force_random_multi_intersection():
    random.seed(424242)
    for _ in range(300):
        n_nodes = random.randint(1, 4)
        nodes = []
        for _ in range(n_nodes):
            c = random.randint(1, 60)
            gs = random.randint(0, c - 1)
            ge = random.randint(0, c - 1)
            travel = random.randint(0, 60)
            kwargs = dict(
                cycle=c,
                offset=random.randint(0, c - 1),
                green_start=gs,
                green_end=ge,
                travel=travel,
                travel_max=(
                    travel + random.randint(0, 20)
                    if random.random() < 0.5 else travel
                ),
            )
            nodes.append(it(**kwargs))
        length = random.randint(1, 120)
        lo = random.randint(0, 120)
        hi = lo + length
        adjustable = random.randint(0, n_nodes - 1)
        got_intervals, got_suggestion = compute_slot_offsets(
            nodes, adjustable, lo, hi
        )

        fixed_ok = all(
            all(
                feasible_at(nodes[i], t, nodes[i]["offset"])
                for t in range(lo, hi)
            )
            for i in range(n_nodes) if i != adjustable
        )
        expected = (
            brute_feasible_offsets(nodes[adjustable], lo, hi)
            if fixed_ok else []
        )
        assert got_intervals == expected
        target = nodes[adjustable]
        assert got_suggestion == brute_suggestion(
            expected, target["offset"], target["cycle"]
        )
