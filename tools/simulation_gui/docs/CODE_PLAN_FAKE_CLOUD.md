# fake_cloud — 代码方案

> **目录**: `tools/simulation_gui/fake_cloud/`（本仓库，3 模块 ~850 行）
> **GUI 面板**: `mavlink_monitor/integrated_gui/_cloud_panel.py`（CloudProxyPanel ~370 行）
> **版本**: v1.3（监听阶段）
> **行数**: fake_cloud 851 + _cloud_panel 368
> **最后同步**: 2026-09-15
> **需求来源**: `D:\Work\My_Project_Local\temp_file\advertisement-popup-strategy.md` §8（方案 A）
> **用途**: 云平台透明反向代理 —— 拦截本地地面站与云平台（dmduav）之间的 HTTP 流量，
> **纯透传 + 双向监听 + 协议解析**，以结构化事件暴露给 GUI 消息监视视图
>
> **⚠️ 阶段约束（v1.0）**: 当前为「监听阶段」——对请求/响应内容 **100% 透传，
> 不做任何篡改或拦截改写**（用户决议）。篡改框架已就位：
> `tampered_response` 事件类型 + `json_diff` 字段级高亮 + GUI 篡改对比区，
> 后续阶段在 `_ProxyHandler._handle` 启用改写路径即可（见 §8.3）。
>
> **关联方案**:
> - [CODE_PLAN.md](./CODE_PLAN.md) — integrated_gui 主面板方案（§4.3a CloudProxyPanel）
> - [CODE_PLAN_FAKE_AIRPLANE.md](./CODE_PLAN_FAKE_AIRPLANE.md) — 假飞机模块方案（本方案的设备模式参考）

---

## 目录

