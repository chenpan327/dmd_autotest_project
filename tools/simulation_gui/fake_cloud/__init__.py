"""fake_cloud — 云平台透明反向代理（监听 + 解析模式）。

依据 ``advertisement-popup-strategy.md`` §8（方案 A）落地的仿真组件：
拦截本地地面站与云平台之间的 HTTP 流量，做**纯透传 + 双向监听 + 协议解析**，
以结构化事件暴露给 GUI（``CloudProxyPanel`` 消息监视视图）。

当前版本为「监听阶段」：对请求/响应内容 **100% 透传，不做任何篡改或拦截改写**。
篡改框架（``tampered_response`` 事件类型 + ``json_diff`` 字段级高亮组件）已就位，
后续「篡改阶段」只需在代理层启用改写路径。

子模块：
    ad_proxy    — FakeCloudGateway / _FakeCloudSender / _FakeCloudSenders
    json_diff   — JSON 递归 diff 与 HTML 高亮（纯函数，预留篡改阶段）

零第三方依赖：stdlib ``http.server`` + ``urllib.request``。
"""
from __future__ import annotations

from .ad_proxy import (
    DEFAULT_LISTEN_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_UPSTREAM_ORIGIN,
    MAX_EVENT_BUFFER,
    PROMOTION_LIST_PATH,
    UAT_UPSTREAM_ORIGIN,
    FakeCloudGateway,
    _FakeCloudSender,
    _FakeCloudSenders,
    parse_promotion_response,
)
from .json_diff import diff_json, highlight_html, syntax_highlight

__all__ = [
    # 常量
    "DEFAULT_LISTEN_HOST",
    "DEFAULT_LISTEN_PORT",
    "DEFAULT_UPSTREAM_ORIGIN",
    "UAT_UPSTREAM_ORIGIN",
    "PROMOTION_LIST_PATH",
    "MAX_EVENT_BUFFER",
    # 类
    "FakeCloudGateway",
    "_FakeCloudSender",
    "_FakeCloudSenders",
    # 函数
    "parse_promotion_response",
    "diff_json",
    "highlight_html",
    "syntax_highlight",
]
