"""干线绿波发车窗口核心算法。

所有时间量均为整数秒，路口信号以固定周期循环。

相位约定
--------
对路口 i，给定：

* ``cycle``  : 信号周期 C（秒，正整数）；
* ``offset`` : 相位偏移 o（0 <= o < C），绝对时间 t 在该路口的本地相位为
               ``(t + o) mod C``；
* ``green_start`` / ``green_end`` : 周期内绿灯半开区间端点，取值 [0, C)：
    - g_start < g_end：绿灯为 ``[g_start, g_end)``；
    - g_start > g_end：绿灯跨零点，为 ``[g_start, C) ∪ [0, g_end)``；
    - g_start == g_end：整周期常绿 ``[0, C)``；
* ``travel`` : 从起点到该路口的行驶秒数下限 T（默认即固定行驶时间）；
* ``travel_max`` : 可选的行驶秒数上限，缺省等于 ``travel``。实际行驶时间
  可取闭区间 ``[T, T_max]`` 内的**任意实数**秒，出发窗口必须对其中每一种
  取值都保证遇绿。

出发时刻为 t 时，抵达时刻覆盖闭区间 ``[t + T, t + T_max]``。令波动量
``slack = T_max - T``，在展开（不绕零点）的时间轴上，绿灯半开区间 ``[a,b)``
能容下整个抵达闭区间，当且仅当 ``a <= t+T+o`` 且 ``t+T_max+o < b``，即
绿灯段被右端收缩为 ``[a, b - slack)``（slack >= 段长时该路口永不可行）。
跨零点绿灯须先视为连续时段 ``[g_start, C + g_end)`` **再收缩**，不得拆成
两段分别收缩；整周期常绿不受任何波动影响。每个路口收缩后的可行出发时刻是
一组周期重复的半开整数区间 ``[kC + a - shift, kC + b - shift)``
（shift = (T + o) mod C），再与请求的发车范围
``[depart_from, depart_to)`` 求交；各路口结果两两求交并合并相邻
（端点相接）区间，即得全部极大半开发车窗口。全程只做区间运算，不逐秒试探。

最大覆盖
--------
:func:`compute_max_coverage` 复用上述**单路口可行窗口**：对范围内每个整数
出发时刻，统计"行驶时间取 [T, T_max] 内任意实数仍遇绿"的路口数（覆盖数）。
覆盖数只可能在某个可行窗口的端点处变化，故把每个半开窗口 ``[a,b)`` 记为
``a`` 处 +1、``b`` 处 -1 的差分事件，按位置排序后逐段扫描即可，不逐秒统计。
取全局最大覆盖数，合并相邻（端点相接）的最优段，即得全部极大半开发车区间；
最大值为 0 时没有任何事件，唯一的极大区间即完整发车范围。

可调路口 offset 寻优（slot-offsets）
------------------------------------
:func:`compute_slot_offsets` 中，除可调路口外的其余路口 offset 固定，它们的
可行窗口（同样含波动收缩）必须**完整覆盖**整段半开发车范围
``[depart_from, depart_to)``——窗口端点都是整数，覆盖范围内每个整数秒与连续
覆盖该半开区间等价。

对可调路口，令范围长度 ``L = depart_to - depart_from``。在已做行驶波动收缩
（跨零点绿灯先视为连续段再收缩）的基础上再做**整段时隙收缩**：连续 L 个整数
出发时刻都可行，当且仅当长度 L 的整数弧整体落入某个周期重复的收缩绿灯分量
``[kC+a, kC+b)``，即起点相位被允许在长度 ``b-a-L`` 的余量区间内。跨零点绿灯
经波动收缩后的分量可以长于一个周期，故余量区间也可能跨过零点；周期圆上旋转
回 offset 后在 ``[0, C)`` 内分段表示，即得全部极大半开可行 offset 区间。
"""

from __future__ import annotations

from typing import Iterable

# 周期上限仅用于防御异常输入，一日之内足够覆盖任何实际信号周期。
MAX_CYCLE = 86_400
MAX_WINDOW_SECONDS = 3_600
MAX_INTERSECTIONS = 8
MAX_OBSERVATIONS = 2_000

