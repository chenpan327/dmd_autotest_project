"""fake_cloud.ad_proxy — 云平台透明反向代理（监听 + 解析模式）。

依据 ``advertisement-popup-strategy.md`` §8.3（方案 A）落地。
当前版本为「监听阶段」：对请求/响应内容 **100% 透传，不做任何篡改或拦截改写**；
仅双向捕获并解析 HTTP 消息，以结构化事件暴露给 GUI（``CloudMessageView``）。

配合地面站本地 Host 覆盖机制使用（origin 在客户端进程内只读一次，改动需重启客户端）：
  1. 启动本代理（默认 http://127.0.0.1:8765）；
  2. 在地面站进程工作目录新建 ``http_test_server.txt``，内容一行：
     ``http://127.0.0.1:8765``；
  3. 启动地面站（Release 构建）并登录：登录、token 刷新及其余云端接口
     全部经本代理透传至真实云平台；GUI 实时显示
     「地面站→云平台请求 / 云平台→地面站响应」事件流。

预留（后续「篡改阶段」，本版本不启用）：
  * ``tampered_response`` 事件类型 + ``fake_cloud.json_diff`` 字段级高亮组件；
  * ``/mock/*.png`` 图片行为模拟路由（imageUrl 指向本代理时才会被请求）。

事件结构（``drain_events()`` 返回的 dict）：
    seq        事件序号（sender 内递增）
    ts         time.time()
    kind       "gcs_request" | "cloud_response" | "proxy_error"
               （"tampered_response" 预留篡改阶段）
    req_id     同一 HTTP 事务的关联 id（请求/响应成对）
    method / path / status / content_type / body_len
    auth / client_version                    仅 gcs_request（Authorization 存在性 / X-DGCS-VERSION）
    json_body  解析后的 JSON（>1MB 或非 JSON 为 None）
    parsed     promotion 接口深度解析结果（parse_promotion 开启时）
    error      仅 proxy_error
    summary    单行摘要（GUI 表格直接使用）

零第三方依赖：stdlib ``http.server`` + ``urllib.request``。
"""
from __future__ import annotations

import gzip
import json
import ssl
import threading
import time
import urllib.error
import urllib.request
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

# ═══════════════════════════════════════════════════════════════
# 模块级常量（GUI「基础参数」区 AST 反射源）
# ═══════════════════════════════════════════════════════════════
DEFAULT_LISTEN_HOST = "10.10.12.149"
DEFAULT_LISTEN_PORT = 14852
DEFAULT_UPSTREAM_ORIGIN = "https://cloud-gateway-uat.dmduav.com"
UAT_UPSTREAM_ORIGIN = "https://cloud-gateway-uat.dmduav.com"
PROMOTION_LIST_PATH = "/api/v1/promotion/list"
UPSTREAM_TIMEOUT_SECONDS = 15.0
MAX_EVENT_BUFFER = 2000
MAX_JSON_PARSE_BYTES = 1024 * 1024

# 逐跳头：代理层必须丢弃（RFC 7230 §6.1）；
# host/content-length/accept-encoding 由本层或 urllib 重新生成：
#   请求侧删 accept-encoding → 上游返回明文，可安全解析 JSON 后原样回写。
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_REQ_DROP_HEADERS = _HOP_HEADERS | {"host", "content-length", "accept-encoding"}
_RESP_DROP_HEADERS = _HOP_HEADERS | {"content-length"}

_UPSTREAM_TIMEOUT = UPSTREAM_TIMEOUT_SECONDS


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁用自动跟随重定向（透明透传 3xx，事件流可见）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, ARG002
        return None


# 联调场景上游常为 IP 直连 / 自签证书（如 https://10.20.2.34:443），
# 证书 CN 几乎必不匹配 → 默认不校验上游证书（对齐 mitmproxy 类联调工具语义）。
_UPSTREAM_SSL_CONTEXT = ssl._create_unverified_context()  # noqa: SLA001

