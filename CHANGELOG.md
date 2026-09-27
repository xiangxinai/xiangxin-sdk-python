# 更新日志

## 0.2.0 — 未发布

- 模型改名：默认模型从 `xiangxin-latest` 改为 **`xiangxin-s1-latest`**（条件反射对应 `xiangxin-reflex-latest`），响应里的版本号为 `xiangxin-s1-1.0.0` / `xiangxin-reflex-1.0.0`。旧名 `xiangxin-latest`、`xiangxin-preview`、`xiangxin-1.0.0` 服务端仍然接受。
- 新增**条件反射**（`xiangxin-reflex`）支持：`client.reflexes.create / list / get / cancel / delete / wait`（同步与异步），类型 `Reflex`、`ReflexMetrics`（`before` / `after` 的 `accuracy`、`log_loss`、`ece`、`per_question`）、`ReflexExample`。
- 新增模型常量 `S1_MODEL`（`xiangxin-s1`）、`REFLEX_MODEL`（`xiangxin-reflex`）与 `reflex_model(name)`（`xiangxin-reflex:<name>`）。
- 新增异常 `ConflictError`（409：`reflex_not_ready` / `reflex_busy` / `too_many_reflexes`）、`RequestTooLargeError`（413）与 `WaitTimeoutError`。
- `reflexes.create` 默认超时不短于 300 秒，且默认不重试超时（409 / 422 从不重试）。

## 0.1.1 — 2026-09-26

- 默认超时从 30 秒调整为 **120 秒**。服务端现在支持 32k token 的 `state`（单请求 64k），长文档加多个问题的请求可能需要数十秒；原来的 30 秒会让这类请求超时并被自动重试，白白重复计算。
- 发布改为 GitHub Actions + PyPI Trusted Publishing 自动完成。

## 0.1.0 — 2026-09-25

- 首个版本：`XiangxinClient` / `AsyncXiangxinClient`，`Choice` / `Score` / `Noul` 类型化问题与答案，自动重试，`models.list()`。