Interval = list[int]  # 长度为 2 的半开区间 [start, end)


def local_green_intervals(cycle: int, green_start: int, green_end: int) -> list[Interval]:
    """展开单个周期 [0, C) 内的绿灯半开区间。

    端点相等时视为整周期常绿；跨零点时展开为两段。
    """
    if green_start == green_end:
        return [[0, cycle]]
    if green_start < green_end:
        return [[green_start, green_end]]
    return [[green_start, cycle], [0, green_end]]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """合并重叠或端点相接的半开区间（[a,b) 与 [b,c) 合并为 [a,c)）。"""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def clip_intervals(
    intervals: Iterable[Interval], lower: int, upper: int
) -> list[Interval]:
    """把半开区间裁剪进 [lower, upper)。"""
    clipped: list[Interval] = []
    for start, end in intervals:
        start = max(start, lower)
        end = min(end, upper)
        if start < end:
            clipped.append([start, end])
    return clipped


def eroded_green_components(
    cycle: int,
    green_start: int,
    green_end: int,
    slack: int,
) -> tuple[bool, list[Interval]]:
    """波动量 slack 下、每个周期内的"连续"绿灯分量（出发轴视角）。

    返回 ``(always_green, components)``：

    * ``green_start == green_end``（整周期常绿）：返回 ``(True, [])``，
      常绿不受行驶时间波动影响；
    * 普通绿灯 ``[g_start, g_end)``：右端收缩为
      ``[g_start, g_end - slack)``，slack >= 绿灯长度时为空；
    * 跨零点绿灯：**先**视为连续时段 ``[g_start, C + g_end)`` **再收缩**
      为 ``[g_start, C + g_end - slack)``（可能长于一个周期）。

    收缩是针对"抵达闭区间整体落入绿灯半开区间"的最坏情形：
    到达最早时刻可压在左端点（含），到达最晚时刻必须严格早于右端点。
    """
    if green_start == green_end:
        return True, []
    if green_start < green_end:
        if slack >= green_end - green_start:
            return False, []
        return False, [[green_start, green_end - slack]]
    # 跨零点：先视为连续的 [g_start, C + g_end)，再做右端收缩。
    extended_end = cycle + green_end - slack
    if extended_end <= green_start:
        return False, []
    return False, [[green_start, extended_end]]


