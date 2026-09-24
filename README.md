# 干线绿波发车窗口 API

基于 **Python 3.11 + FastAPI** 的干线（arterial）绿波发车窗口计算服务。

提供三个接口：

1. **绿波发车窗口** `POST /api/green-wave/windows`：给定干线上至多 8 个路口各自的
   信号周期、相位偏移、周期内绿灯半开区间（允许跨周期零点）以及从起点到该路口的
   行驶秒数（可选上限 `travel_max`，表示实际行驶时间可取闭区间
   `[travel, travel_max]` 内任意实数秒），并给定一个不超过 3600 秒（一小时）的整数秒
   **半开**发车范围，服务返回在该范围内出发、**对任意可能的行驶时间**抵达**每个**路口时
   都恰好遇到绿灯的**全部极大半开发车区间**，按起点升序排列；不存在任何可行窗口时返回空数组 `[]`。
2. **最大绿波覆盖** `POST /api/green-wave/max-coverage`：请求参数与上一个接口完全相同。
   对发车范围内的每个整数出发时刻，统计**行驶时间取区间内任意实数**抵达时都能遇到绿灯的
   路口数（覆盖数），返回全局**最大路口数** `max_coverage` 以及取到该值的**全部极大半开
   发车区间**（相邻最优段已合并，按起点升序）；当最大值为 0 时仍返回**完整发车范围**
   `[depart_from, depart_to)` 作为唯一区间。
3. **单路口 offset 诊断** `POST /api/green-wave/offset-diagnostics`：给定单个路口的
   `cycle`、`green_start`、`green_end` 及 1～2000 条 `{arrival_time, observed_green}`
   观测（时间均为整数秒），对每个整数 `offset ∈ [0, cycle)` 按
   `(arrival_time + offset) mod cycle` 预测灯色，返回**最少错配条数**以及取到该值的
   **全部极大半开 offset 区间**（按起点排序；跨零点的最优集合在 `[0, cycle)` 内分段表示）。

## 目录结构

```
.
├── app/
│   ├── __init__.py
│   ├── greenwave.py      # 纯算法：周期展开 + 区间求交，无逐秒试探
│   ├── schemas.py        # Pydantic 请求/响应模型与输入校验
│   └── main.py           # FastAPI 入口与路由
├── tests/                # pytest 测试（含随机用例的逐秒/逐 offset 对照）
├── conftest.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## 一条命令启动（Docker Compose，推荐）

需要本机已安装 Docker 与 Docker Compose 插件（Docker Desktop 自带）。在仓库根目录执行：

```bash
docker compose up --build -d
```

仅此一条命令即可完成镜像构建、依赖安装并在后台启动服务。启动后服务监听宿主机
**8000 端口**，直接访问 <http://localhost:8000/docs> 即可看到交互式文档。

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

> 旧版独立命令 `docker-compose up --build -d` 同样可用。

### 无 Docker 时的本地启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

同样通过 <http://localhost:8000/> 访问。

## API 地址与端口

| 用途 | 地址 |
| --- | --- |
| 健康检查 | `GET http://localhost:8000/health` |
| 绿波窗口计算 | `POST http://localhost:8000/api/green-wave/windows` |
| 最大绿波覆盖 | `POST http://localhost:8000/api/green-wave/max-coverage` |
| 单路口 offset 诊断 | `POST http://localhost:8000/api/green-wave/offset-diagnostics` |
| 交互式文档（Swagger UI） | `http://localhost:8000/docs` |
| OpenAPI 描述 | `http://localhost:8000/openapi.json` |

## 必要配置