_OPENER = urllib.request.build_opener(
    _NoRedirectHandler(),
    urllib.request.HTTPSHandler(context=_UPSTREAM_SSL_CONTEXT),
)


# ═══════════════════════════════════════════════════════════════
# 解析工具
# ═══════════════════════════════════════════════════════════════
def _try_parse_json(body: bytes) -> Any | None:
    """尝试把 body 解析为 JSON（超限/非 JSON/空 → None）。"""
    if not body or len(body) > MAX_JSON_PARSE_BYTES:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _decode_for_parse(body: bytes, content_encoding: str | None) -> bytes | None:
    """按 Content-Encoding 解压（仅用于解析；回写客户端仍是原始字节）。"""
    enc = (content_encoding or "").lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(body)
        if "deflate" in enc:
            return zlib.decompress(body)
    except Exception:
        return None
    return body


def parse_promotion_response(json_body: Any) -> dict | None:
    """深度解析 ``/api/v1/promotion/list`` 响应（不影响透传内容）。

    返回 ``{envelope_code, message, item_count, items:[{id,title,image_url,
    content_len,url}]}``（items 最多前 10 条）；非预期结构返回 None。
    """
    if not isinstance(json_body, dict):
        return None
    data = json_body.get("data")
    items: list[dict] = []
    if isinstance(data, list):
        for it in data[:10]:
            if isinstance(it, dict):
                items.append({
                    "id": it.get("id"),
                    "title": (it.get("title") or "")[:40],
                    "image_url": it.get("imageUrl"),
                    "content_len": len(it.get("content") or ""),
                    "url": it.get("url"),
                })
    return {
        "envelope_code": json_body.get("code"),
        "message": json_body.get("message"),
        "item_count": len(data) if isinstance(data, list) else None,
        "items": items,
    }


def _response_summary(body_len: int, content_type: str,
                      json_body: Any, parsed: dict | None) -> str:
    if isinstance(json_body, dict) and "code" in json_body:
        s = f"code={json_body.get('code')}"
        if parsed and parsed.get("item_count") is not None:
            s += f" items={parsed['item_count']}"
        return s
    ct = (content_type or "").split(";")[0]
    return f"{body_len}B {ct}".strip()


