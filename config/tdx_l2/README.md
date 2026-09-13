# TDX L2 实时盘口接入（占位）

本目录**只放说明文档，不存放任何加密的通达信插件文件**（如 `nbcomte.dat`）。

## 工作机制

```
┌────────────────────┐      L2 行情       ┌──────────────────────┐
│  通达信客户端      │◄──────────────────►│  通用 L2 站点          │
│  D:\tdx7\TdxW.exe  │  nbcomte.dat 解析  │  (cctv 已在 nbcomte  │
│  (T0002 用户目录)  │                    │   配置)               │
└────────────────────┘                    └──────────────────────┘
        │  ↑                                       ▲
        │  │ 共享 vipdoc / 共享 L2 缓存             │
        │  └───────────────────────────────────────┘
        ▼
┌────────────────────┐
│ XGDA Real 模式     │  9:25 选股后调
│ scripts/run_real_  │  l2_verify.verify_with_l2()
│ live.py            │  → 二次筛选 watchlist
└────────────────────┘
```

## 关键事实

1. **nbcomte.dat 已在 `D:\tdx7\` 客户端根下就绪**（2026-08-01 已生效）
   - 验证：`ls D:\tdx7\nbcomte.dat` 输出 9636 字节文件
   - **本项目不需要自己解析它**
2. **L2 行情是"借道"而来**——必须先启动通达信客户端，让其把 L2 行情拉下来共享给其它进程
3. **XGDA 接入抽象层**——`xgda/data_source/tdx_socket.py` 提供 `TdxL2Client` / `L2QuoteFetcher`
   - 默认实现 `NoopL2Fetcher`：返回 `L2Quote(unknown=True)`，不动 L2
   - 真实接入：cctv 后续按 `tdx_socket.py` 协议层实现协议（`pytdx`/`mootdx`/`eltdx` 任选其一）

## 为什么不能直接读 nbcomte.dat

- 二进制加密，仅 TdxAsioComm64.dll 内的客户端代码能解析
- 协议不公开，绕过客户端直接读属于逆向工程范畴，存在合规风险
- XGDA 是分析/选股工具，**L2 行情获取走通达信官方客户端提供的接口**，而不碰加密配置

## 接入示例（cctv 自行实现）

```python
from xgda.data_source.tdx_socket import TdxL2Client, L2Quote

client = TdxL2Client(host="127.0.0.1", port=7709)  # 标准 TDX TCP 端口
client.connect()
quote = client.get_l2_quote("000001")
print(quote.bid1_price, quote.bid1_volume)
```

`L2Quote` 字段定义见 `xgda/data_source/tdx_socket.py` 文件头。
