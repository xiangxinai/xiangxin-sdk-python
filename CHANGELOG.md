# 更新日志

## 0.3.0 — 2026-09-28

- 只有一个模型：象信（xiangxin），默认模型改为 `xiangxin-latest`。
- 删除已下线的模型训练接口及其类型。

## 0.2.1 — 2026-09-28

重试策略与 TypeSafe 官方 SDK 对齐：
- 默认重试的状态码从 `429 / 500 / 502 / 503 / 504 / 529` 扩大为 `408`、`429` 与**所有 5xx**。
- 指数退避单次上限从 8 秒改为 **5 秒**（0.5 秒起翻倍，随机扣减最多 25%）。
- 服务端建议的等待（`retry-after-ms` / `retry-after`）超过 `max_retry_after`（默认 60 秒）时，不再直接放弃，而是改按指数退避重试。
- 重试请求带 `x-xiangxin-retry-count: n`（新增常量 `RETRY_COUNT_HEADER`），首发请求不带；服务端据此区分首发与重试。

## 0.2.0 — 2026-09-27

- 新增异常 `ConflictError`（409）与 `RequestTooLargeError`（413）。
 — 2026-09-26

- 默认超时从 30 秒调整为 **120 秒**。服务端现在支持 32k token 的 `state`（单请求 64k），长文档加多个问题的请求可能需要数十秒；原来的 30 秒会让这类请求超时并被自动重试，白白重复计算。
- 发布改为 GitHub Actions + PyPI Trusted Publishing 自动完成。

## 0.1.0 — 2026-09-25

- 首个版本：`XiangxinClient` / `AsyncXiangxinClient`，`Choice` / `Score` / `Noul` 类型化问题与答案，自动重试，`models.list()`。