# ═══════════════════════════════════════════════════════════════
# HTTP 处理器
# ═══════════════════════════════════════════════════════════════
class _ProxyHandler(BaseHTTPRequestHandler):
    """透传处理器：每个请求 = 捕获事件 → 透传上游 → 捕获事件 → 原样回写。"""

    protocol_version = "HTTP/1.1"
    server_version = ""      # 回写时不附加 Server 头（send_response_only 不写默认头）
    sys_version = ""

    # 全部方法走同一透传路径
    def do_GET(self):    # noqa: N802
        self._handle()

    def do_POST(self):   # noqa: N802
        self._handle()

    def do_PUT(self):    # noqa: N802
        self._handle()

    def do_DELETE(self):  # noqa: N802
        self._handle()

    def do_PATCH(self):  # noqa: N802
        self._handle()

    def do_HEAD(self):   # noqa: N802
        self._handle()

    def do_OPTIONS(self):  # noqa: N802
        self._handle()

    # ── 事件桥 ──
    @property
    def _proxy(self) -> "FakeCloudGateway":
        return self.server.proxy  # type: ignore[attr-defined]

    def parse_request(self) -> bool:  # noqa: D102
        """覆写：非 HTTP 数据（如 TLS ClientHello）连入明文代理端口时发事件。

        默认实现解析失败仅静默关连接（或回 400），上位机完全无感知 ——
        典型场景是地面站 ``http_test_server.txt`` 写成了 ``https://`` 前缀。
        """
        ok = super().parse_request()
        if not ok:
            try:
                raw = getattr(self, "raw_requestline", b"") or b""
                preview = raw[:16].hex()
                self._proxy.emit_event({
                    "kind": "proxy_error", "req_id": 0, "ts": time.time(),
                    "method": "-", "path": f"{self.client_address[0]} → 代理",
                    "status": None,
                    "error": ("收到非 HTTP 数据（疑似 TLS/二进制流）。若地面站以 "
                              "https:// 指向本代理，请将 http_test_server.txt 改为 "
                              "http:// 前缀并重启地面站。数据预览: " + preview),
                    "summary": f"非 HTTP 数据(hex) {preview}",
                })
            except Exception:
                pass
        return ok

    def _handle(self) -> None:
        proxy = self._proxy
        method = self.command
        path = self.path
        req_id = proxy.next_req_id()

        # ---- 读请求体 ----
        body = self._read_request_body()

        # ---- 事件：地面站 → 云平台 ----
        auth = "Authorization" in self.headers
        client_version = self.headers.get("X-DGCS-VERSION", "")
        req_ct = self.headers.get("Content-Type", "")
        proxy.emit_event({
            "kind": "gcs_request", "req_id": req_id, "ts": time.time(),
            "method": method, "path": path, "status": None,
            "auth": auth, "client_version": client_version,
            "content_type": req_ct, "body_len": len(body),
            "json_body": _try_parse_json(body),
            "summary": (f"auth={int(auth)}"
                        + (f" ver={client_version}" if client_version else "")
                        + (f" body={len(body)}B" if body else "")),
        })

        # ---- 透传 ----
        upstream = proxy.get_upstream().rstrip("/")
        url = upstream + path
        fwd_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in _REQ_DROP_HEADERS
        }
        status, resp_headers, resp_body = self._forward(
            proxy, req_id, method, url, fwd_headers, body,
        )
        if status is None:   # _forward 已回写 502 并发事件
            return

        # ---- 事件：云平台 → 地面站 ----
        header_map = {k.lower(): v for k, v in resp_headers}
        content_type = header_map.get("content-type", "")
        parse_view = _decode_for_parse(resp_body, header_map.get("content-encoding"))
        json_body = _try_parse_json(parse_view) if parse_view is not None else None
        parsed = None
        if (json_body is not None and proxy.get_parse_promotion()
                and path.split("?")[0] == PROMOTION_LIST_PATH):
            parsed = parse_promotion_response(json_body)
        proxy.emit_event({
            "kind": "cloud_response", "req_id": req_id, "ts": time.time(),
            "method": method, "path": path, "status": status,
            "content_type": content_type, "body_len": len(resp_body),
            "json_body": json_body, "parsed": parsed,
            "summary": _response_summary(len(resp_body), content_type,
                                         json_body, parsed),
        })

        # ---- 原样回写（Content-Length 重算；body 字节不变）----
        out_headers = [
            (k, v) for k, v in resp_headers
            if k.lower() not in _RESP_DROP_HEADERS
        ]
        self._reply(status, out_headers, b"" if method == "HEAD" else resp_body)

    def _read_request_body(self) -> bytes:
        """读取请求体（当前支持 Content-Length；chunked 联调场景未用到）。"""
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            return b""   # 不支持 chunked 上行；返回空体透传（上游会按语义报错）
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return b""
        return self.rfile.read(n)

    def _forward(self, proxy: "FakeCloudGateway", req_id: int, method: str,
                 url: str, headers: dict[str, str], body: bytes):
        """透传到上游；网络级失败 → 502 + proxy_error 事件，返回 (None, None, None)。"""
        try:
            req = urllib.request.Request(
                url, data=body if body else None,
                headers=headers, method=method,
            )
            with _OPENER.open(req, timeout=_UPSTREAM_TIMEOUT) as resp:
                return resp.status, list(resp.getheaders()), resp.read()
        except urllib.error.HTTPError as e:      # 4xx/5xx 也是有效响应，原样透传
            return e.code, list(e.headers.items()), e.read()
        except Exception as e:                   # URLError / timeout / 连接拒绝
            proxy.emit_event({
                "kind": "proxy_error", "req_id": req_id, "ts": time.time(),
                "method": method, "path": url, "status": None,
                "error": repr(e), "summary": f"上游错误: {e}",
            })
            msg = f"fake_cloud upstream error: {e}".encode("utf-8")
            self._reply(502, [("Content-Type", "text/plain; charset=utf-8")], msg)
            return None, None, None

    def _reply(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        try:
            self.send_response_only(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except ConnectionError:
            # 客户端已断开（BrokenPipe / ConnectionReset / WinError 10053
            # ConnectionAborted —— 如地面站 10s 超时后放弃等待）
            pass

    def log_message(self, fmt: str, *args) -> None:  # 静音（事件流即为日志）
        pass


def _check_port_free(host: str, port: int) -> None:
    """端口占用预检。

    Windows 下 ``SO_REUSEADDR`` 允许多个 server **静默 bind 同一端口**（事件流
    会分裂），故在创建 server 前用 connect 探测判定「是否存在活跃监听」
    （TIME_WAIT 残留不会误报）；占用则抛 OSError → ``mgr_cls.__init__`` 同步
    失败 → GUI「添加失败」弹窗。server 本身仍带 allow_reuse_address
    （下线→上线快速重启不受 TIME_WAIT 影响）。
    """
    import socket as _socket
    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    occupied = False
    try:
        probe.settimeout(0.3)
        try:
            probe.connect((host, int(port)))
            occupied = True    # 能连上 → 有活跃监听
        except OSError:
            occupied = False  # 连接被拒/超时 → 无监听（TIME_WAIT 不影响）
    finally:
        probe.close()
    if occupied:
        raise OSError(f"端口 {host}:{port} 已被占用（存在活跃监听）")


class _ProxyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, proxy: "FakeCloudGateway"):
        _check_port_free(addr[0], addr[1])
        self.proxy = proxy
        super().__init__(addr, _ProxyHandler)


# ═══════════════════════════════════════════════════════════════
# FakeCloudGateway — 传输层（transport 角色）
# ═══════════════════════════════════════════════════════════════
class FakeCloudGateway:
    """云平台透明反向代理（SimulationPanel transport 契约）。

    契约要点：
      * ``local_ip`` / ``local_port`` → 设备列表第 2 列；
      * ``close()`` → 移除/下线清理（幂等）；
      * **无 ``sock`` 属性** → ``_patch_transport_socket`` 自动跳过（非 UDP 设备）。

    构造即 bind（端口占用在 ``mgr_cls.__init__`` 同步抛出 → GUI「添加失败」）；
    ``start()`` 启动 serve_forever 线程；配置实时读 sender（update_xxx 立即生效）。
    """

    def __init__(self, listen_host: str, listen_port: int,
                 upstream_origin: str,
                 event_sink: Callable[[dict], None] | None = None,
                 sender: Any = None):
        self.local_ip = listen_host
        self.local_port = int(listen_port)
        self.upstream_origin = upstream_origin
        self.event_sink = event_sink
        self.sender = sender            # _FakeCloudSender（配置宿主，可为 None）
        self._server = _ProxyHTTPServer((listen_host, self.local_port), self)
        self._serve_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ── 生命周期 ──
    def start(self) -> None:
        with self._lock:
            if self._serve_thread and self._serve_thread.is_alive():
                return
            self._serve_thread = threading.Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.2},
                daemon=True, name=f"FakeCloudGateway-{self.local_port}",
            )
            self._serve_thread.start()

    def close(self) -> None:
        with self._lock:
            srv, self._server = self._server, None
            thr, self._serve_thread = self._serve_thread, None
        # 仅当 serve_forever 循环在跑时才 shutdown —— BaseServer.shutdown()
        # 会 wait() 「循环退出」Event，从未 start 的 server 该 Event 永不 set，
        # 会永久阻塞（幂等：线程已死则直接关 socket）。
        if thr is not None and thr.is_alive() and srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            thr.join(timeout=2)
        if srv is not None:
            try:
                srv.server_close()
            except Exception:
                pass

    def is_serving(self) -> bool:
        return self._server is not None

    # ── 配置实时读取（update_xxx 修改 sender 后立即生效） ──
    def get_upstream(self) -> str:
        if self.sender is not None:
            u = getattr(self.sender, "upstream_origin", None)
            if u:
                return u
        return self.upstream_origin

    def get_parse_promotion(self) -> bool:
        if self.sender is not None:
            return bool(getattr(self.sender, "parse_promotion", True))
        return True

    # ── 事件桥（线程安全 seq 由 sender 分配） ──
    def next_req_id(self) -> int:
        if self.sender is not None and hasattr(self.sender, "next_req_id"):
            return self.sender.next_req_id()
        return int(time.time() * 1000) % 10_000_000

    def emit_event(self, event: dict) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(event)
            except Exception:
                pass  # 事件回调异常绝不影响透传主流程