1. [文件速览](#1-文件速览)
2. [代码分段索引](#2-代码分段索引)
3. [类层次结构](#3-类层次结构)
4. [核心类详解](#4-核心类详解)
5. [update_xxx 方法清单](#5-update_xxx-方法清单)
6. [数据流（事件流）](#6-数据流事件流)
7. [与 integrated_gui 的交互](#7-与-integrated_gui-的交互)
8. [修改指南（含篡改阶段扩展）](#8-修改指南含篡改阶段扩展)

---

## 1. 文件速览

```
tools/simulation_gui/fake_cloud/          (Python 包, ~850 行)
│
├── __init__.py       ( 50 行)  导出公共符号（常量/类/函数）
│
├── ad_proxy.py       (609 行)  核心代理（本方案主体）
│   ├── 模块级常量（GUI 基础参数区 AST 反射源）
│   ├── _NoRedirectHandler / _OPENER — 禁跟随重定向的 urllib opener
│   ├── _try_parse_json / _decode_for_parse / parse_promotion_response
│   ├── _ProxyHandler(BaseHTTPRequestHandler) — 透传处理器
│   ├── _check_port_free — Windows SO_REUSEADDR 端口占用预检
│   ├── _ProxyHTTPServer(ThreadingHTTPServer)
│   ├── FakeCloudGateway — 传输层（transport 角色）
│   ├── _FakeCloudSender — 协议响应器（sender 角色，事件汇）
│   └── _FakeCloudSenders — 批量管理器（mgr 角色）
│
└── json_diff.py      (192 行)  JSON 递归 diff + HTML 高亮（纯函数，预留篡改阶段）
    ├── diff_json(original, tampered) → [{path, kind, old, new}]
    ├── render_json_html / syntax_highlight — 语法高亮渲染
    └── highlight_html(original, tampered) — 改⚠黄/增＋绿/删－红 对比视图

mavlink_monitor/integrated_gui/
└── _cloud_panel.py   (368 行)  GUI 复合面板
    ├── CloudMessageView — 消息监视（事件表格 + 详情 HTML）
    └── CloudProxyPanel — SimulationPanel + CloudMessageView（API 委托）

tests/
├── test_fake_cloud_proxy.py  (330 行)  TC1-TC5 自动化用例
└── _gui_verify_fake_cloud.py (手动)    E1-E5 扩展验证（含 GUI 实操）
```

**依赖**: 零第三方依赖（stdlib `http.server` + `urllib.request` + `gzip/zlib`）。

**使用方法**（对齐 advertisement-popup-strategy.md §8.3）:
1. GUI「云平台拦截」Tab 添加代理实例（默认 `10.10.12.149:14852`，上游
   UAT `https://cloud-gateway-uat.dmduav.com`，可用 `update_upstream` 随时切换）；
2. 地面站工作目录新建 `http_test_server.txt`，内容一行
   `http://10.10.12.149:14852`（**必须 http:// 前缀**——本代理为明文 HTTP，
   https:// 前缀会发 TLS ClientHello 打到明文端口，代理将发
   「非 HTTP 数据」proxy_error 事件提示；origin 客户端进程内只读一次，
   改动需重启地面站）；
3. Release 构建地面站登录 → 全部云端接口经代理透传 → GUI 实时显示
   「地面站→云 / 云→地面站」事件流。

---

## 2. 代码分段索引

### 2.1 ad_proxy.py 模块级常量与工具 (L1-148)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L47-55 | 模块级常量（AST 反射到 GUI 基础参数区） | `DEFAULT_LISTEN_HOST`(10.10.12.149), `DEFAULT_LISTEN_PORT`(14852), `DEFAULT_UPSTREAM_ORIGIN`(https://cloud-gateway-uat.dmduav.com, v1.2 改回 UAT), `UAT_UPSTREAM_ORIGIN`, `PROMOTION_LIST_PATH`(/api/v1/promotion/list), `UPSTREAM_TIMEOUT_SECONDS`(15), `MAX_EVENT_BUFFER`(2000), `MAX_JSON_PARSE_BYTES`(1MB) |
| L57-70 | 逐跳头集合 + 请求/响应侧丢弃集 | `_HOP_HEADERS`; 请求另删 `host/content-length/accept-encoding`（上游返回明文可安全解析）；响应另删 `content-length`（本地重算） |
| L72-84 | `_NoRedirectHandler` + `_UPSTREAM_SSL_CONTEXT` + `_OPENER` | 禁自动跟随 3xx（透明透传）；**上游 HTTPS 默认不校验证书**（`ssl._create_unverified_context()`，联调上游常为 IP 直连/自签如 https://10.20.2.34:443，校验必失败 → 502） |
| L85-93 | `_try_parse_json(body)` | >1MB / 非 JSON / 空 → None |
| L95-106 | `_decode_for_parse(body, encoding)` | gzip/deflate 解压**仅用于解析**；回写客户端仍是原始字节 |
| L108-134 | **`parse_promotion_response(json_body)`** | 信封 code/message + data 条目数 + 前 10 条摘要（id/title/image_url/content_len/url） |
| L136-147 | `_response_summary(...)` | 表格摘要列：JSON→`code=200 items=3`；非 JSON→`74B image/png` |

### 2.2 _ProxyHandler — 透传处理器 (L150-295)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L150-156 | 类头（protocol_version="HTTP/1.1"，server_version 空） | — |
| L158-178 | do_GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS → 全部走 `_handle` | — |
| L181-182 | `_proxy` property → `self.server.proxy` | gateway 引用 |
| L184-212 | **`parse_request()` 覆写** — 非 HTTP 数据（TLS ClientHello / 二进制）连入明文代理端口 → 发 `proxy_error` 事件（提示 http_test_server.txt 须用 `http://` 前缀 + 16 字节 hex 预览）；默认实现仅静默关连接，上位机零感知 | v1.1 新增 |
| **L214-274** | **`_handle()`** — 核心透传链 | 读请求体 → 发 `gcs_request` 事件 → 过滤头透传上游 → 解析响应 → 发 `cloud_response` 事件（含 promotion 深度解析）→ 原样回写（Content-Length 重算，HEAD 无 body） |
| L246-256 | `_read_request_body()` | Content-Length 读取；chunked 上行不支持（返回空体，上游按语义报错） |
| L258-278 | `_forward(...)` | `_OPENER.open(timeout=15)`；HTTPError(4xx/5xx) 也是有效响应原样透传；网络级失败 → 502 + `proxy_error` 事件 |
| L280-292 | `_reply(...)` | `send_response_only`（不加 Server/Date 头）；`except ConnectionError` 吞客户端断开（BrokenPipe/Reset/WinError 10053 Aborted） |
| L294-295 | `log_message` 静音 | 事件流即为日志 |

### 2.3 端口预检与 Server (L298-334)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L298-321 | **`_check_port_free(host, port)`** | Windows `SO_REUSEADDR` 允许多 server 静默 bind 同端口（事件流分裂）→ **connect 探测**判定「存在活跃监听」（TIME_WAIT 不误报）；占用抛 OSError → mgr 构造同步失败 → GUI「添加失败」 |
| L323-334 | `_ProxyHTTPServer(ThreadingHTTPServer)` | `daemon_threads=True`; `allow_reuse_address=True`（下线→上线快速重启不受 TIME_WAIT 影响）；构造前执行端口预检 |

### 2.4 FakeCloudGateway — transport 角色 (L336-423)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L336-346 | 类文档（SimulationPanel 契约：local_ip/local_port/close；**无 sock** → `_patch_transport_socket` 自动跳过） | — |
| L348-360 | `__init__` — **构造即 bind**（异常同步上抛） | `self._server = _ProxyHTTPServer(...)` |
| L362-371 | `start()` — serve_forever daemon 线程（poll 0.2s） | `_serve_thread` |
| L373-390 | `close()` — **仅 serve 线程存活时才 shutdown()**（从未 start 的 server 调 `BaseServer.shutdown()` 会 wait 永不 set 的 Event → 永久阻塞）；再 `server_close()` | 幂等 |
| L392-394 | `is_serving()` | `_server is not None` |
| L396-407 | `get_upstream()` / `get_parse_promotion()` — **实时读 sender**（update_xxx 修改立即生效） | — |
| L409-422 | `next_req_id()` / `emit_event()` — 事件桥（seq 分配委托 sender；回调异常吞掉不影响透传） | — |

### 2.5 _FakeCloudSender — sender 角色 (L425-574)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L425-435 | 类文档（契约：update_xxx 反射 / running+thread+_run+stop / code+serial / set_msg_injector 占位） | — |
| L437-464 | `__init__` — 属性初始化 + **同步预 bind**（`_ensure_gateway()` 在 `start()` 前）+ 自启 | `code=listen_port`, `serial=upstream_origin`, `deque(maxlen=max_events)` |
| L466-474 | `start()` / L476-481 `stop()`（join 5s） | — |
| L483-507 | `_run()` — serve 循环 | `_ensure_gateway`（异常→`proxy_error` 事件+退出）→ `gw.start()` → 轮询 running → close；下线再上线自动重建 |
| L509-523 | `_ensure_gateway()` / `_current_gateway()` | `_gw_lock` 保护 |
| L525-539 | **update_xxx**（见 §5） | — |
| L541-551 | `_emit_event(event)` — seq 分配 + deque 追加 + 回调（锁内） | — |
| L553-563 | `next_req_id()` / **`drain_events()`**（GUI 轮询入口，取走全部） | — |
| L565-574 | `set_event_callback(cb)`（程序化订阅，测试用）/ `set_msg_injector(cb)`（UDP 注入兼容占位，no-op） | — |

### 2.6 _FakeCloudSenders — mgr 角色 (L576-609)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L576-601 | `__init__(count, listen_host, listen_port, upstream_origin, parse_promotion, max_events, log_manager)` — GUI「添加设备」表单即此签名；count 个实例端口自 listen_port 递增 | `cloud_senders`, `cloud_gateways` |
| L604-609 | `stop()` — 批量 stop | — |

### 2.7 json_diff.py (L1-192)

| 行号 | 功能 | 关键符号 |
|------|------|----------|
| L19-33 | 高亮样式常量 | `CHANGED_STYLE`(黄#ffe58f) / `ADDED_STYLE`(绿#b7eb8f) / `REMOVED_STYLE`(红#ffa39e+删除线) |
| L43-87 | **`diff_json(original, tampered, path="$")`** — 递归对比 dict/list/标量 | 路径语法 `$.data[0].title`；kind ∈ changed/added/removed；`_MISSING` 哨兵 |
| L90-148 | `_fmt_scalar` / `_wrap_mark`（⚠＋－ 前缀 + title 原值提示）/ `render_json_html`（缩进 HTML + marks 命中路径高亮） | — |
| L151-161 | `syntax_highlight(obj)` — 纯语法高亮（GUI 详情区） | key蓝/str绿/num紫/bool橙 |
| L163-192 | **`highlight_html(original, tampered)`** — 对比视图（legend 计数 + 高亮 body） | 改动悬停显示原值 |

---

## 3. 类层次结构

```
ThreadingHTTPServer
  └── _ProxyHTTPServer                        (ad_proxy L323)
        └── .proxy: FakeCloudGateway

BaseHTTPRequestHandler
  └── _ProxyHandler                           (ad_proxy L150)
        └── 全部 do_* → _handle()（事件 + 透传 + 回写）

urllib.request.HTTPRedirectHandler
  └── _NoRedirectHandler                      (ad_proxy L72)

（SimulationPanel 三角色契约）
FakeCloudGateway      — transport（local_ip/local_port/close；无 sock）
_FakeCloudSender      — sender（update_xxx/running/thread/_run/stop/code/serial）
_FakeCloudSenders     — mgr（cloud_senders/cloud_gateways）
```

GUI 侧（详见主方案 CODE_PLAN.md §4.3a）：

```
QWidget
  ├── CloudProxyPanel                         (_cloud_panel L221)
  │     ├── ._sim_panel: SimulationPanel(cloud cfg)
  │     ├── ._view: CloudMessageView          (_cloud_panel L41)
  │     └── ._poll_timer: QTimer(50ms)
  └── CloudMessageView
        ├── ._table: QTableWidget(7 列)
        └── ._detail: QTextBrowser（HTML）
```

---

## 4. 核心类详解

### 4.1 _ProxyHandler._handle（核心透传链，L184-244）

```
读请求体（Content-Length）
  → emit gcs_request {method, path, auth(Authorization 存在性，值不落事件),
                      client_version(X-DGCS-VERSION), content_type, body_len,
                      json_body, summary}
  → url = upstream.rstrip('/') + path          （upstream 实时读 sender）
  → 过滤请求头：丢 hop-by-hop + host/content-length/accept-encoding
  → _forward: _OPENER.open(url, timeout=15s)
       ├─ 成功/HTTPError(4xx/5xx) → (status, headers, body)
       └─ URLError/timeout → 502 + proxy_error 事件 → return
  → 解析响应体（content-encoding gzip/deflate 先解压仅供解析）
  → emit cloud_response {status, content_type, body_len, json_body,
                         parsed(仅 promotion 接口且 parse_promotion 开),
                         summary}
  → 回写：过滤 hop-by-hop + content-length → send_response_only(status)
          + headers + 重算 Content-Length + body（HEAD 无 body）
```

**安全细节**：Authorization 头只记录存在性（`auth: True`），token 值不进事件流
（需求 §8.7 token 安全）。

### 4.2 事件模型（drain_events 返回的 dict）

| 字段 | 类型 | 说明 |
|------|------|------|
| `seq` | int | sender 内递增（线程安全，锁内分配） |
| `ts` | float | `time.time()` |
| `kind` | str | `gcs_request` / `cloud_response` / `proxy_error`（`tampered_response` 预留篡改阶段） |
| `req_id` | int | 同一 HTTP 事务请求/响应成对关联 |
| `method` / `path` / `status` / `content_type` / `body_len` | — | HTTP 元数据 |
| `auth` / `client_version` | — | 仅 gcs_request |
| `json_body` | Any/None | 解析后 JSON（>1MB/非 JSON/压缩失败 → None） |
| `parsed` | dict/None | promotion 深度解析（`envelope_code/message/item_count/items[≤10]`） |
| `error` | str | 仅 proxy_error |
| `summary` | str | 单行摘要（GUI 表格直用） |
| `original` / `tampered` | — | **预留** tampered_response 事件携带（GUI 对比高亮渲染） |

### 4.3 线程模型

```
_FakeCloudSenders.__init__（GUI 主线程 / 测试线程）
  └── _FakeCloudSender.__init__
        ├── _ensure_gateway() → FakeCloudGateway.__init__ → bind（同步，失败上抛）
        └── start() → _run 线程 (daemon)
              └── gw.start() → serve 线程 (daemon, poll 0.2s)
                    └── _ProxyHandler 每连接每请求一线程 (daemon_threads)

GUI: CloudProxyPanel._poll_timer (50ms, Qt 主线程)
  → drain_events()（锁内取走 deque 全部）
  → CloudMessageView.add_event（表格行 + 详情渲染）
```

- **下线**：running=False → `_run` 内层 sleep 退出 → `gw.close()`（serve 线程活 → shutdown 正常）→ gateway=None
- **再上线**：`_start_sender_thread` 新线程 → `_run` 重建 gateway（allow_reuse_address 使 TIME_WAIT 期快速复用）
- **进程退出**：全部 daemon 线程，`CloudProxyPanel.shutdown()` → sim_panel.shutdown() → sender.stop()

---

## 5. update_xxx 方法清单

> 本阶段（监听模式）仅监听配置，**不影响透传内容**。篡改类方法
> （update_scenario / update_status_code / update_delay 等）留待篡改阶段（§8.3）。

| 方法 | 参数 | 说明 |
|------|------|------|
| `update_upstream` | `upstream_origin: str = ""` | 切换上游云平台 origin（如 UAT `https://cloud-gateway-uat.dmduav.com`）；gateway 每请求实时读取 |
| `update_event_buffer` | `max_events: int = 2000` | 调整事件队列容量（缩小丢弃最旧；下限 10） |
| `update_parse_promotion` | `enable: bool = True` | 开关 promotion 接口深度解析（关闭后事件 `parsed=None`；透传内容不变） |

GUI 反射（`SimConfig.known_param_types`）：`upstream_origin/upstream→str`、
`max_events→int`、`enable→bool`、`listen_host→str`、`listen_port→int`、
`parse_promotion→bool`、`count→int`。

---

## 6. 数据流（事件流）

```
地面站 (Release, http_test_server.txt → http://127.0.0.1:8765)
   │ HTTP (Authorization + X-DGCS-VERSION + JSON body)
   ▼
FakeCloudGateway (ThreadingHTTPServer, 127.0.0.1:8765)
   │ _ProxyHandler._handle
   ├─① gcs_request 事件 ──────────────┐
   │ 透传（头过滤/禁重定向/15s 超时）    │
   ▼                                  │
真实云平台 (cloud.dmduav.com:8080)      │
   │ HTTP 响应                          │
   ▼                                  │
   ├─② cloud_response 事件（含 parsed）─┤→ sender._emit_event
   │ 原样回写地面站                       │   （seq + deque + callback）
   ▼                                  │        │
（内容 100% 不变）                       ▼        ▼
                                   drain_events()  set_event_callback
                                        │           （测试）
                                        ▼
                       CloudProxyPanel._on_poll (QTimer 50ms)
                                        ▼
                       CloudMessageView 表格行（类型/方法/路径/状态/摘要）
                                        ▼ 点击行
                       详情 QTextBrowser：
                         · gcs_request → 头摘要表 + body JSON 语法高亮
                         · cloud_response → 信封 + promotion 条目表 + JSON 高亮
                         · tampered_response（预留）→ json_diff.highlight_html
                           （改⚠黄底 悬停原值 / 增＋绿 / 删－红）
```

---

## 7. 与 integrated_gui 的交互

| 集成点 | 位置 | 说明 |
|--------|------|------|
| 模块导入 | `_env.py` 末段 | `_SIM_GUI_DIR` 入 sys.path；`HAS_FAKE_CLOUD` 恒 True（本仓库内）；失败 None 占位 |
| SimConfig 注册 | `_config.py` `_build_sim_configs()` | `"cloud"` 无条件分支（不依赖 HAS_FAKE_MODULES）；假设备分支不变；`module_name="fake_cloud.ad_proxy"`（「应用基础参数」的 importlib 导入名，包内模块必须 dotted 路径，v1.1） |
| Tab 创建 | `_window.py` | `CloudProxyPanel`（`INTEGRATED_TAB_CLOUD`），假设备循环 `skip "cloud"`；`_sim_configs` 构建条件 `HAS_FAKE_MODULES or HAS_FAKE_CLOUD` |
| 消息注入 | `set_message_injector` | UDP raw 注入对 HTTP 代理为兼容占位（gateway 无 sock → 拦截器自动跳过；sender.set_msg_injector no-op） |
| 假节点 IP | `CloudProxyPanel.get_fake_node_ips()` | 恒 `[]`（非 UDP 假节点，不进 UDP 监控过滤列表） |
| 关闭清理 | `_window.closeEvent` → `CloudProxyPanel.shutdown()` | 停轮询 + sim_panel.shutdown() → sender.stop() → gateway.close() |

**与假飞机/机巢/电台的差异**：

| 维度 | 假飞机/机巢/电台 | fake_cloud |
|------|-----------------|------------|
| 协议 | UDP + MAVLink/DAV 二进制 | HTTP 反向代理（明文 JSON） |
| 源文件位置 | 假项目 `src/Protocol/mavlink/` | 本仓库 `tools/simulation_gui/fake_cloud/` |
| 可用性 | `HAS_FAKE_MODULES`（依赖假项目） | `HAS_FAKE_CLOUD`（恒 True） |
| 消息进 GUI | `inject_raw_message` → UDP 监控 Tab | `drain_events` → cloud Tab 专属消息视图 |
| Tab 形态 | SimulationPanel | CloudProxyPanel（SimulationPanel + CloudMessageView 复合） |
| 篡改高亮 | —（二进制无 diff 视图） | json_diff 字段级 HTML 高亮（预留启用） |

---

## 8. 修改指南（含篡改阶段扩展）

### 8.1 新增 update_xxx 方法

1. `_FakeCloudSender` 添加方法（带类型注解默认值，GUI 反射生成控件）；
2. `_config.py` cloud `known_param_types` 注册参数类型；
3. 需要新常量则加 `ad_proxy.py` 模块级（GUI 基础参数区自动出现）；
4. 更新本文档 §5；测试补用例到 `tests/test_fake_cloud_proxy.py`。

### 8.2 调整监听/解析行为

1. 请求/响应事件字段：`_ProxyHandler._handle` 两个 emit_event 调用；
2. 深度解析新接口：参照 `parse_promotion_response` 新增函数 + `_handle` 中
   path 判定分支 + sender 加 `update_parse_xxx` 开关；
3. 事件容量/轮询：`MAX_EVENT_BUFFER` / `CloudProxyPanel._POLL_INTERVAL_MS`。

### 8.3 启用「篡改阶段」（后续版本）

框架已就位，启用步骤：

1. **场景构建**：新建 `fake_cloud/scenarios.py`（single/multi/empty/dup_id/
   oversize/bad_url/fail_code/http_502/slow，参照需求文档 §8.3 `build_data()`）；
2. **改写路径**：`_ProxyHandler._handle` 在 cloud_response 事件后、`_reply` 前插入：
   `tampered = apply_tamper(json_body, config)`（读 sender 的篡改配置）；
   非 None 时改写回写体，并 emit `tampered_response` 事件（携带
   `original=json_body` + `tampered`，GUI 对比高亮自动渲染）；
3. **update 方法**：`update_scenario` / `update_status_code` / `update_delay` /
   `update_intercept` 等（config 增对应属性，gateway 加 getter）；
4. **图片 mock 路由**：`_ProxyHandler` 注册 `/mock/<name>.png`
   （ok/404/500/slow/huge/notimage/corrupt，参照需求文档 §8.5），scenarios 的
   imageUrl 指向 `http://{listen_host}:{listen_port}/mock/ok.png`；
5. 测试：TC1 改断言篡改生效；新增场景矩阵用例（需求文档 §8.6 17 条可筛选）；
6. 更新本文档版本号 + §1/§5/§6 + 主方案 CODE_PLAN。

### 8.4 排查「GUI 看不到消息」

1. 设备列表该实例是否在线（serve 线程活）；
2. `drain_events()` 是否有返回（`proxy_error` 事件看启动/上游错误）；
3. 端口预检：同端口已有活跃监听会同步「添加失败」；
4. 地面站 origin 只读一次——改 `http_test_server.txt` 后需重启地面站；
5. 详情区点击行才渲染（表格行 → `_on_row_clicked`）。

---

> **更新记录**:
> - 2026-09-15: v1.3 — GUI 结构调整：云平台拦截 Tab 子 Tab 化（主方案 v3.9）——
>   「云平台配置」= 本方案描述的原页面（SimulationPanel + CloudMessageView）；
>   「TCP 消息监控」= `TcpMonitorPanel`（GCS↔云平台 TCP/TLS 独立监控，
>   从 UDP 消息监控 Tab 迁出，详见主方案 §4.3b）。
> - 2026-09-15: v1.2 — `DEFAULT_UPSTREAM_ORIGIN` 由 10.20.2.34:443 改回 UAT
>   `https://cloud-gateway-uat.dmduav.com`（监听仍 10.10.12.149:14852）。
>   监控区域（UDP 监控 Tab）同步新增「地面站应用」TCP 监控数据源
>   （不依赖地面站配置 http_test_server.txt 即可旁路看到 GCS↔云平台
>   TCP/TLS 流量元数据，见主方案 v3.8）。`test_fake_cloud_proxy.py` TC7 /
>   `_gui_verify_fake_cloud.py` E7.3 断言同步更新。
> - 2026-09-15: v1.1 — 用户反馈 4 项修复：(1) 「应用基础参数」报
>   `No module named 'ad_proxy'` —— `SimConfig` 新增 `module_name` 字段
>   （cloud="fake_cloud.ad_proxy"），`_panels.py _on_basic_apply_clicked`
>   导入名 `module_name or source_file.stem`（假设备顶层模块不受影响；
>   不把 fake_cloud/ 目录加 sys.path——避免与包导入形成双模块实例）；
>   (2) 默认监听改 `10.10.12.149:14852`；(3) 默认上游改
>   `https://10.20.2.34:443`；(4) 上位机看不到消息的三层根因修复——
>   上游 HTTPS 默认不校验证书（IP 直连/自签必失败 → 此前全 502）、
>   非 HTTP 数据（TLS ClientHello）连入明文代理静默丢弃 → `parse_request`
>   覆写发 proxy_error 事件提示 http:// 前缀、监听地址与地面站访问地址
>   对齐。新增 `test_fake_cloud_proxy.py` TC6-TC9（自签 HTTPS 端到端需
>   openssl）；`_gui_verify_fake_cloud.py` 增 E6-E9；全套 430 passed、
>   扩展验证 35/35。
> - 2026-09-14: v1.0 — 监听阶段初版：透明反向代理（纯透传）+ 双向事件流
>   （gcs_request/cloud_response/proxy_error）+ promotion 深度解析 +
>   json_diff 高亮组件 + GUI CloudProxyPanel（SimulationPanel 复合消息监视）。
>   开发中修复：① `close()` 对从未 start 的 server 调 `shutdown()` 永久阻塞；
>   ② Windows `SO_REUSEADDR` 同端口静默共存 → connect 探测预检；
>   ③ `_reply` 未捕获 `ConnectionAbortedError`(WinError 10053)。
>   测试：`test_fake_cloud_proxy.py` TC1-TC5（5 用例）+ `_gui_verify_fake_cloud.py`
>   E1-E5（25 断言，含 GUI 实操）；全套 426 passed。
