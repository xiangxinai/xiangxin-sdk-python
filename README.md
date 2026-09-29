# 象信 AI Python SDK

`xiangxin-sdk` 是 [象信 AI](https://xiangxinai.cn) 的官方 Python SDK，用于调用系统一模型**象信（xiangxin）**。

象信不生成文本：你给它一段**状态（state）**和一组**带类型的问题**，它一次前向就返回带校准概率的结构化答案。问题有三种原语：

| 原语 | 用途 | 答案字段 |
|---|---|---|
| `Noul` | 是非题 | `.noul`：成立的概率 0–1 |
| `Choice` | 单选题（≤ 255 个选项） | `.choice`、`.probabilities`、`.confidence` |
| `Score` | 打分题（2–10 档有序量表） | `.score`（期望分）、`.probabilities`、`.legend`、`.confidence` |

- 同步 / 异步两套客户端，接口一致
- 完整类型标注（`py.typed`），基于 pydantic v2 与 httpx
- 自动重试（429 / 529 / 5xx，遵守 `retry-after`）、超时、日志
- 要求 Python ≥ 3.10

## 安装

```bash
pip install xiangxin-sdk
# 或
uv add xiangxin-sdk
```

## 快速开始

先在 [控制台](https://console.xiangxinai.cn/keys) 创建 API 密钥，并设置环境变量：

```bash
export XIANGXIN_API_KEY="sk-xx-..."
```

```python
from xiangxin import Choice, Noul, Score, XiangxinClient

client = XiangxinClient()  # 自动读取 XIANGXIN_API_KEY

resp = client.system_one(
    state="我这个月被重复扣费了两次，客服三天都没回复，请尽快处理！",
    questions={
        "is_urgent": Noul(instructions="这张工单是否需要当天处理？"),
        "department": Choice(
            instructions="应分派到哪个部门？",
            criteria={
                "billing": "扣费、发票、退款",
                "technical": "报错、故障、无法登录",
                "sales": "购买咨询、套餐升级",
            },
        ),
        "frustration": Score(
            instructions="用户的情绪有多激动？",
            criteria=["平静", "不满", "非常愤怒"],
        ),
    },
)

print(resp.answers["is_urgent"].noul)          # 0.95
print(resp.answers["department"].choice)       # "billing"
print(resp.answers["department"].confidence)   # 0.81
print(resp.answers["frustration"].score)       # 1.05
print(resp.usage.input_tokens, resp.model)     # 296 xiangxin-2.0.0
```

也可以按类型分组读取：`resp.nouls`、`resp.choices`、`resp.scores`。

### 用字典写问题

问题对象与普通字典完全等价，可以混用：

```python
client.system_one(
    state={"标题": "无法登录", "正文": "输入验证码后一直转圈"},
    questions={
        "is_bug": {"type": "noul", "instructions": "这是产品缺陷吗？"},
        "severity": Score(instructions="严重程度", criteria=["轻微", "一般", "严重"]),
    },
)
```

`state`、`instructions` 以及各选项的描述都可以是文本、JSON 对象或数组。

### 异步客户端

```python
import asyncio
from xiangxin import AsyncXiangxinClient, Noul

async def main() -> None:
    async with AsyncXiangxinClient() as client:
        resp = await client.system_one(
            state="这家店的发货速度太慢了",
            questions={"negative": Noul(instructions="这是负面评价吗？")},
        )
        print(resp.answers["negative"].noul)

asyncio.run(main())
```

### 带类型的响应模型

继承 `SystemOneResponse`，声明与问题同名的字段，即可获得类型检查与补全：

```python
from xiangxin import ChoiceAnswer, NoulAnswer, SystemOneResponse

class Ticket(SystemOneResponse):
    is_urgent: NoulAnswer
    department: ChoiceAnswer

t = client.system_one(state, questions, response_model=Ticket)
t.is_urgent.noul, t.department.choice
```

## 模型

```python
for m in client.models.list().models:
    print(m.name, m.description, m.release_date)
```

只有一个模型：象信（xiangxin）。`models.list()` 列出可在 `model` 中使用的别名：

| 模型 | 说明 |
|---|---|
| `xiangxin-latest` | 最新正式版，SDK 默认值 |

响应里的 `resp.model` 是实际使用的版本化 ID，如 `xiangxin-2.0.0`；需要固定版本时可直接传版本化 ID。可在创建客户端时指定 `model=`，或在单次调用时传入 `model=` 覆盖。

## 读取响应头与原始响应

```python
resp = client.system_one(state, questions)
resp.request_id          # x-request-id
resp.model_ms            # 模型耗时（毫秒）
resp.total_ms            # 总耗时（毫秒）
resp.raw_http_response   # httpx.Response

raw = client.with_raw_response.system_one(state, questions)
raw.status_code, raw.headers["x-xiangxin-model-ms"]
resp = raw.parse()
```

## 错误处理

所有异常都继承自 `XiangxinError`：

| 异常 | 状态码 | 场景 |
|---|---|---|
| `AuthenticationError` | 401 | API 密钥缺失、无效或已禁用 |
| `InsufficientBalanceError` | 402 | 余额不足，请到控制台充值 |
| `NotFoundError` | 404 | 模型不存在（`model_not_found`） |
| `RequestTooLargeError` | 413 | 请求体过大 |
| `UnprocessableEntityError` | 422 | 请求校验失败（选项过多、超出 token 上限等） |
| `RateLimitError` | 429 | 超出速率限制（`.retry_after` 为建议等待秒数） |
| `OverloadedError` | 529 | 服务过载，稍后重试 |
| `InternalServerError` | 其他 5xx | 服务端错误 |
| `APIConnectionError` / `APITimeoutError` | — | 网络错误 / 超时 |

```python
from xiangxin import APIError, InsufficientBalanceError

try:
    client.system_one(state, questions)
except InsufficientBalanceError:
    print("余额不足，请充值")
except APIError as e:
    print(e.status_code, e.detail, e.request_id)
```

## 重试与超时

默认对 408、429、所有 5xx（含 529）以及连接错误 / 超时重试 2 次，指数退避（0.5 秒起翻倍，单次不超过 5 秒）加抖动；服务端返回 `retry-after-ms` / `retry-after` 时按其等待（超过 60 秒则改按退避）。重试请求带 `x-xiangxin-retry-count`。422 等客户端错误不会重试。

```python
from xiangxin import RetryPolicy, XiangxinClient

client = XiangxinClient(
    timeout=10.0,                                   # 单次 HTTP 超时（秒），默认 120
    retry=RetryPolicy(max_retries=4, backoff_max=4.0),
)
client.system_one(state, questions, retry=RetryPolicy(max_retries=0), timeout=5.0)  # 单次覆盖
```

## 日志

SDK 使用名为 `xiangxin` 的 logger。`info` 级别每个请求输出一行摘要，`debug` 级别额外输出请求 / 响应头与正文（`Authorization` 等敏感头会被隐去，正文不会）。

```python
import logging
logging.getLogger("xiangxin").setLevel(logging.INFO)
```

或在导入 SDK 前设置 `XIANGXIN_LOG=debug|info|warning|error|off`。

## 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `XIANGXIN_API_KEY` | API 密钥（必填） | — |
| `XIANGXIN_BASE_URL` | API 根地址 | `https://api.xiangxinai.cn` |
| `XIANGXIN_DEFAULT_MODEL` | 默认模型 | `xiangxin-latest` |
| `XIANGXIN_LOG` | 日志级别 | 不设置 |

显式传入的参数优先于环境变量。

## 开发

```bash
uv sync
uv run pytest
```

更多文档见 <https://docs.xiangxinai.cn>。