所有配置均有默认值，不改任何文件即可启动：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_PORT` | `8000` | **宿主机**暴露端口（容器内固定监听 8000）。8000 被占用时：`cp .env.example .env` 后改成如 `APP_PORT=8080`，再重新 `docker compose up -d` |
| `LOG_LEVEL` | `info` | uvicorn 日志级别（`critical`/`error`/`warning`/`info`/`debug`） |

## 时间与相位语义（重要约定）

所有时间量均为**整数秒**。对路口 *i*：

- `cycle`：信号周期 `C`（秒），`1 <= C <= 86400`；
- `offset`：相位偏移 `o`，`0 <= o < C`。绝对时刻 `t` 在该路口的本地相位为
  `(t + o) mod C`；
- `green_start` / `green_end`：周期内绿灯**半开区间**端点，均满足 `0 <= g < C`：
  - `green_start < green_end`：绿灯为 `[green_start, green_end)`；
  - `green_start > green_end`：绿灯**跨周期零点**，展开为
    `[green_start, C) ∪ [0, green_end)`；
  - `green_start == green_end`：整周期常绿 `[0, C)`；
- `travel`：从起点到该路口的行驶秒数**下限** `T >= 0`；
- `travel_max`（可选）：行驶秒数**上限** `T_max`，缺省等于 `travel`。实际行驶时间
  可取**闭区间** `[T, T_max]` 内的**任意实数秒**（如路况波动），窗口必须对其中每一种
  取值都保证遇绿；约束为 `0 <= T <= T_max <= 86400`。
- 发车范围为半开区间 `[depart_from, depart_to)`，长度 `1 .. 3600` 秒。

因此出发时刻 `t` 对该路口可行，当且仅当：**所有**实际行驶时间 `x ∈ [T, T_max]`
下，`(t + x + o) mod C` 都落在绿灯相位集合中。即抵达时刻覆盖闭区间
`[t+T+o, t+T_max+o]`，该闭区间必须整体落入展开（不绕零点）时间轴上的某个绿灯
**半开**区间：左端可压在绿灯起点（含），右端必须严格早于绿灯终点。令波动量
`slack = T_max - T`，等价于把每个连续绿灯段从右端收缩 `slack` 秒
（`[a,b)` → `[a, b-slack)`，slack 达到段长时该路口无解）。**跨周期零点的绿灯先视为
一条连续时段 `[green_start, C + green_end)` 再收缩**；`green_start == green_end`
的整周期常绿不受任何波动影响。

输出窗口同为半开区间 `[start, end)`：`start` 时刻可行、`end` 时刻不可行。

## 请求与响应

请求体：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `depart_from` | int | `>= 0`，发车范围起点（含） |
| `depart_to` | int | `> depart_from`，且 `depart_to - depart_from <= 3600` |
| `intersections` | array | 1..8 个路口 |
| `intersections[].name` | string? | 可选名称，仅用于辨识 |
| `intersections[].cycle` | int | `1..86400` |
| `intersections[].offset` | int | `0 <= offset < cycle` |
| `intersections[].green_start` | int | `0 <= green_start < cycle` |
| `intersections[].green_end` | int | `0 <= green_end < cycle` |
| `intersections[].travel` | int | `0 <= travel <= 86400`，行驶秒数下限 |
| `intersections[].travel_max` | int? | 可选，`travel <= travel_max <= 86400`，缺省等于 `travel`；实际行驶时间可取 `[travel, travel_max]` 内任意实数秒 |

成功响应为窗口数组（可能为空）：

```json
[ { "start": 0, "end": 30 }, { "start": 60, "end": 90 } ]
```

### 示例 1：两路口绿波带

两个周期 60 秒的路口，绿灯均为本地相位 `[0,30)`；路口 1 在起点（行驶 0 秒），
路口 2 行驶 30 秒，且下游相位偏移 `offset=30` 恰好补偿行程时间（即下游信号
比上游晚 30 秒启绿）。发车范围 `[0,300)`：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/windows \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 300,
    "intersections": [
      {"cycle": 60, "offset": 0,  "green_start": 0,  "green_end": 30, "travel": 0},
      {"cycle": 60, "offset": 30, "green_start": 0,  "green_end": 30, "travel": 30}
    ]
  }'
```

响应（每周期内前 30 秒出发可全程遇绿）：

```json
[{"start": 0, "end": 30}, {"start": 60, "end": 90},
 {"start": 120, "end": 150}, {"start": 180, "end": 210},
 {"start": 240, "end": 270}]
```

### 示例 2：绿灯跨零点

绿灯相位为 `[50,60) ∪ [0,10)`，行驶 5 秒，发车范围 `[0,125)`：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/windows \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 125,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 50, "green_end": 10, "travel": 5}
    ]
  }'
```

响应（跨零点的本地绿灯被展开后与发车范围求交）：

```json
[{"start": 0, "end": 5}, {"start": 45, "end": 65}, {"start": 105, "end": 125}]
```

### 示例 3：无解

两个路口的可行时段互不相交时返回空数组：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/windows \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 60,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 0,  "green_end": 10, "travel": 0},
      {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 30, "travel": 0}
    ]
  }'
# []
```

### 示例 4：行驶时间波动（travel_max）

