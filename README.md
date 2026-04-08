# poly-web3

![PyPI](https://img.shields.io/pypi/v/poly-web3)
![Python](https://img.shields.io/pypi/pyversions/poly-web3)
![License](https://img.shields.io/github/license/tosmart01/poly-web3)

面向 Polymarket 的 Python 单体仓库：通过 Relayer 在 **Proxy / Safe** 钱包上执行 **赎回（redeem）**、**拆分（split）**、**合并（merge）**；并附带 **手续费感知盈亏分析 Web 界面**（`analysis_poly`）与 **仓位工具**（`poly_position_watcher`）。

**语言：** [中文](README.md) | [English](README.en.md)

---

## 一、卸载通过 pip 从网络安装的旧版本

若你曾用 `pip install poly-web3` 或单独安装过 `analysis_poly`（或其它名称但指向同一套代码的包），建议先卸载再使用本仓库的本地安装，避免 `site-packages` 里混用旧 wheel 与新源码。

在**同一 Python 环境**中执行（可按需加上 `-y` 跳过确认）：

```bash
pip uninstall poly-web3 analysis_poly -y
```

确认已无残留：

```bash
pip show poly-web3 analysis_poly
# 若提示 WARNING: Package(s) not found 则表示已卸载干净
```

**说明：**

- 若你只安装过 `poly-web3`，第二条命令对 `analysis_poly` 报错是正常的。
- 若你使用 **可编辑安装** `pip install -e .` 过旧路径的仓库，同样用上面的 `uninstall` 卸载后再从**当前**克隆目录重新 `pip install -e .`。
- 可选：清理 pip 下载缓存（不影响已安装包，仅释放磁盘）  
  `pip cache purge`

---

## 二、克隆本仓库后的本地安装（推荐）

**要求：** Python **>= 3.11**

```bash
git clone https://github.com/kai586123/poly-web3.git
cd poly-web3

python3.11 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -U pip
pip install -e ".[dev]"
```

安装完成后，控制台会提供（与 `pyproject.toml` 中 `[project.scripts]` 一致）：

| 命令 | 说明 |
|------|------|
| `analysis-poly` | 仅启动 Web 服务（默认绑定 `0.0.0.0:8000`） |
| `analysis-poly-open` | 启动服务并在浏览器打开，可附带分析参数 |

**修改前端资源：** 若你改动了 `frontend/src/`，请在仓库根目录执行 `npm install && npm run build`，以刷新 `analysis_poly/static/dist/` 下的打包文件。

**与 PyPI 包的区别：** `pip install poly-web3` 通常对应已发布的 **SDK wheel**；要从本仓库获得 **完整** `poly_web3` + `analysis_poly` + `poly_position_watcher`，请使用上面的 **`pip install -e .`**。

---

## 三、分析与缓存、报告目录说明

分析器会将 **市场元数据缓存**、**按地址聚合的市场结果缓存** 等写入本机目录；**导出报告**默认在用户数据目录下。逻辑见 `analysis_poly/storage_paths.py`。

### 环境变量（可选，覆盖默认路径）

| 变量 | 作用 |
|------|------|
| `ANALYSIS_POLY_CACHE_DIR` | 缓存根目录（其下会再有子目录，见下表） |
| `ANALYSIS_POLY_DATA_DIR` | 应用数据根目录 |
| `ANALYSIS_POLY_REPORTS_DIR` | 分析报告输出目录（默认在数据目录下的 `reports`） |

未设置时，**缓存根目录**大致为：

| 系统 | 默认缓存根路径 |
|------|----------------|
| macOS | `~/Library/Caches/poly-web3` |
| Linux | `~/.cache/poly-web3` |
| Windows | `%LOCALAPPDATA%\poly-web3`（若不存在则回退到 `%APPDATA%\poly-web3`） |

在缓存根目录下常见子目录：

- `market_by_slug/` — 按 slug 缓存的市场元数据  
- `address_market_results/` — 按钱包地址聚合的分析结果缓存（与 `market_result_cache` 等逻辑配合）

**报告目录**在未设置 `ANALYSIS_POLY_REPORTS_DIR` 时，一般为：

- macOS：`~/Library/Application Support/poly-web3/reports`
- Linux：`~/.local/share/poly-web3/reports`
- Windows：`%APPDATA%\poly-web3\reports`

升级分析逻辑后若图表或数据异常，可删除对应缓存目录或提高结果缓存的 schema 版本后重新跑一次分析（以代码为准）。

---

## 四、网页分析器：如何启动

### 典型用法（打开浏览器并预填参数）

在已 `pip install -e .` 且虚拟环境已激活的前提下，于**仓库根目录**执行：

```bash
analysis-poly-open --address 0x你的钱包地址 --symbols btc --intervals 5,15
```

说明：

- `--address`：要分析的钱包地址（`0x` 开头）。
- `--symbols`：逗号分隔，如 `btc,eth`（与产品约定一致）。
- `--intervals`：逗号分隔的分钟周期，如 `5,15`。
- 默认在 `0.0.0.0:8000` 启动服务，并在浏览器打开；本机访问即 `http://localhost:8000/`。
- 常用可选参数：`--host`、`--port`、`--start-time`、`--end-time`（格式 `YYYY-MM-DD HH:MM`）、`--auto-start` 等；详见 `analysis_poly/open_with_params.py`。

### 仅启动服务（不自动开浏览器）

```bash
analysis-poly
# 等价于使用 uvicorn 启动 FastAPI 应用，默认端口仍为 8000（以 CLI 为准）
```

手动在浏览器访问 `http://localhost:8000/` 即可。

---

## 五、Split / Merge / Redeem 完整示例

以下示例与仓库内 `examples/example_split_merge.py`、`examples/example_redeem.py` 一致思路：**请先配置环境变量**（勿将密钥提交到 git）。

所需环境变量示例（名称以你本地 `.env` 为准）：

- `POLY_API_KEY`、`POLYMARKET_PROXY_ADDRESS`（或 Safe 地址）
- `BUILDER_KEY`、`BUILDER_SECRET`、`BUILDER_PASSPHRASE`（Builder 凭证，链上写操作依赖 Relayer，需按 [Polymarket Builders 文档](https://docs.polymarket.com/developers/builders/builder-intro) 申请）

```bash
pip install python-dotenv
```

```python
# -*- coding: utf-8 -*-
"""Split、Merge、Redeem 完整示例（二元市场；amount 为 USDC 人类单位）。"""
import os

import dotenv
from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
from py_clob_client.client import ClobClient

from poly_web3 import RELAYER_URL, PolyWeb3Service

dotenv.load_dotenv()

host = "https://clob.polymarket.com"
chain_id = 137  # Polygon 主网

client = ClobClient(
    host,
    key=os.getenv("POLY_API_KEY"),
    chain_id=chain_id,
    signature_type=1,  # Proxy；Safe 钱包使用 signature_type=2
    funder=os.getenv("POLYMARKET_PROXY_ADDRESS"),
)
client.set_api_creds(client.create_or_derive_api_creds())

relayer_client = RelayClient(
    RELAYER_URL,
    chain_id,
    os.getenv("POLY_API_KEY"),
    BuilderConfig(
        local_builder_creds=BuilderApiKeyCreds(
            key=os.getenv("BUILDER_KEY"),
            secret=os.getenv("BUILDER_SECRET"),
            passphrase=os.getenv("BUILDER_PASSPHRASE"),
        )
    ),
)

service = PolyWeb3Service(
    clob_client=client,
    relayer_client=relayer_client,
    rpc_url="https://polygon-bor.publicnode.com",
)

condition_id = "0xaba28be5f981580aa29a123afc8d233dd66c1f236f0d7e1bfffe07777cdb6cc5"
amount = 10  # USDC 人类单位

# ---------- Split：USDC 拆成 Yes/No 仓位 ----------
split_result = service.split(condition_id, amount)
print("split:", split_result)

# ---------- Merge：将 Yes/No 合并回 USDC ----------
merge_result = service.merge(condition_id, amount)
print("merge:", merge_result)

# ---------- 批量 Split / Merge ----------
split_batch_result = service.split_batch([{"condition_id": condition_id, "amount": 10}])
print("split_batch:", split_batch_result.model_dump_json(indent=2))

merge_batch_result = service.merge_batch([{"condition_id": condition_id, "amount": 10}])
print("merge_batch:", merge_batch_result.model_dump_json(indent=2))

# ---------- 扫描可 merge 的仓位（仅规划，不自动全部执行）----------
merge_plan = service.plan_merge_all(min_usdc=5, exclude_neg_risk=True)
for item in merge_plan:
    print(item.model_dump_json(indent=2))

merge_all_result = service.merge_all(min_usdc=1, batch_size=10)
print("merge_all:", merge_all_result)

# ---------- Redeem：赎回已结算仓位 ----------
redeem_all_result = service.redeem_all(batch_size=10)
print("redeem_all:", redeem_all_result)
if redeem_all_result.error_list:
    print("失败项:", redeem_all_result.error_list)
    print("可重试 condition_ids:", redeem_all_result.error_condition_ids)

condition_ids = [
    "0xaba28be5f981580aa29a123afc8d233dd66c1f236f0d7e1bfffe07777cdb6cc5",
]
redeem_batch_result = service.redeem(condition_ids, batch_size=10)
print("redeem:", redeem_batch_result)
if redeem_batch_result.error_list:
    print("失败项:", redeem_batch_result.error_list)
    print("可重试 condition_ids:", redeem_batch_result.error_condition_ids)
```

**行为说明摘要：**

- 可赎回列表来自官方 Positions API，可能有约 **1～3 分钟**延迟。
- `redeem` / `redeem_all` 返回 `RedeemResult`（含 `success_list`、`error_list`、`error_condition_ids`），失败项可据此重试。
- 负风险市场会通过 Gamma API 识别并走 NegRisk Adapter；`split`/`merge` 的 `amount` 均为 **USDC 人类单位**。

更细的 API 说明与英文文档见 [README.en.md](README.en.md)。

---

## 六、仓库结构（节选）

```
├── poly_web3/             # SDK：redeem / split / merge
├── analysis_poly/         # 分析引擎 + FastAPI + 前端静态资源
├── poly_position_watcher/ # 仓位与成交相关工具
├── frontend/              # React 源码 → 构建到 analysis_poly/static/dist
├── examples/              # 可运行示例脚本
├── tests/
└── pyproject.toml
```

---

## 七、开发与测试

```bash
pip install -e ".[dev]"
python -m pytest tests/
```

运行示例：

```bash
python examples/example_redeem.py
python examples/example_split_merge.py
```

---

## 许可证与链接

- 许可证：MIT  
- [Polymarket](https://polymarket.com/) · [Polygon](https://polygon.technology/)
