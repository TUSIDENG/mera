"""MERA 采集代理中继：容器内本地 HTTP 代理，接收 Camoufox/Playwright 请求，
转发到 1024proxy 住宅出口。

支持两种出站模式（MERA_RELAY_HOP1 / --no-hop1 切换）：

1. hop1 开启（默认，用于中国大陆等来源 IP 未加白的部署）：
       容器 → Clash(日本) → 1024proxy endpoint → target
2. hop1 关闭（用于日本/新加坡等已把服务器 IP 加入 1024proxy 白名单的部署）：
       容器 → 1024proxy endpoint → target

用法（worker 容器内）:
    python tools/proxy_chain_relay.py --port 9999            # 两步链
    python tools/proxy_chain_relay.py --port 9999 --no-hop1  # 直连 endpoint

启动后设置 MERA_FETCH_PROXY=http://127.0.0.1:9999，Camoufox 即透明走该链路。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import socketserver
import ssl
import threading
import time
import urllib.parse

# ── 配置（来自环境变量或命令行） ──
CLASH_HOST = os.environ.get("MERA_RELAY_CLASH_HOST", "host.docker.internal")
CLASH_PORT = int(os.environ.get("MERA_RELAY_CLASH_PORT", "6789"))
ENDPOINT_API = "https://white.1024proxy.com/white/api?region=Rand&num=5&time=10&format=1&type=txt"
# 1024proxy 白名单凭证 user:pass，只能由环境变量注入（禁止写入仓库）
ENDPOINT_CRED = os.environ.get("MERA_RELAY_ENDPOINT_CRED", "")
ENDPOINT_REFRESH_INTERVAL_SEC = 8 * 60  # 白名单 endpoint 90 分钟有效，每 8 分钟刷新
LOCAL_LISTEN_HOST = "127.0.0.1"
LOCAL_LISTEN_PORT = 9999
# 控制入口：丢弃当前 endpoint 并重新获取，供采集端在被 Cloudflare 挑战时换出口 IP
CONTROL_PATH = "/__rotate"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# 是否经 Clash 中转（hop1）。服务器已在 1024proxy 白名单内时设为 false。
HOP1_ENABLED = _env_flag("MERA_RELAY_HOP1", True)

AUTH_B64 = base64.b64encode(ENDPOINT_CRED.encode()).decode()

# ── endpoint 缓存 ──
_endpoint: tuple[str, int] | None = None
_endpoint_expires_at: float = 0.0
_endpoint_checked_at: float = 0.0
_endpoint_lock = threading.Lock()


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[proxy-chain {ts}] {msg}", flush=True)


def _recv_header(sock: socket.socket) -> bytes:
    """读取 HTTP 响应头，直到空行。"""
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(4096)
        if not chunk:
            break
        header += chunk
    return header


def _dial_endpoint(endpoint_host: str, endpoint_port: int,
                   timeout: float = 20.0) -> socket.socket:
    """建立到 1024proxy endpoint 的 TCP 连接。

    HOP1_ENABLED=True  ：经 Clash 中转（Clash → endpoint）。
    HOP1_ENABLED=False ：直接连接 endpoint，适用于来源 IP 已在白名单的部署。
    """
    if not HOP1_ENABLED:
        return socket.create_connection((endpoint_host, endpoint_port), timeout=timeout)

    s = socket.create_connection((CLASH_HOST, CLASH_PORT), timeout=timeout)
    req = (
        f"CONNECT {endpoint_host}:{endpoint_port} HTTP/1.1\r\n"
        f"Host: {endpoint_host}:{endpoint_port}\r\n"
        "Proxy-Connection: close\r\n\r\n"
    ).encode()
    s.sendall(req)
    s.settimeout(timeout)
    header = _recv_header(s)
    first = header.split(b"\r\n")[0]
    if b"200" not in first:
        s.close()
        raise RuntimeError(f"Clash->endpoint CONNECT failed: {first.decode(errors='replace')}")
    return s


PROBE_HOST = os.environ.get("MERA_RELAY_PROBE_HOST", "arena.ai")
PROBE_PATH = os.environ.get("MERA_RELAY_PROBE_PATH", "/")
# 目标站返回这些标记说明命中了 Cloudflare 挑战页。注意：挑战页只代表裸 HTTP 过不去，
# 真实浏览器（Camoufox）仍可能通过 JS 校验，所以它只是「次优」而非「不可用」。
_CF_MARKERS = (b"Just a moment", b"challenge-platform", b"__cf_chl", b"cf-mitigated")
# endpoint 健康状态：干净 / 被挑战（浏览器仍可能过）/ 不可用
PROBE_CLEAN = "clean"
PROBE_CHALLENGED = "challenged"
PROBE_DEAD = "dead"
# 缓存 endpoint 的复检间隔，避免每个 CONNECT 都向目标站打一次探测请求
CACHE_PROBE_INTERVAL_SEC = 60


def _probe_endpoint(endpoint_host: str, endpoint_port: int,
                    max_time: float = 25.0) -> str:
    """探测 endpoint 访问目标站的可用程度。

    走 HTTPS（443 + SNI）而不是 HTTP：浏览器实际访问的是 HTTPS，Cloudflare 对
    HTTP/HTTPS 的策略也不完全一致，且握手失败的 endpoint 本来就无法承载浏览器流量。
    返回 clean / challenged / dead 三态，由调用方决定「优先干净、退而用被挑战的 IP」。
    """
    import select

    raw = None
    try:
        raw = _connect_via_endpoint(endpoint_host, endpoint_port, PROBE_HOST, 443)
        ctx = ssl.create_default_context()
        s = ctx.wrap_socket(raw, server_hostname=PROBE_HOST)
        s.settimeout(max_time)
        s.sendall(
            f"GET {PROBE_PATH} HTTP/1.1\r\nHost: {PROBE_HOST}\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
            "Accept: text/html\r\nConnection: close\r\n\r\n".encode()
        )
        buf = b""
        deadline = time.time() + max_time
        while len(buf) < 8192:
            remain = deadline - time.time()
            if remain <= 0:
                break
            ready, _, _ = select.select([s], [], [], remain)
            if not ready:
                break
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\r\n\r\n" in buf and len(buf) >= 600:  # 头 + 足够正文即可判定
                break
        s.close()
        first = buf.split(b"\r\n", 1)[0]
        if b"HTTP/" not in first:
            return PROBE_DEAD
        if any(marker in buf for marker in _CF_MARKERS):
            return PROBE_CHALLENGED
        if any(code in first for code in (b"200", b"301", b"302")):
            return PROBE_CLEAN
        return PROBE_CHALLENGED  # 其它状态码多为风控，交给浏览器再试
    except Exception:  # noqa: BLE001 - 探测失败视为不可用
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass
        return PROBE_DEAD


def _cache_endpoint(host: str, port: int, note: str) -> tuple[str, int]:
    """把可用 endpoint 写入缓存并返回。"""
    global _endpoint, _endpoint_expires_at, _endpoint_checked_at
    _endpoint = (host, port)
    _endpoint_expires_at = time.time() + ENDPOINT_REFRESH_INTERVAL_SEC
    _endpoint_checked_at = time.time()
    _log(f"endpoint = {host}:{port} ({note}, expires {ENDPOINT_REFRESH_INTERVAL_SEC}s)")
    return _endpoint


def _fetch_endpoint(avoid: set[str] | None = None) -> tuple[str, int]:
    """从 1024proxy white API 获取新 endpoint。
    hop1 开启时经 Clash 访问（确保来源 IP 已加白）；关闭时直连，
    适用于服务器 IP 本身已在白名单的部署。
    一次取多个候选，优先选能干净访问目标站的，其次退让给「被 CF 挑战」的
    （裸 HTTP 过不去但真实浏览器仍可能通过），最多重试 3 轮。
    avoid 为刚刚用过的出口 IP：同一 IP 换会话端口对 Cloudflare 无区别，
    必须整段跳过，否则「换 IP」实际没换。"""
    global _endpoint, _endpoint_checked_at
    with _endpoint_lock:
        now = time.time()
        if _endpoint and now < _endpoint_expires_at - 30:  # 30s 缓冲
            if now - _endpoint_checked_at < CACHE_PROBE_INTERVAL_SEC:
                return _endpoint
            # 缓存的 endpoint 按间隔复检，避免每个 CONNECT 都探一次目标站
            state = _probe_endpoint(_endpoint[0], _endpoint[1])
            _endpoint_checked_at = now
            if state != PROBE_DEAD:
                return _endpoint
            _log(f"cached endpoint {_endpoint[0]}:{_endpoint[1]} dead, refreshing")

        import subprocess
        last_exc: Exception | None = None
        fallback: tuple[str, int] | None = None
        reused: tuple[str, int] | None = None
        avoid = avoid or set()
        fetch_route = f"via Clash {CLASH_HOST}:{CLASH_PORT}" if HOP1_ENABLED else "direct"
        for attempt in range(1, 4):  # 最多 3 次
            _log(f"fetching fresh endpoint ({fetch_route}, attempt {attempt}/3)...")
            try:
                cmd = ["curl", "-s", "--max-time", "20"]
                if HOP1_ENABLED:
                    cmd += ["-x", f"http://{CLASH_HOST}:{CLASH_PORT}"]
                else:
                    # 容器里可能配了系统代理，直连模式必须显式绕过
                    cmd += ["--noproxy", "*"]
                cmd.append(ENDPOINT_API)
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                )
                candidates = [ln.strip() for ln in result.stdout.splitlines() if ":" in ln]
                if not candidates:
                    raise RuntimeError(f"bad endpoint list: {result.stdout.strip()!r}")
                for candidate in candidates:
                    host, port_str = candidate.split(":", 1)
                    port = int(port_str)
                    state = _probe_endpoint(host, port)
                    if state == PROBE_DEAD:
                        _log(f"endpoint {host}:{port} dead, skipping")
                        continue
                    if host in avoid:
                        # 换 IP 时不能复用同一出口 IP（端口不同 IP 相同，CF 判定不变）
                        reused = reused or (host, port)
                        _log(f"endpoint {host}:{port} recently used, skipping")
                        continue
                    if state == PROBE_CLEAN:
                        return _cache_endpoint(host, port, "ok")
                    if fallback is None:
                        fallback = (host, port)
                        _log(f"endpoint {host}:{port} challenged by CF, kept as fallback")
                    else:
                        _log(f"endpoint {host}:{port} state={state}, skipping")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                _log(f"endpoint fetch attempt {attempt} error: {exc!s}")
        # 没有干净 IP 时退而使用被挑战的：Camoufox 能跑 JS 过挑战页，比直接失败好
        if fallback:
            _log("no clean endpoint, using CF-challenged one (browser may still pass)")
            return _cache_endpoint(fallback[0], fallback[1], "challenged")
        # IP 池被 1024proxy 复用到只剩刚用过的那个：只能沿用，但明确记录
        if reused:
            _log(f"pool exhausted, reusing same exit IP {reused[0]}")
            return _cache_endpoint(reused[0], reused[1], "reused")
        # 全部失败：如果有旧 endpoint 就先用
        if _endpoint:
            _log(f"all fetch attempts failed, using cached {_endpoint[0]}:{_endpoint[1]}")
            return _endpoint
        detail = (f": {last_exc!s}" if last_exc
                  else "（取到的 endpoint 全部不可用）")
        raise RuntimeError(f"failed to get working endpoint after 3 attempts{detail}")


def _rotate_endpoint() -> tuple[str, int]:
    """丢弃缓存的 endpoint 并立刻重新获取（被目标站挑战时换出口 IP）。"""
    global _endpoint, _endpoint_expires_at
    with _endpoint_lock:
        previous = _endpoint[0] if _endpoint else None
        _endpoint = None
        _endpoint_expires_at = 0.0
    _log(f"control: rotate endpoint (avoid {previous or '-'})")
    return _fetch_endpoint({previous} if previous else None)


def _is_control_target(target: str) -> bool:
    path = urllib.parse.urlsplit(target).path or target
    return path.rstrip("/") == CONTROL_PATH


def _connect_via_endpoint(endpoint_host: str, endpoint_port: int,
                          target_host: str, target_port: int) -> socket.socket:
    """经 1024proxy endpoint 连到 target。
    返回已建立的 TCP tunnel socket（200 Connection established 后）。
    """
    # Hop 1（可选）: container -> [Clash] -> endpoint
    s = _dial_endpoint(endpoint_host, endpoint_port)
    # endpoint 需要几秒来初始化代理会话，立刻发 hop2 会超时
    time.sleep(1.5)

    # Hop 2: endpoint -> target (HTTP proxy CONNECT with auth)
    req2 = (
        f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
        f"Host: {target_host}:{target_port}\r\n"
        f"Proxy-Authorization: Basic {AUTH_B64}\r\n"
        "Proxy-Connection: close\r\n\r\n"
    ).encode()
    s.sendall(req2)
    s.settimeout(30)
    resp2 = b""
    while b"\r\n\r\n" not in resp2:
        chunk = s.recv(4096)
        if not chunk:
            break
        resp2 += chunk
    first2 = resp2.split(b"\r\n")[0]
    if b"200" not in first2:
        s.close()
        raise RuntimeError(f"endpoint->{target_host}:{target_port} CONNECT failed: "
                           f"{first2.decode(errors='replace')}\n{resp2.decode(errors='replace')[:500]}")
    return s


def _relay_data(src: socket.socket, dst: socket.socket) -> None:
    """双向 TCP 数据转发，直到一方关闭或超时报错。"""
    def _pipe(a: socket.socket, b: socket.socket, direction: str) -> None:
        try:
            a.settimeout(30)
            while True:
                data = a.recv(32768)
                if not data:
                    break
                try:
                    b.sendall(data)
                except OSError:
                    break
        except (socket.timeout, OSError):
            pass

    t1 = threading.Thread(target=_pipe, args=(src, dst, "A->B"), daemon=True)
    t2 = threading.Thread(target=_pipe, args=(dst, src, "B->A"), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)


class _Handler(socketserver.StreamRequestHandler):
    """处理 Camoufox/Playwright 发来的 HTTP proxy 请求。
    支持 CONNECT（HTTPS）和普通 HTTP 请求。
    """

    def handle(self) -> None:
        try:
            # 读完整的首行 + headers（不读 body，Camoufox 不发 body 到代理）
            self.request.settimeout(30)
            header_buf = b""
            while b"\r\n\r\n" not in header_buf:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                header_buf += chunk
            header_text = header_buf.decode(errors="replace")
            lines = header_text.split("\r\n")
            if not lines:
                return
            first = lines[0]
            parts = first.split(" ")
            if len(parts) < 3:
                return
            method, target, _ = parts

            if method == "CONNECT":
                self._handle_connect(target)
            elif _is_control_target(target):
                self._handle_control()
            else:
                self._handle_http(header_text, header_buf)
        except Exception as exc:  # noqa: BLE001 - 单连接失败不影响其他
            _log(f"handler error: {exc!s}")
        finally:
            try:
                self.request.close()
            except OSError:
                pass

    def _handle_control(self) -> None:
        """控制请求：轮换 endpoint 并返回结果（不走代理链路）。"""
        try:
            host, port = _rotate_endpoint()
            body = json.dumps({"ok": True, "endpoint": f"{host}:{port}"}).encode()
            status = "200 OK"
        except Exception as exc:  # noqa: BLE001 - 轮换失败也要给出可读响应
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            status = "503 Service Unavailable"
        self.request.sendall(
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode() + body
        )

    def _handle_connect(self, target: str) -> None:
        """HTTPS 隧道：两步链 CONNECT 后透明转发。"""
        host, _, port_s = target.partition(":")
        port = int(port_s) if port_s else 443
        endpoint = _fetch_endpoint()
        _log(f"CONNECT {host}:{port} via {endpoint[0]}:{endpoint[1]}")
        tunnel = _connect_via_endpoint(endpoint[0], endpoint[1], host, port)
        # 告诉 Camoufox 隧道已建立
        try:
            self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        except OSError:
            tunnel.close()
            return
        # 双向转发，直到一方关闭
        try:
            _relay_data(self.request, tunnel)
        finally:
            tunnel.close()

    def _handle_http(self, header_text: str, header_buf: bytes) -> None:
        """普通 HTTP 请求：两步链转发整个请求。"""
        lines = header_text.split("\r\n")
        first = lines[0]
        method, target, version = first.split(" ", 2)
        parsed = urllib.parse.urlparse(target)
        host = parsed.hostname or ""
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if not host:
            return

        endpoint = _fetch_endpoint()
        _log(f"HTTP {method} {host}{path[:60]} via {endpoint[0]}:{endpoint[1]}")
        tunnel = _connect_via_endpoint(endpoint[0], endpoint[1], host, port)
        # 重写首行为绝对路径（代理要求）
        lines[0] = f"{method} {path} {version}"
        new_header_text = "\r\n".join(lines) + "\r\n\r\n"
        tunnel.sendall(new_header_text.encode())
        # 读完整响应再转发（简单处理，不做流式 chunked 重组）
        tunnel.settimeout(30)
        tunnel.settimeout(60)
        try:
            _relay_data(self.request, tunnel)
        finally:
            tunnel.close()


class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    global HOP1_ENABLED
    parser = argparse.ArgumentParser(description="MERA proxy relay (-> 1024proxy -> target)")
    parser.add_argument("--port", type=int, default=LOCAL_LISTEN_PORT, help="local listen port")
    parser.add_argument("--host", default=LOCAL_LISTEN_HOST, help="local listen host")
    parser.add_argument("--no-hop1", action="store_true",
                        help="skip the Clash hop and dial 1024proxy directly "
                             "(server IP already whitelisted); same as MERA_RELAY_HOP1=0")
    args = parser.parse_args()
    if args.no_hop1:
        HOP1_ENABLED = False
    if not ENDPOINT_CRED:
        raise SystemExit(
            "MERA_RELAY_ENDPOINT_CRED 未设置：请在 .env 注入 1024proxy 白名单凭证（user:pass）"
        )

    route = f"Clash {CLASH_HOST}:{CLASH_PORT} -> 1024proxy" if HOP1_ENABLED else "1024proxy (direct)"
    _log(f"outbound route: {route}")

    # 预热 endpoint
    _fetch_endpoint()

    with _ThreadedServer((args.host, args.port), _Handler) as srv:
        _log(f"proxy relay listening on {args.host}:{args.port}")
        _log(f"endpoint_api = {ENDPOINT_API}")
        _log(f"matching MERA_FETCH_PROXY=http://{args.host}:{args.port}")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            _log("shutting down")


if __name__ == "__main__":
    main()
