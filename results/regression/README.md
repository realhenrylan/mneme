# 回归证据归档（2026-09-09 / 2026-10-31）

本目录保存可入库的回归证据副本，供版本库直接追溯，不依赖本机临时文件或 CI artifact。
日志均为 `pytest -q` 原始输出（无 ANSI 颜色、未编辑），SHA-256 见各表。

## 2026-10-31 默认套件（绿）

| 项 | 值 |
|---|---|
| 工作树 | `main` @ `1066d60a31b754cdf8054200a63066e64a8bd9e1` + T1–T8 改动（两个本地提交，未 push；提交哈希见 `git log`） |
| 运行时间 | 2026-10-31 22:09–22:15（Asia/Shanghai） |
| 耗时 | 327.98 s（0:05:27） |
| 命令 | `$env:PYTHONUTF8='1'; python -m pytest -q --ignore=tests/analysis -m "not frozen_stage" -p no:cacheprovider` |
| 环境 | Windows + PowerShell 7；Python 3.12.10 + pytest 9.0.3（系统解释器） |
| 读数 | **2653 passed / 8 skipped / 318 deselected / 0 failed / 0 errors** |
| 归档文件 | `2026-10-31-default-suite.log`（3,058 字节，38 行） |
| SHA-256 | `C8D7CECA255F80F899D615809DB87C32D171292BF93DB8B89633409856EA6E17` |

## 2026-10-31 冻结阶段套件（known-red）

| 项 | 值 |
|---|---|
| 工作树 | 同上（同一工作树、同一解释器） |
| 耗时 | 21.35 s |
| 命令 | `python -m pytest -q --ignore=tests/analysis -m frozen_stage -p no:cacheprovider --tb=line` |
| 预期退出码 | `1`（known-red，非 0 是预期行为） |
| 读数 | **240 failed / 78 errors / 2661 deselected / 0 passed** |
| 归档文件 | `2026-10-31-frozen-stage.log`（140,810 字节，1,180 行） |
| SHA-256 | `B389CF368D9F17F96F9E142956B9FDF21AEC11F5E8F976EEC6526227FB0CE6E1` |

> `--tb=line` 只压缩 traceback 展示，不改变收集集合与 failed/errors 计数；使用默认
> traceback 会得到约 1.3 MB 的日志，不利于入库。
>
> 该读数的 failed/errors 数与 2026-09-09 基线**逐项一致**（240 / 78），证明隔离是
> “把同一批历史门禁移出默认套件并独立复现”，不是掩盖或改写失败。该 job 在 CI 中
> 为 `continue-on-error: true` 的非阻断任务。

## 2026-09-09 全量回归（修复前基线）

| 项 | 值 |
|---|---|
| 来源 commit | `1066d60a31b754cdf8054200a63066e64a8bd9e1`（`main`，2026-09-09） |
| 运行时间 | 2026-09-09 22:44（Asia/Shanghai） |
| 耗时 | 282.49 s（0:04:42） |
| 命令 | `python -m pytest -q --ignore=tests/analysis` |
| 环境 | Python 3.12 + pytest 9.0.3（系统解释器） |
| 读数 | **2653 passed / 240 failed / 78 errors / 8 skipped** |
| 归档文件 | `2026-09-09-full-regression.log`（36,802 字节，362 行） |
| SHA-256 | `2FFC13931A5A3693B1E657589A92BD81DA7F841F6466403960BE55B09077C18F` |

> 环境备注：`venv/` 未安装 dev extras，`venv\Scripts\python.exe -m pytest` 会报
> `No module named pytest`；复现前需在目标环境执行 `pip install -e ".[dev]"`。
> 该日志不含命令行/版本头，环境信息依据执行上下文复原，无法从文件内部独立核验。

## 已知失败根因（frozen_stage 为何保留）

冻结阶段门禁测试在 preflight 中断言“当前输入 SHA == 该阶段 manifest `inputs`”，
而共享真值 `evaluation/datasets/v2/annotations/v2-cases-draft.jsonl` 已在 `f28cce5`
（2026-08-29 Round-2 人审修复）被原地改写，导致 v2.0.5–v2.1.1 语料治理阶段门禁
在 preflight 中 fail-closed：约 85% 的 failed 集中在 12 个套件，78 个 errors 集中在
另外 6 个套件的 setup/teardown（抽样确认同一机制）。这是测试与共享真值文件的耦合，
**不是产品代码回归**。

处置：`frozen_stage` marker 精确覆盖 318 个已知红节点——1 个全红测试模块保留模块级
marker（12 例），其余 30 个测试文件用 305 个函数级 marker 覆盖 306 个节点（一个参数化
用例的两个节点共用同一 marker）。因此 285 个原本通过的历史用例已恢复进入默认套件：
默认套件 2,661 selected = 2,653 passed + 8 skipped，318 known-red 仅在独立 job 复现。
详见 [docs/STATUS.md](../../docs/STATUS.md) 的 P0-1。

## 复现

```powershell
# Windows PowerShell：必须先设置 PYTHONUTF8，否则 TUI/子进程相关用例会因 GBK 控制台失败
$env:PYTHONUTF8='1'
python -m pytest -q --ignore=tests/analysis -m "not frozen_stage" -p no:cacheprovider
python -m pytest -q --ignore=tests/analysis -m frozen_stage -p no:cacheprovider
```

> 编码注意：不要用 `PYTHONIOENCODING=utf-8` 代替 `PYTHONUTF8=1`——前者会让子进程输出
> UTF-8 而父进程仍按 GBK 解码，导致 fresh-process 测试的 `stderr` 变 `None`；也不要为
> 默认套件设置 `MNEME_DATA_DIR` 沙箱，配置契约测试需要在真实默认目录下断言模块常量。

若当前环境缺少 pytest，请先执行 `pip install -e ".[dev]"`。
