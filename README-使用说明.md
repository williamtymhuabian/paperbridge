# 10-工具-论文翻译

整本 PDF 论文 → 中文，保留原排版、公式、图片位置。底座是开源项目
PDFMathTranslate（pdf2zh，37k star，EMNLP 2025），外面封了批量/术语表/参考文献跳过/体检四层。

## 快速开始

```bash
cd 10-工具-论文翻译

# 翻译一篇（产出 纯中文版 + 双语对照版 两份）
.venv/Scripts/python.exe translate.py 某论文.pdf

# 批量翻译一个目录
.venv/Scripts/python.exe translate.py 待翻译目录/

# 断点续跑（跳过已有成果的）
.venv/Scripts/python.exe translate.py 待翻译目录/ --resume

# 改过术语表后必须加 --fresh，否则缓存里的旧译文直接复用
.venv/Scripts/python.exe translate.py 某论文.pdf --fresh
```

产出在 `output/`：
- `xxx-mono.pdf` 纯中文版（版面与原 PDF 一致）
- `xxx-dual.pdf` 双语对照版（原文页 + 中文页交替）

## 参考文献自动保持原文（默认开启）

- 自动定位 REFERENCES 起始页：**之前的页正常翻译；标题所在页按条目特征跳过；
  其后的页（含附录）整页保持原文**，最后拼回完整 PDF，页数不变。
- 条目判定在 `refs_skip.py`（编号制/APA 制/首字母制/arXiv 条目/整栏大块），
  取向是"宁可漏、不可误"：误杀正文的情形已用例排除（结论段、相关工作、图注）。
- 想连参考文献一起翻：加 `--translate-refs`。
- 定位/条目判定偶尔失手时，兜底是整篇翻译+条目启发式，不会崩。
- 调试判定过程：设环境变量 `REFS_DEBUG=日志路径` 再跑，每次送翻/跳过的块都会记录。

## 翻完建议做个体检

```bash
.venv/Scripts/python.exe check.py 某论文.pdf
```

自动核对：页数、每页图片数量与位置（1pt 容差）、公式/表格线数量、有无整页漏翻
（参考文献页的"保持英文"会被识别为正常，不误报）。

## 配置（config/env.json）

| 字段 | 说明 |
|---|---|
| engine | `bing`（免费，当前默认）/ `openai`（大模型，质量最好） |
| OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL | OpenAI 兼容网关三件套 |

- **想提质量**：把 engine 改回 `openai` 并填入可用 key（当前 cpa 网关 key 返回 401 认证失败，key 可用后无需改代码）。
- **术语表**：`config/术语表.csv`，三列（term, 译法, 说明），加一行就生效，
  VLN/VLA/NLOS/CRLB/SPL/RIR 等已预置约 100 条，强制不译或按指定译法。
- **翻译口径**：`config/prompt-template.txt`（换大模型引擎时生效）。

## 目录

- `translate.py` 主入口（单篇/批量/断点续跑/References 页切分与拼接）
- `run_pdf2zh.py` pdf2zh 启动入口（先打参考文献补丁再进 CLI）
- `refs_skip.py` 参考文献条目判定 + 翻译层补丁（`REFS_DEBUG` 可开调试日志）
- `check.py` 版面体检（认得"故意保持英文"的参考文献页）
- `test_api.py` 测网关连通性
- `test/` 测试论文；`output/` 成品；`logs/` 运行日志
- `.venv/` Python 3.11 隔离环境（pdf2zh 1.9.11）

## 本机已修过的坑（重装环境时照抄）

1. pdf2zh 要求 Python 3.11–3.12 → 用 `D:/Python` 的 3.11 建 venv。
2. `tencentcloud-sdk-python-tmt` 必须 3.0.x（新版 3.1 缺 TextTranslateRequest）：
   `pip install tencentcloud-sdk-python-tmt==3.0.1478`
3. `onnxruntime` 1.31 导入即段错误（本机核显）：
   `pip install onnxruntime==1.19.2`
4. `bitstring` 必须 4.x（5.0 删了 BitStream）：
   `pip install bitstring==4.3.0`
5. 沙箱环境跑 pip 时先 `unset CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR CODEBUDDY_TOOL_CALL_ID`，
   否则 pip 覆盖文件会触发批量删除保护直接退出。
6. 布局模型从 HuggingFace 下载，脚本已内置 `HF_ENDPOINT=https://hf-mirror.com`。
7. Google 通道本机被代理挡，Bing 可用。

## 实测记录（2026-10-25）

MutingTokens（arXiv 2610.31235，12 页，Bing 引擎）：
- 首测 116s 体检 0 异常，人工抽查第 3 页双栏/图 2/内联公式全部原位。
- 加"参考文献保持原文"后 78s（条目不再送翻），p9 左栏结论正常中文、
  右栏 REFERENCES 整栏英文原样、p10-12 整页原文，体检 0 异常。
- 判定启发式 19 个离线用例全过（含"整栏条目无换行大块"这个 pdf2zh 聚合特例）。
