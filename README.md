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

## 二、克隆本仓库后如何使用（不污染系统 Python）

**要求：** Python **>= 3.11**

本仓库的**推荐用法**是：只把**第三方依赖**装进虚拟环境（`requirements.txt`），**不要把本项目做成 pip 包**（不使用 `pip install -e .` / `pip install .`）。在本目录运行时代码时，用 **`PYTHONPATH`** 指向仓库根目录即可导入 `poly_web3`、`analysis_poly` 等。

### 推荐步骤

```bash
git clone https://github.com/kai586123/poly-web3.git
cd poly-web3

python3.11 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
# 开发 / 跑测试时可选：pip install -r requirements-dev.txt

export PYTHONPATH="${PWD}:${PYTHONPATH}"
```

之后可直接：

```bash
python main.py
# 或（等价于曾经的 analysis-poly / analysis-poly-open 命令行入口，但不依赖 pip 安装本仓库）
./scripts/analysis-poly
./scripts/analysis-poly-open --address 0x你的地址 --symbols btc --intervals 5,15
```

亦可用模块方式（同样需已 `export PYTHONPATH` 且当前目录为仓库根）：

```bash
python -m analysis_poly.cli
python -m analysis_poly.open_with_params --help
```

在任意脚本里引用 SDK：

```python
import sys
sys.path.insert(0, "/path/to/poly-web3")
from poly_web3 import PolyWeb3Service
```

**修改前端资源：** 若你改动了 `frontend/src/`，请在仓库根目录执行 `npm install && npm run build`，以刷新 `analysis_poly/static/dist/` 下的打包文件。

### 关于「完全不使用 pip」

**做不到**在仍从 PyPI 拉取依赖的前提下，完全跳过 `pip`（或同类工具）：`web3`、`pydantic` 等必须先安装到**某个**解释器环境里。若坚持零 pip，只能自行把依赖 wheel **vendor 进仓库**并改 `PYTHONPATH`，维护成本很高，本项目不提供。

`pip install -r requirements.txt` **只会**安装 `requirements.txt` 里的第三方包，**不会**把本仓库安装成 site-packages 里的一个发行版，因此满足「不采用 pip 安装本项目的模式」。

### 与 `pyproject.toml` / PyPI 的关系

`pyproject.toml` 仍用于声明元数据；发布到 PyPI 的安装方式与上述「仅克隆 + requirements」并行存在。日常开发可只认 **`requirements.txt`**。

---

## 三、分析与缓存、报告目录说明

分析器将缓存与报告写在磁盘上；逻辑见 `analysis_poly/storage_paths.py`。

### 默认：从源码目录运行时，缓存与报告在仓库内

当 `analysis_poly` 是从**带 `pyproject.toml` 的克隆目录**加载（例如 `PYTHONPATH` 指向该目录、或从该目录运行）且**未**设置下面的环境变量时，默认路径为：

| 用途 | 路径 |
|------|------|
| 缓存根目录 | `<仓库根>/.cache/poly-web3/` |
| 报告目录 | `<仓库根>/.data/poly-web3/reports/` |

上述目录已写入 `.gitignore`，不会随 `git add` 提交。

子目录示例（在缓存根下）：

- `market_by_slug/` — 按 slug 缓存的市场元数据  
- `address_market_results/` — 按地址聚合的分析结果缓存  

若从 **PyPI wheel** 安装到 `site-packages`（非源码树），未设置环境变量时仍使用**操作系统用户目录**（与旧版一致），见下表。

| 系统 | 默认缓存根（wheel / 非源码树） |
|------|-------------------------------|
| macOS | `~/Library/Caches/poly-web3` |
| Linux | `~/.cache/poly-web3` |
| Windows | `%LOCALAPPDATA%\poly-web3`（或回退 `%APPDATA%\poly-web3`） |

**报告目录**（wheel / 非源码树、且未设置 `ANALYSIS_POLY_REPORTS_DIR`）一般为：macOS 下 `~/Library/Application Support/poly-web3/reports`，Linux `~/.local/share/poly-web3/reports`，Windows `%APPDATA%\poly-web3\reports`。

### 环境变量（可选，覆盖默认路径）

| 变量 | 作用 |
|------|------|
| `ANALYSIS_POLY_CACHE_DIR` | 缓存根目录 |
| `ANALYSIS_POLY_DATA_DIR` | 应用数据根目录 |
| `ANALYSIS_POLY_REPORTS_DIR` | 分析报告输出目录 |

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