实际行驶时间可能在 `[travel, travel_max]` 内浮动时，窗口必须保证**最坏情况下**也遇绿。
绿灯 `[20,40)`、行驶时间可能取 `[0,10]` 任意实数秒：早到可压在第 20 秒（含），
最晚到达（t+10）必须严格早于第 40 秒，因此窗口由 20 秒收缩为 10 秒：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/windows \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 120,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 40,
       "travel": 0, "travel_max": 10}
    ]
  }'
```

响应（与固定行驶 0 秒时的 `[20,40) [80,100)` 相比，每段右端收缩 10 秒）：

```json
[{"start": 20, "end": 30}, {"start": 80, "end": 90}]
```

跨零点的绿灯先当作连续时段再收缩。绿灯为 `[50,60) ∪ [0,10)`（连续长度 20 秒）、
行驶时间 `[0,10]` 时，只有在 `[50,60)` 内出发才能保证任意行驶时长下全程遇绿
（若拆成两段分别收缩，则绕零点后的 10 秒会被错误丢弃）：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/windows \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 130,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 50, "green_end": 10,
       "travel": 0, "travel_max": 10}
    ]
  }'
# [{"start": 50, "end": 60}, {"start": 110, "end": 120}]
```

若波动量达到或超过（连续）绿灯长度（如绿灯 20 秒而 `travel_max - travel = 20`），
任何出发时刻都无法保证遇绿，该路口（进而整个请求）返回 `[]`；整周期常绿
（`green_start == green_end`）不受波动影响。省略 `travel_max` 时语义与旧版完全一致。

## 最大绿波覆盖

`POST /api/green-wave/max-coverage` 的**请求体与 `/api/green-wave/windows` 完全相同**
（同样的发车范围、路口参数与 422 校验规则），但不再要求所有路口同时可行，而是回答：
在给定发车范围内，最好的出发时刻能"稳过"几个路口？

- `max_coverage`：范围内任意整数出发时刻，**行驶时间取 `[T, T_max]` 内任意实数**
  抵达都遇绿的路口数的**全局最大值**；
- `optimal_intervals`：覆盖数恰好等于最大值的**全部极大半开**发车区间
  `[start, end)`，按起点升序。两个端点相接的最优段会被合并（如路口 A 的窗口
  `[0,30)` 与路口 B 的窗口 `[30,40)` 覆盖数同为最大值 1，则合并为 `[0,40)`）；
  中间隔着覆盖数更低的时段则分段表示。
- 当最大值为 **0**（例如唯一的路口因波动量过大而永不可行）时，仍返回**完整发车范围**
  `[{"start": depart_from, "end": depart_to}]`：范围内每个时刻的覆盖数都为 0，
  整个范围本身就是唯一的极大区间。

成功响应：

```json
{
  "max_coverage": 2,
  "optimal_intervals": [{"start": 20, "end": 40}, {"start": 80, "end": 100}]
}
```

### 示例 1：两路口部分重叠，最大值 2

两个周期 60 秒的路口绿灯分别为 `[0,40)` 与 `[20,50)`，均在起点：重叠段
`[20,40)` 内出发可同时稳过两个路口，其余时刻最多过一个。发车范围 `[0,120)`：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/max-coverage \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 120,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 0,  "green_end": 40, "travel": 0},
      {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 50, "travel": 0}
    ]
  }'
```

响应（只返回覆盖数达到最大值 2 的区间，按周期重复）：

```json
{"max_coverage":2,"optimal_intervals":[{"start":20,"end":40},{"start":80,"end":100}]}
```

### 示例 2：相邻最优段合并

路口 1 可行窗口为 `[0,30)` 周期 60，路口 2 为 `[30,40)` 周期 60：覆盖数恒为 1
（同一时刻至多过一个路口），端点相接的最优段合并为 `[0,40)`；`[40,60)` 内两个
路口都不可行、覆盖数为 0，故最优区间在周期边界处断开：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/max-coverage \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 0,
    "depart_to": 120,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 0,  "green_end": 30, "travel": 0},
      {"cycle": 60, "offset": 0, "green_start": 30, "green_end": 40, "travel": 0}
    ]
  }'
# {"max_coverage":1,"optimal_intervals":[{"start":0,"end":40},{"start":60,"end":100}]}
```

### 示例 3：最大值为 0 时返回完整发车范围

唯一路口绿灯 20 秒，而行驶时间波动 `travel_max - travel = 30` 已超过绿灯长度，
任何出发时刻都无法保证任意行驶时长下遇绿。最大值为 0，仍返回完整发车范围：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/max-coverage \
  -H "Content-Type: application/json" \
  -d '{
    "depart_from": 10,
    "depart_to": 130,
    "intersections": [
      {"cycle": 60, "offset": 0, "green_start": 20, "green_end": 40,
       "travel": 0, "travel_max": 30}
    ]
  }'