def departure_windows_for_intersection(
    cycle: int,
    offset: int,
    green_start: int,
    green_end: int,
    travel: int,
    depart_from: int,
    depart_to: int,
    travel_max: int | None = None,
) -> list[Interval]:
    """单个路口在 [depart_from, depart_to) 内的全部可行出发区间（已合并）。

    ``travel_max`` 缺省等于 ``travel``（无波动）。行驶时间可能取闭区间
    [travel, travel_max] 内任意实数秒时，只有对所有取值均遇绿的出发时刻
    才会被保留。
    """
    if travel_max is None:
        travel_max = travel
    slack = travel_max - travel
    always_green, components = eroded_green_components(
        cycle, green_start, green_end, slack
    )
    if always_green:
        return [[depart_from, depart_to]]
    # (t + T + o) mod C 与 (t + shift) mod C 等价；slack 只影响绿灯长度。
    shift = (travel + offset) % cycle

    raw: list[Interval] = []
    for local_start, local_end in components:
        # 本地（已收缩）绿灯 [a, b) 对应出发区间 [kC + a - shift, kC + b - shift)。
        # 只需枚举与发车范围有非空交的周期 k：
        #   kC + b - shift > depart_from  ⇔  k > (depart_from - b + shift) / C
        #   kC + a - shift < depart_to    ⇔  k < (depart_to   - a + shift) / C
        k_min = (depart_from - local_end + shift) // cycle + 1
        k_max = -((-(depart_to - local_start + shift)) // cycle) - 1
        for k in range(k_min, k_max + 1):
            base = k * cycle
            raw.append(
                [base + local_start - shift, base + local_end - shift]
            )

    return merge_intervals(clip_intervals(raw, depart_from, depart_to))


def intersect_interval_lists(
    left: list[Interval], right: list[Interval]
) -> list[Interval]:
    """两组各自有序、互不相交的半开区间列表的交集（双指针）。"""
    i = j = 0
    result: list[Interval] = []
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start < end:
            result.append([start, end])
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return result


def compute_windows(
    intersections: Iterable[dict],
    depart_from: int,
    depart_to: int,
) -> list[Interval]:
    """求所有路口均遇绿灯的全部极大半开发车区间，按起点排序。

    ``intersections`` 中的每个字典包含 cycle / offset / green_start /
    green_end / travel 字段，以及可选的 travel_max 字段（缺省等于 travel，
    表示行驶时间可能取 [travel, travel_max] 内任意实数秒），由 Pydantic 模型
    保证合法。
    """
    common: list[Interval] | None = None
    for item in intersections:
        windows = departure_windows_for_intersection(
            cycle=item["cycle"],
            offset=item["offset"],
            green_start=item["green_start"],
            green_end=item["green_end"],
            travel=item["travel"],
            travel_max=item.get("travel_max"),
            depart_from=depart_from,
            depart_to=depart_to,
        )
        if common is None:
            common = windows
        else:
            common = intersect_interval_lists(common, windows)
        if not common:
            return []
    # 求交不会产生相接区间，最后再合并一次以策安全。
    return merge_intervals(common or [])


def compute_max_coverage(
    intersections: Iterable[dict],
    depart_from: int,
    depart_to: int,
) -> tuple[int, list[Interval]]:
    """求范围内"最多有多少个路口任意行驶时长下都遇绿"及全部极大最优区间。

    对发车范围 ``[depart_from, depart_to)`` 内的每个整数出发时刻 t，覆盖数
    为满足下述条件的路口数：行驶时间取 ``[T, T_max]`` 内**任意实数**时抵达
    该路口都遇绿灯（即可行窗口的判定与 :func:`compute_windows` 完全一致，
    直接复用 :func:`departure_windows_for_intersection`）。

    返回 ``(最大覆盖数, 极大半开区间列表)``：区间按起点升序，区间内每个出发
    时刻的覆盖数都等于最大值，且区间两端已覆盖数下降或到达发车范围边界。
    采用区间端点事件扫描（每个可行窗口在起点 +1、终点 -1），覆盖数只在端点
    处变化，故不逐秒统计；最大值为 0（无任何事件）时返回
    ``(0, [[depart_from, depart_to]])``，即完整发车范围仍是唯一的极大区间。
    """
    # 事件：(位置, 增量)。半开窗口 [a,b) 内贡献 1，故 a 处 +1、b 处 -1。
    events: list[tuple[int, int]] = []
    for item in intersections:
        for start, end in departure_windows_for_intersection(
            cycle=item["cycle"],
            offset=item["offset"],
            green_start=item["green_start"],
            green_end=item["green_end"],
            travel=item["travel"],
            travel_max=item.get("travel_max"),
            depart_from=depart_from,
            depart_to=depart_to,
        ):
            events.append((start, 1))
            events.append((end, -1))

    if not events:
        # 没有任何路口在范围内可行（含范围上的退化情形）：覆盖数恒为 0。
        return 0, [[depart_from, depart_to]]

    events.sort()
    segments: list[tuple[int, int, int]] = []  # (起点, 终点, 覆盖数)
    coverage = 0
    prev = depart_from
    i = 0
    while i < len(events):
        pos = events[i][0]
        if prev < pos:
            segments.append((prev, pos, coverage))
        delta = 0
        while i < len(events) and events[i][0] == pos:
            delta += events[i][1]
            i += 1
        coverage += delta
        prev = pos
    if prev < depart_to:
        segments.append((prev, depart_to, coverage))

    maximum = max(seg[2] for seg in segments)
    # 合并相邻（端点相接）且同为最大覆盖数的段，得到全部极大半开区间。
    optimal: list[Interval] = []
    for start, end, value in segments:
        if value != maximum:
            continue
        if optimal and optimal[-1][1] == start:
            optimal[-1][1] = end
        else:
            optimal.append([start, end])
    return maximum, optimal


# ---------- 单路口 offset 诊断 ----------

Observation = tuple[int, bool]  # (arrival_time, observed_green)


def _rotate_intervals_on_circle(
    intervals: list[Interval], cycle: int, shift: int
) -> list[Interval]:
    """把 ``[0, C)`` 内一组半开整数区间在周期圆上整体平移 ``-shift``。

    平移保持长度与互不相交性：``[a, b)`` 平移后为长度不变的半开整数弧
    ``[(a-shift) mod C, ...)``，绕零点时断成两段。输入区间已合并且总长度
    不超过 C 时，输出经 :func:`merge_intervals` 合并相邻（端点相接）段后
    仍为有序互不相交的半开区间列表；输入为完整周期 ``[[0, C]]`` 时原样返回。
    """
    if intervals == [[0, cycle]]:
        return [[0, cycle]]
    shift %= cycle
    rotated: list[Interval] = []
    for a, b in intervals:
        length = b - a
        lo = (a - shift) % cycle
        if lo + length <= cycle:
            rotated.append([lo, lo + length])
        else:
            rotated.append([lo, cycle])
            tail = (lo + length) % cycle
            if tail:
                rotated.append([0, tail])
    return merge_intervals(rotated)


def _shifted_circle_intervals(
    cycle: int,
    green_start: int,
    green_end: int,
    shift: int,
) -> list[Interval]:
    """周期圆上的绿灯集合平移 -shift 后、落在 [0, C) 内的半开整数区间。

    即满足 ``(p + shift) mod C`` 落在绿灯集合中的 p 集合
    （本地绿灯 ``[a,b)`` 平移后为 ``[a-shift, b-shift) mod C``）。
    ``green_start == green_end``（整周期常绿）时返回 ``[[0, C]]``；
    跨零点的平移结果可能在 [0, C) 内断成两段。
    """
    if green_start == green_end:
        return [[0, cycle]]
    # 非跨零点绿灯 [gs, ge) 是一段；跨零点先视为连续段 [gs, C+ge)。
    raw = (
        [(green_start, green_end)]
        if green_start < green_end
        else [(green_start, cycle + green_end)]
    )
    return _rotate_intervals_on_circle(
        [[a, b] for a, b in raw], cycle, shift
    )


def _complement_in_cycle(intervals: list[Interval], cycle: int) -> list[Interval]:
    """[0, C) 内一组有序互不相交半开区间的补集（同为半开区间）。"""
    result: list[Interval] = []
    cursor = 0
    for start, end in intervals:
        if cursor < start:
            result.append([cursor, start])
        cursor = end
    if cursor < cycle:
        result.append([cursor, cycle])
    return result


def _mismatch_intervals_for_observation(
    cycle: int,
    green_start: int,
    green_end: int,
    arrival_time: int,
    observed_green: bool,
) -> list[Interval]:
    """单条观测的"预测灯色 != 观测灯色" offset 集合（[0,C) 内半开区间）。

    offset 预测灯色为绿，当且仅当 ``(arrival_time + offset) mod C``
    落在绿灯集合中；观测为绿时错配集合为其补集（预测为红），观测为红时
    错配集合即预测为绿的集合。
    """
    green_offsets = _shifted_circle_intervals(
        cycle, green_start, green_end, arrival_time % cycle
    )
    if not observed_green:
        return green_offsets
    return _complement_in_cycle(green_offsets, cycle)


def offset_diagnostics(
    cycle: int,
    green_start: int,
    green_end: int,
    observations: Iterable[Observation],
) -> tuple[int, list[Interval]]:
    """求最少错配条数及取到最小值的全部极大半开 offset 区间。

    对整数 ``offset ∈ [0, C)``，按 ``(arrival_time + offset) mod C``
    预测灯色（绿灯半开区间、跨零点、端点相等为常绿的语义与其余接口一致），
    统计预测与 ``observed_green`` 不符的观测条数。返回
    ``(最少错配条数, 最优 offset 区间列表)``，区间按起点升序。

    采用周期区间事件扫描：每条观测的错配集合至多两条半开区间，仅在区间
    端点放置 +1/-1 差分事件，按事件位置排序后逐段维护当前错配数，全程不
    枚举 offset × 观测（复杂度 O(n log n)，与 cycle 大小无关）。跨零点的
    最优集合天然在 [0, C) 内分段表示；同错配数的相邻段合并为极大区间。
    """
    # 事件：(位置, 增量)。错配数只在整数区间端点处变化，段内恒定。
    events: list[tuple[int, int]] = []
    for arrival_time, observed_green in observations:
        for start, end in _mismatch_intervals_for_observation(
            cycle, green_start, green_end, arrival_time, observed_green
        ):
            events.append((start, 1))
            events.append((end, -1))

    if not events:
        # 无任何错配事件 ⇔ 所有观测均与整周期常绿一致：每个 offset 都最优。
        return 0, [[0, cycle]]

    events.sort()
    segments: list[tuple[int, int, int]] = []  # (起点, 终点, 错配数)
    mismatches = 0
    prev = 0
    i = 0
    while i < len(events):
        pos = events[i][0]
        if prev < pos:
            segments.append((prev, pos, mismatches))
        delta = 0
        while i < len(events) and events[i][0] == pos:
            delta += events[i][1]
            i += 1
        mismatches += delta
        prev = pos
    if prev < cycle:
        segments.append((prev, cycle, mismatches))

    minimum = min(seg[2] for seg in segments)
    # 合并相邻且同为最小错配数的段，得到全部极大半开区间。
    optimal: list[Interval] = []
    for start, end, value in segments:
        if value != minimum:
            continue
        if optimal and optimal[-1][1] == start:
            optimal[-1][1] = end
        else:
            optimal.append([start, end])
    return minimum, optimal


# ---------- 可调路口 offset 寻优 ----------


def _feasible_slot_offsets_for_intersection(
    cycle: int,
    green_start: int,
    green_end: int,
    travel: int,
    travel_max: int,
    depart_from: int,
    depart_to: int,
) -> list[Interval]:
    """单个可调路口使整段每个整数秒都可发车的全部可行 offset（[0,C) 内）。

    行驶时间可能取 ``[travel, travel_max]`` 内任意实数，发车范围
    ``[depart_from, depart_to)`` 内**每个整数秒**都必须保证任意行驶时长下
    遇绿。返回取到该条件的全部极大半开整数 offset 区间（按起点升序，跨
    零点在 ``[0, C)`` 内分段）；整周期常绿时为 ``[[0, C]]``，永不可行时
    为空。

    推导（只做区间运算，不逐 offset 试探）：

    1. **行驶波动收缩**：跨零点绿灯先视为连续段再按
       :func:`eroded_green_components` 右端收缩 slack 秒；常绿直接返回整
       个周期。
    2. **整段时隙收缩**：令 ``L = depart_to - depart_from``。收缩绿灯分量
       ``[a, b)`` 周期重复为 ``[kC+a, kC+b)``，连续 L 个整数出发时刻
       ``t0..t0+L-1`` 都落在其中（最晚整数时刻 t0+L-1 加 slack 后仍须
       严格早于右端点），当且仅当整数起点相位满足
       ``kC+a <= t0+shift <= kC+b-L``（shift=(T+o) mod C），写成整数半开
       区间即 ``[kC+a, kC+b-L+1)``，经周期圆旋转后给出可行 offset。余量
       区间可能长于一个周期（跨零点绿灯收缩后 b-a 可大于 C），故周期 k 的
       枚举同时覆盖 k=-1 与 k=1 等相邻周期。
    """
    slack = travel_max - travel
    always_green, components = eroded_green_components(
        cycle, green_start, green_end, slack
    )
    if always_green:
        return [[0, cycle]]

    length = depart_to - depart_from
    raw_phase: list[Interval] = []
    for a, b in components:
        if b - a < length:
            # 波动收缩后的连续绿灯分量容不下整段时隙：任何相位都无解。
            return []
        # r = (depart_from + T + o) mod C；r 落入 [kC+a, kC+b-L+1)（整数半开）。
        # 枚举余量区间与 [0, C) 有非空交的周期 k：
        #   kC + a <= C - 1   ⇔  k <= (C - 1 - a) / C
        #   kC + b - L + 1 > 0 ⇔  k > (L - b - 1) / C
        k_min = -((b - length + 1) // cycle)  # floor((L-b-1)/C) + 1
        k_max = (cycle - 1 - a) // cycle
        for k in range(k_min, k_max + 1):
            base = k * cycle
            raw_phase.append([base + a, base + b - length + 1])

    phase_windows = clip_intervals(raw_phase, 0, cycle)
    if not phase_windows:
        return []
    # o ≡ r - depart_from - T (mod C)：在周期圆上旋转 -(depart_from + T)。
    return _rotate_intervals_on_circle(
        merge_intervals(phase_windows),
        cycle,
        (depart_from + travel) % cycle,
    )


def _nearest_ring_offset(
    intervals: list[Interval], original: int, cycle: int
) -> int | None:
    """可行区间集合中距 ``original`` 环形距离最小的整数 offset。

    环形距离 ``min(|o - original|, C - |o - original|)``；等距时取较小
    offset。可行集合以 ``[0, C)`` 内分段表示，距离沿周期圆度量，最小距离
    只可能取在：各区间端点、``original`` 本身可行处，以及跨零点集合在圆
    上相连时的接缝端点 0 与 C-1。收集这些候选（再按是否属于可行集合过滤）
    逐一比较即可。
    """
    best: int | None = None
    best_key: tuple[int, int] | None = None
    candidates = {0, cycle - 1}
    for start, end in intervals:
        candidates.add(start)
        candidates.add(end - 1)
        if start <= original < end:
            candidates.add(original)
    for candidate in candidates:
        if not any(start <= candidate < end for start, end in intervals):
            continue
        delta = abs(candidate - original)
        distance = min(delta, cycle - delta)
        key = (distance, candidate)
        if best_key is None or key < best_key:
            best_key, best = key, candidate
    return best


def compute_slot_offsets(
    intersections: Iterable[dict],
    adjustable_index: int,
    depart_from: int,
    depart_to: int,
) -> tuple[list[Interval], int | None]:
    """求可调路口保证整段逐秒可发车的全部极大半开可行 offset 区间。

    ``intersections`` 参数同 :func:`compute_windows`（由 Pydantic 保证
    合法）；``adjustable_index`` 指定唯一可调路口（从 0 起），其余路口
    保持各自原 offset 不变。可行条件：

    * 每个**固定**路口在原 offset 下的可行窗口必须完整覆盖半开发车范围
      ``[depart_from, depart_to)``（端点均为整数，覆盖每个整数秒等价于
      连续覆盖整段）；任一固定路口做不到，可行集即为空；
    * **可调**路口需在其自身周期/绿灯/行驶波动下使范围内每个整数秒均可
      发车（见 :func:`_feasible_slot_offsets_for_intersection`，跨零点绿灯
      先连续化再波动收缩、再整段时隙收缩）。

    返回 ``(可行 offset 区间列表, 建议 offset)``：区间为 ``[0, C)`` 内
    有序、互不相交、跨零点分段表示的极大半开整数区间；建议值为距该路口
    原 offset 环形距离最小者，等距取较小 offset；无可行值时为
    ``([], None)``。
    """
    nodes = list(intersections)
    target = nodes[adjustable_index]

    for index, item in enumerate(nodes):
        if index == adjustable_index:
            continue
        windows = departure_windows_for_intersection(
            cycle=item["cycle"],
            offset=item["offset"],
            green_start=item["green_start"],
            green_end=item["green_end"],
            travel=item["travel"],
            travel_max=item.get("travel_max"),
            depart_from=depart_from,
            depart_to=depart_to,
        )
        if windows != [[depart_from, depart_to]]:
            return [], None

    feasible = _feasible_slot_offsets_for_intersection(
        cycle=target["cycle"],
        green_start=target["green_start"],
        green_end=target["green_end"],
        travel=target["travel"],
        travel_max=(
            target["travel"]
            if target.get("travel_max") is None
            else target["travel_max"]
        ),
        depart_from=depart_from,
        depart_to=depart_to,
    )
    if not feasible:
        return [], None
    suggestion = _nearest_ring_offset(
        feasible, target["offset"], target["cycle"]
    )
    return feasible, suggestion