# ═══════════════════════════════════════════════════════════════
# _FakeCloudSender — 协议响应器（sender 角色）
# ═══════════════════════════════════════════════════════════════
class _FakeCloudSender:
    """云平台代理 sender（配置宿主 + 事件汇）。

    SimulationPanel 契约：
      * ``update_xxx`` 方法自动反射为 GUI 控件（本阶段仅监听配置，
        篡改类方法留待后续阶段，GUI 不出现无效控件）；
      * ``running`` / ``thread`` / ``_run()`` / ``stop()`` 支撑「上线/下线」；
      * ``code`` / ``serial`` 供设备列表第 3 列显示；
      * ``set_msg_injector`` 为 UDP raw 注入兼容占位（HTTP 代理走结构化
        事件，GUI 通过 ``drain_events()`` 轮询，与 UDP 监控 _on_tick 同模式）。
    """

    def __init__(self, listen_host: str = DEFAULT_LISTEN_HOST,
                 listen_port: int = DEFAULT_LISTEN_PORT,
                 upstream_origin: str = DEFAULT_UPSTREAM_ORIGIN,
                 parse_promotion: bool = True,
                 max_events: int = MAX_EVENT_BUFFER,
                 log_manager: Any = None):
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.upstream_origin = upstream_origin
        self.parse_promotion = bool(parse_promotion)
        self.running = False
        self.thread: threading.Thread | None = None
        self.periodic_thread = None     # 无周期发送线程，占位（_is_sender_online 检查）
        self.code = str(self.listen_port)
        self.serial = upstream_origin
        self._log_manager = log_manager
        self._events: deque = deque(maxlen=int(max_events))
        self._event_lock = threading.Lock()
        self._event_seq = 0
        self._req_seq = 0
        self._event_callback: Callable[[dict], None] | None = None
        self._gateway: FakeCloudGateway | None = None
        self._gw_lock = threading.Lock()
        # 同步预 bind：端口占用在 mgr.__init__ 阶段同步抛出 → GUI「添加失败」；
        # 且 mgr 构造后立即可取到 gateway 引用（设备列表显示）。
        self._ensure_gateway()
        self.start()

    # ── 生命周期 ──
    def start(self) -> None:
        if self.running and self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._run, daemon=True,
            name=f"FakeCloudSender-{self.listen_port}",
        )
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        t = self.thread
        if t is not None and t.is_alive():
            t.join(timeout=5)
        self.thread = None

    def _run(self) -> None:
        """serve 循环：创建 gateway（bind）→ serve → running=False 后关闭并退出。

        下线后再上线：线程重启 → 重建 gateway（SO_REUSEADDR 下快速复用端口）。
        """
        while self.running:
            try:
                gw = self._ensure_gateway()
                gw.start()
            except Exception as e:
                self._emit_event({
                    "kind": "proxy_error", "req_id": 0, "ts": time.time(),
                    "method": "-", "path": f"{self.listen_host}:{self.listen_port}",
                    "status": None, "error": f"启动失败: {e}",
                    "summary": f"启动失败: {e}",
                })
                self.running = False
                break
            while self.running:
                time.sleep(0.2)
            gw = self._current_gateway()
            if gw is not None:
                gw.close()
            with self._gw_lock:
                self._gateway = None

    def _ensure_gateway(self) -> FakeCloudGateway:
        """获取或创建 gateway；构造即 bind（异常上抛给调用方）。"""
        with self._gw_lock:
            if self._gateway is None:
                self._gateway = FakeCloudGateway(
                    self.listen_host, self.listen_port,
                    self.upstream_origin,
                    event_sink=self._emit_event, sender=self,
                )
            return self._gateway

    def _current_gateway(self) -> FakeCloudGateway | None:
        with self._gw_lock:
            return self._gateway

    # ── update_xxx（本阶段仅监听配置；不影响透传内容） ──
    def update_upstream(self, upstream_origin: str = "") -> None:
        """切换上游云平台 origin（如 UAT: https://cloud-gateway-uat.dmduav.com）。"""
        if upstream_origin:
            self.upstream_origin = upstream_origin
            self.serial = upstream_origin

    def update_event_buffer(self, max_events: int = MAX_EVENT_BUFFER) -> None:
        """调整事件队列容量（缩小容量时丢弃最旧事件）。"""
        with self._event_lock:
            self._events = deque(self._events, maxlen=max(10, int(max_events)))

    def update_parse_promotion(self, enable: bool = True) -> None:
        """开关 /api/v1/promotion/list 响应的深度解析（不影响透传内容）。"""
        self.parse_promotion = bool(enable)

    # ── 事件汇（GUI 轮询入口 / 程序化订阅） ──
    def _emit_event(self, event: dict) -> None:
        with self._event_lock:
            self._event_seq += 1
            event["seq"] = self._event_seq
            self._events.append(event)
            cb = self._event_callback
        if cb is not None:
            try:
                cb(dict(event))
            except Exception:
                pass

    def next_req_id(self) -> int:
        with self._event_lock:
            self._req_seq += 1
            return self._req_seq

    def drain_events(self) -> list[dict]:
        """取走全部积压事件（GUI QTimer 轮询调用，线程安全）。"""
        with self._event_lock:
            out = list(self._events)
            self._events.clear()
        return out

    def set_event_callback(self, callback: Callable[[dict], None] | None) -> None:
        """程序化订阅事件（测试用；GUI 走 drain_events 轮询）。"""
        self._event_callback = callback

    def set_msg_injector(self, callback: Any) -> None:  # noqa: ARG002
        """UDP raw 注入兼容占位：HTTP 代理走结构化事件，不走该通道。"""