# {"max_coverage":0,"optimal_intervals":[{"start":10,"end":130}]}
```

### 最大覆盖的算法说明（复用单路口窗口 + 端点事件扫描）

1. **复用单路口可行窗口**：对每个路口直接调用与 `/windows` 相同的单路口计算
   （含跨周期绿灯先展开再收缩、常绿不收缩、半开边界裁剪），得到它在发车范围内
   的全部可行半开区间；
2. **端点差分事件扫描**：每个可行窗口 `[a,b)` 在 `a` 处记 +1、`b` 处记 -1，
   事件按位置排序后从 `depart_from` 扫到 `depart_to`，逐段维护当前覆盖路口数。
   覆盖数只可能在窗口端点处变化，故**不逐秒统计**；
3. 取各段覆盖数的全局最大值，把相邻（端点相接）且同为最大值的段合并，即得全部
   极大半开发车区间；没有任何事件时覆盖数恒为 0，直接返回完整发车范围。

## 单路口 offset 诊断

`POST /api/green-wave/offset-diagnostics` 用于根据实际车辆到达观测反推路口最合适的
信号相位偏移。给定一个路口的周期与绿灯相位，以及 1～2000 条
`{arrival_time, observed_green}` 观测（时间均为**整数秒**，`arrival_time` 可为任意
整数——含负数——按周期取模），服务对每个整数 `offset ∈ [0, cycle)` 按

```
本地相位 = (arrival_time + offset) mod cycle
```

预测该观测到达时的灯色（绿灯半开区间、跨零点、端点相等为常绿的语义与上文完全一致），
统计预测灯色与 `observed_green` 不符的观测条数，返回：

- `min_mismatches`：所有整数 offset 中**最少**的错配条数；
- `optimal_intervals`：取到最少错配数的**全部极大半开 offset 区间**
  `[start, end)`（整数 offset 满足 `start <= offset < end`），按 `start` 升序；
  跨零点的最优集合在 `[0, cycle)` 内**分段**表示（例如
  `[{"start":0,"end":10},{"start":50,"end":60}]`），不会出现跨周期的单一区间。

请求体：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `cycle` | int | `1..86400`，信号周期 C（秒） |
| `green_start` | int | `0 <= green_start < cycle`，绿灯起点（本地相位秒） |
| `green_end` | int | `0 <= green_end < cycle`，绿灯终点（本地相位秒，不含）；与 `green_start` 相等表示整周期常绿 |
| `observations` | array | **1..2000** 条观测 |
| `observations[].arrival_time` | int | 到达时刻（整数秒，任意整数，按周期取模） |
| `observations[].observed_green` | bool | 到达时实际灯色：`true`=绿，`false`=红 |

成功响应：

```json
{
  "min_mismatches": 0,
  "optimal_intervals": [{"start": 0, "end": 10}, {"start": 50, "end": 60}]
}
```

### 示例 1：跨零点最优集合分段

绿灯为 `[50,60) ∪ [0,10)`：一条 `arrival_time=0` 观测为绿灯时，offset 取
`[0,10)` 或 `[50,60)` 都零错配（最优集合在 `[0,60)` 内分两段）；另一条
`arrival_time=100`（本地相位 40）观测为红灯，在这两段内相位分别为 40..50 与
30..40（端点 40 不含），仍均预测为红、零错配：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/offset-diagnostics \
  -H "Content-Type: application/json" \
  -d '{
    "cycle": 60,
    "green_start": 50,
    "green_end": 10,
    "observations": [
      {"arrival_time": 0,   "observed_green": true},
      {"arrival_time": 100, "observed_green": false}
    ]
  }'
```

响应：

```json
{"min_mismatches":0,"optimal_intervals":[{"start":0,"end":10},{"start":50,"end":60}]}
```

### 示例 2：不可完全拟合时给出最少错配

整周期常绿（`green_start == green_end`）下任何 offset 都预测为绿；若有一条观测
实际为红灯，则每个 offset 都恰好错配 1 条，最优区间为整个周期：

```bash
curl -s -X POST http://localhost:8000/api/green-wave/offset-diagnostics \
  -H "Content-Type: application/json" \
  -d '{
    "cycle": 60,
    "green_start": 30,
    "green_end": 30,
    "observations": [{"arrival_time": 9, "observed_green": false}]
  }'
# {"min_mismatches":1,"optimal_intervals":[{"start":0,"end":60}]}
```

