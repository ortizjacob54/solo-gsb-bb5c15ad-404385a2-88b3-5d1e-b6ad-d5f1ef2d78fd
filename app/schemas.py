"""请求与响应的 Pydantic 模型及输入校验。"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .greenwave import MAX_CYCLE, MAX_INTERSECTIONS, MAX_OBSERVATIONS, MAX_WINDOW_SECONDS


class Intersection(BaseModel):
    """单个路口的信号与行程参数，全部为整数秒。"""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(
        default=None, max_length=64, description="可选的路口名称，仅用于辨识"
    )
    cycle: int = Field(
        ..., ge=1, le=MAX_CYCLE, description="信号周期 C（秒），1..86400"
    )
    offset: int = Field(..., ge=0, description="相位偏移 o（秒），需满足 0 <= o < C")
    green_start: int = Field(
        ..., ge=0, description="绿灯起点（本地相位秒），需满足 0 <= g_start < C"
    )
    green_end: int = Field(
        ..., ge=0, description="绿灯终点（本地相位秒，不含），需满足 0 <= g_end < C"
    )
    travel: int = Field(
        ..., ge=0, le=MAX_CYCLE, description="从起点到该路口的行驶秒数下限 T"
    )
    travel_max: int | None = Field(
        default=None,
        ge=0,
        description=(
            "行驶秒数上限 T_max（可选，缺省等于 travel）；实际行驶时间可取"
            "闭区间 [travel, travel_max] 内任意实数秒"
        ),
    )

    @property
    def effective_travel_max(self) -> int:
        """缺省时 travel_max 等于 travel。"""
        return self.travel if self.travel_max is None else self.travel_max

    def validate_against_cycle(self) -> None:
        """校验所有以周期为上界的字段；不合法时抛出 HTTP 422。"""
        errors: list[str] = []
        label = self.name or f"cycle={self.cycle}"
        if not 0 <= self.offset < self.cycle:
            errors.append(f"offset 必须满足 0 <= offset < cycle（路口 {label}）")
        if not 0 <= self.green_start < self.cycle:
            errors.append(
                f"green_start 必须满足 0 <= green_start < cycle（路口 {label}）"
            )
        if not 0 <= self.green_end < self.cycle:
            errors.append(
                f"green_end 必须满足 0 <= green_end < cycle（路口 {label}）"
            )
        if self.effective_travel_max > MAX_CYCLE:
            errors.append(
                f"travel_max 不得大于 86400（路口 {label}）"
            )
        if self.effective_travel_max < self.travel:
            errors.append(
                f"travel_max 不得小于 travel（路口 {label}）"
            )
        if errors:
            raise HTTPException(status_code=422, detail=errors)


class GreenWaveRequest(BaseModel):
    """绿波发车窗口请求。"""

    model_config = ConfigDict(extra="ignore")

    depart_from: int = Field(
        ..., ge=0, le=MAX_CYCLE, description="发车范围起点（秒，含）"
    )
    depart_to: int = Field(
        ..., ge=1, le=2 * MAX_CYCLE, description="发车范围终点（秒，不含）"
    )
    intersections: list[Intersection] = Field(
        ..., min_length=1, max_length=MAX_INTERSECTIONS,
        description="路口列表，1..8 个",
    )

    def validate_ranges(self) -> None:
        """跨字段校验：相位上界与发车范围长度。"""
        errors: list[str] = []
        length = self.depart_to - self.depart_from
        if length <= 0:
            errors.append("depart_to 必须大于 depart_from（半开发车范围）")
        elif length > MAX_WINDOW_SECONDS:
            errors.append("发车范围长度不得超过 3600 秒（一小时）")

        for intersection in self.intersections:
            try:
                intersection.validate_against_cycle()
            except HTTPException as exc:
                detail = exc.detail
                if isinstance(detail, list):
                    errors.extend(detail)
                else:
                    errors.append(str(detail))

        if errors:
            raise HTTPException(status_code=422, detail=errors)


class Window(BaseModel):
    """一个极大半开发车区间 [start, end)。"""

    start: int = Field(..., description="窗口起点（秒，含）")
    end: int = Field(..., description="窗口终点（秒，不含）")


GreenWaveResponse = list[Window]


class MaxCoverageResponse(BaseModel):
    """最大绿波覆盖结果：全局最大遇绿路口数及取到该值的全部极大发车区间。"""

    max_coverage: int = Field(
        ..., ge=0, description="发车范围内任意出发时刻可遇绿路口数的全局最大值"
    )
    optimal_intervals: list[Window] = Field(
        ...,
        description=(
            "覆盖数取到最大值的全部极大半开发车区间 [start,end)，按起点升序；"
            "最大值为 0 时为完整的请求发车范围 "
            "[depart_from, depart_to)"
        ),
    )


class OffsetObservation(BaseModel):
    """一条车辆到达观测：整数秒绝对到达时刻与当时是否绿灯。"""

    model_config = ConfigDict(extra="ignore")

    arrival_time: int = Field(
        ..., description="车辆到达时刻 t（整数秒，可为任意整数，按周期取模）"
    )
    observed_green: bool = Field(
        ..., description="到达时刻该路口实际灯色：true=绿，false=红"
    )


class OffsetDiagnosticsRequest(BaseModel):
    """单路口 offset 诊断请求。"""

    model_config = ConfigDict(extra="ignore")

    cycle: int = Field(
        ..., ge=1, le=MAX_CYCLE, description="信号周期 C（秒），1..86400"
    )
    green_start: int = Field(
        ..., ge=0, description="绿灯起点（本地相位秒），需满足 0 <= green_start < C"
    )
    green_end: int = Field(
        ..., ge=0, description="绿灯终点（本地相位秒，不含），需满足 0 <= green_end < C"
    )
    observations: list[OffsetObservation] = Field(
        ..., min_length=1, max_length=MAX_OBSERVATIONS,
        description="到达观测列表，1..2000 条",
    )

    def validate_ranges(self) -> None:
        """跨字段校验：绿灯相位端点必须在一个周期内；非法时抛 HTTP 422。"""
        errors: list[str] = []
        if not 0 <= self.green_start < self.cycle:
            errors.append("green_start 必须满足 0 <= green_start < cycle")
        if not 0 <= self.green_end < self.cycle:
            errors.append("green_end 必须满足 0 <= green_end < cycle")
        if errors:
            raise HTTPException(status_code=422, detail=errors)


class OffsetInterval(BaseModel):
    """一个取到最少错配数的极大半开 offset 区间 [start, end)。"""

    start: int = Field(..., ge=0, description="offset 区间起点（秒，含）")
    end: int = Field(..., ge=1, description="offset 区间终点（秒，不含）")


class OffsetDiagnosticsResponse(BaseModel):
    """offset 诊断结果：最少错配条数及取到该值的全部极大半开 offset 区间。"""

    min_mismatches: int = Field(
        ..., ge=0, description="所有整数 offset∈[0,cycle) 中最少的预测错配观测条数"
    )
    optimal_intervals: list[OffsetInterval] = Field(
        ...,
        description=(
            "取到最少错配数的全部极大半开 offset 区间 [start,end)，"
            "整数 offset 满足 start <= offset < end；按起点升序；"
            "跨零点的最优集合在 [0,cycle) 内分段表示"
        ),
    )


class SlotOffsetRequest(GreenWaveRequest):
    """可调路口 offset 寻优请求：复用路口参数与发车范围，另指定可调路口。"""

    adjustable_index: int = Field(
        ..., ge=0, description="唯一可调路口在 intersections 中的下标（从 0 起）"
    )

    def validate_ranges(self) -> None:
        """沿用绿波请求的全部 422 校验，并额外校验可调路口下标上界。"""
        super().validate_ranges()
        if self.adjustable_index >= len(self.intersections):
            raise HTTPException(
                status_code=422,
                detail=[
                    "adjustable_index 必须满足 0 <= adjustable_index < 路口数"
                ],
            )


class SlotOffsetResponse(BaseModel):
    """可调路口 offset 寻优结果。"""

    adjustable_index: int = Field(
        ..., ge=0, description="请求中指定的可调路口下标（回显）"
    )
    feasible_intervals: list[OffsetInterval] = Field(
        ...,
        description=(
            "使发车范围内每个整数秒都可发车的全部极大半开整数 offset 区间 "
            "[start,end)（0 <= start < end <= cycle），按起点升序；"
            "跨零点的可行集合在 [0,cycle) 内分段表示；无可行值时为空数组"
        ),
    )
    suggested_offset: int | None = Field(
        ...,
        description=(
            "距该路口原 offset 环形距离最小的可行整数 offset；"
            "环形等距时取较小 offset；无可行值时为 null"
        ),
    )