# ═══════════════════════════════════════════════════════════════
# _FakeCloudSenders — 批量管理器（mgr 角色）
# ═══════════════════════════════════════════════════════════════
class _FakeCloudSenders:
    """批量管理器（SimulationPanel mgr 契约）。

    ``__init__`` 参数即 GUI「添加设备」表单；创建 count 个代理实例，
    端口自 ``listen_port`` 起逐实例 +1。端口占用时在构造中同步抛出 →
    GUI「添加失败」弹窗。
    """

    def __init__(self, count: int = 1,
                 listen_host: str = DEFAULT_LISTEN_HOST,
                 listen_port: int = DEFAULT_LISTEN_PORT,
                 upstream_origin: str = DEFAULT_UPSTREAM_ORIGIN,
                 parse_promotion: bool = True,
                 max_events: int = MAX_EVENT_BUFFER,
                 log_manager: Any = None):
        self.cloud_senders: list[_FakeCloudSender] = []
        self.cloud_gateways: list[FakeCloudGateway] = []
        for i in range(max(1, int(count))):
            sender = _FakeCloudSender(
                listen_host=listen_host, listen_port=int(listen_port) + i,
                upstream_origin=upstream_origin,
                parse_promotion=parse_promotion,
                max_events=max_events, log_manager=log_manager,
            )
            self.cloud_senders.append(sender)
            # sender.__init__ 已同步 bind；gateway 引用供设备列表/清理使用
            self.cloud_gateways.append(sender._current_gateway())

    def stop(self) -> None:
        for s in self.cloud_senders:
            try:
                s.stop()
            except Exception:
                pass