### offset 诊断的算法说明（周期区间事件扫描）

错配条数是定义在周期圆 `[0, C)` 上的分段常值函数：单条观测的"预测≠观测"offset
集合至多是两条半开整数区间（观测为红时取"预测绿"集合，观测为绿时取其补集）。
算法**不逐一计算 offset × 观测**，而是：

1. 对每条观测，把绿灯集合在周期圆上平移 `-arrival_time`（绕零点断成两段），
   按观测灯色决定取正集还是补集，得到该观测的错配半开区间；
2. 在每个错配区间 `[a,b)` 的端点放置差分事件（`a` 处 +1，`b` 处 -1），共至多
   4n 个事件，按位置排序；
3. 沿 `[0, C)` 扫描事件，维护当前错配条数，逐段记录 `(段起点, 段终点, 错配数)`；
4. 取最小错配数，合并相邻且同值的段，即得全部极大半开最优区间（按起点升序）。

复杂度为 `O(n log n)`（n 为观测条数，≤ 2000），与周期 `cycle` 的大小无关；
2000 条观测、86400 秒周期的请求在毫秒级完成。

## 输入校验与错误

无效周期、相位偏移、绿灯端点、行驶时间（含 `travel_max < travel` 或
`travel_max > 86400`），或路口数、发车范围长度越界时返回
`422 Unprocessable Entity`，响应体含中文原因，例如：

```json
{ "detail": ["travel_max 不得小于 travel（路口 中山路）"] }
```

字段类型错误、缺失字段也由 Pydantic 统一返回 422。

`/api/green-wave/offset-diagnostics` 同样在以下情况返回 422：

- `cycle` 不在 `1..86400`；
- `green_start` / `green_end` 不满足 `0 <= g < cycle`（端点相等表示常绿，合法）；
- `observations` 数量不在 `1..2000`；
- 字段缺失或类型错误（如 `observed_green` 不是布尔值）。

例如绿灯终点越界：

```json
{ "detail": ["green_end 必须满足 0 <= green_end < cycle"] }
```

## 算法说明（区间运算，不逐秒试探）

1. **周期内展开与波动收缩**：每个路口的绿灯半开区间先展开为连续分量
   （`g_start > g_end` 跨零点时视为**一条**连续段 `[g_start, C + g_end)`，
   不拆两段；`g_start == g_end` 时为整周期常绿）。当行驶时间可能取
   `[T, T_max]` 时，令 `slack = T_max - T`，每条连续绿灯段右端收缩为
   `[a, b-slack)`（抵达闭区间须整体落在绿灯半开区间内）；常绿不收缩。
2. **映射到出发时间轴**：行驶时间下限与相位偏移合并为 `shift = (T + o) mod C`，
   收缩后的本地绿灯 `[a,b)` 对应出发时间轴上周期重复的
   `[kC + a - shift, kC + b - shift)`。只枚举与发车范围有非空交的周期 `k`
   （由整除直接算出 `k_min / k_max`），裁剪进 `[depart_from, depart_to)`，
   并合并重叠或端点相接（`[a,b)` 与 `[b,c)`）的区间。
3. **多路口求交**：各路口的有序区间列表用双指针两两求交，得到交集的全部连通段；
   交集为空立即返回。最终结果天然是全部**极大**区间，按起点升序输出。

复杂度约为 `O(路口数 × (范围长度 / 最小周期))` 次区间运算；对一小时范围、
周期最小 1 秒的极端情形，每路口也仅约 3600 个区间。

`/api/green-wave/max-coverage` 复用第 1、2 步得到的各路口可行窗口，再在窗口端点
放置差分事件做一次扫描（至多 `8 × 2 × 3600` 个事件），复杂度与窗口接口同阶。

## 运行测试

```bash
pip install pytest
pytest -q
```

测试包含边界场景（跨零点、偏移、范围边界、半开端点不含、无解、行驶时间波动
`travel_max`）以及 400 组随机参数下与逐秒判定参考实现的逐项对照；最大覆盖另有
400 组随机参数下与逐秒统计覆盖数参考实现的对照（含相邻最优段合并与最大值为 0
时返回完整范围）；offset 诊断
另有 2000+ 组随机参数下与逐 offset 暴力实现的对照、跨零点分段、常绿灯、
负到达时刻、周期 1 秒及 2000 条观测的性能用例。
