# Mneme 答案级评测线 M3 报告：受约束 judge 子集

- 协议版本：`al2-judge-v1`（verdict 外置词表 ['hit', 'miss', 'partial']；max_tokens=500；尝试上限=3）
- judge 模型：`deepseek-chat`（llm_call 缺省走 Settings，与 M2 生成同模型——见 §8 自判偏置披露）
- 数据源：M2 密封产物 `results\answer-level\m2-baseline-2026-08-30`（m2_outcomes_sha256=6e4d59e1c7a6…），数据集 `v2.1`（dataset_sha256=4597167dadd7…）
- 密封：`outcomes_sha256=87f4f1cccd33…`，`manifest_sha256=3fb2d1ec1a31…`（自哈希 MATCH；本报告只读不写回）
- 本轮基线：judge 只判 M2 机械 miss 要点（154 条 / 覆盖 107 例），不重跑 M2。

## 1. judge 三态分布与契约错误率

- hit **53** / partial **7** / miss **88** / contract_error **6**（X+Y+Z+W=154）
- contract_error_rate = **0.0390**（6/154；契约错误行按 miss 计入，但未进三态分布与修正分子——如实披露 judge 自身可靠性）
- 平均尝试次数：1.16（min 1 / max 3）

## 2. 修正口径（两面并列，不作门禁/不作优劣结论）

- 机械下界（M2 containment）：**0.1149**（20/174）
- 修正命中率（partial 计 0.5）：**0.4397** = (20 + 53 + 0.5×7)/174
- 保守修正（partial 计 0）：**0.4195** = (20 + 53)/174
- 口径说明：containment 机械下界对同义改写/中英互译系统性漏判，judge 修正只覆盖机械未命中面；两条修正曲线是同一事实的上下界展示，本轮为诊断基线，无任何产品门禁判定。

## 3. 分歧率

- 分歧率 = (X+Y)/154 = **0.3896**（60/154）——机械下界低估量的直接度量：judge 把多少机械 miss 翻转为 hit/partial。

## 4. 跨类分布（query_type × judge verdict）

| query_type | hit | partial | miss | contract_error | 小计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cross_document` | 11 | 6 | 34 | 4 | 55 |
| `metadata` | 8 | 0 | 11 | 0 | 19 |
| `mixed_intent` | 5 | 0 | 8 | 1 | 14 |
| `multi_turn` | 10 | 1 | 16 | 0 | 27 |
| `no_answer` | 2 | 0 | 2 | 1 | 5 |
| `single_fact` | 17 | 0 | 17 | 0 | 34 |
- multi_turn 系（M2 近全 miss 重点群体）：共 27 条，hit 10 / partial 1 / miss 16 / contract_error 0

## 5. no_answer 型 3 例（M2 披露：语义正确但措辞不等价）

| case | 要点 | judge verdict | contract_error | evidence |
| --- | --- | --- | --- | --- |
| `noanswer-039` | Yes — the doc names the per-platform backing mecha | hit | False | 文档描述了在Linux系统上`fs.watch`使用`inotify(7)`作为底层机制来通知文 |
| `noanswer-039` | Other platforms likewise named: BSD kqueue(2), mac | miss | False | 是的，文档描述了在Linux系统上`fs.watch`使用`inotify(7)`作为底层机制来 |
| `noanswer-040` | Yes — the included chapters substantively cover th | miss | False | 无法确认Rust book（本语料库包含的章节）是否涵盖traits |
| `noanswer-040` | Honest scope note: the dedicated traits chapter (C | hit | False | 文档中仅在[S2]和[S7]中提及traits，但均未提供具体内容，仅说明将在第10章讨论 |
| `noanswer-050` | Yes — section 10.11 (Quality Control) introduces t | None | True |  |

## 6. judge token 实耗与预算对比

- judge 调用：**178 次**（call_type='judge' 网关记录过滤）
- prompt：**60,304**（预算 250,000–300,000，占中值 21.9%）；completion：**5,786**（预算 20,000）；合计 **66,090**
- 单次平均：prompt 339 / completion 33

## 7. 同模型自判偏置披露

- judge 与 M2 生成使用**同一模型**（`deepseek-chat`，llm_call 均缺省走 Settings），即「生成者的同门模型审自己的答案」——语义等价判断存在同构偏置可能，本报告不以此为结论，仅如实披露身份。

## 8. 逐要点清单（全量，无截断）

| case | query_type | 要点 | judge verdict | attempts | contract_error | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `multi-011` | multi_turn | 都支持索引和切片操作 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-011` | multi_turn | 两者都是序列类型 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-012` | multi_turn | 数量应相等 | miss | 1 | False | 没有找到关于“序列解包”时左边变量数量与右边元素数量条件的直接说明 |
| `multi-013` | multi_turn | 使用 import fibo as fib | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-013` | multi_turn | 用 as 后的名称绑定导入模块 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-014` | multi_turn | 尽量不要使用 from ... import * | hit | 1 | False | 教程建议避免使用 `from fibo import *` 这种导入方式 |
| `multi-014` | multi_turn | 建议使用 from package import specific_su | miss | 1 | False | 推荐使用更明确的导入方式，如 `from fibo import fib, fib2` 或 `i |
| `multi-015` | multi_turn | simple assignment never copies data | hit | 1 | False | 简单赋值在Python中从不复制数据 |
| `multi-015` | multi_turn | both names reference the same object | hit | 1 | False | 它们引用同一个对象 |
| `multi-016` | multi_turn | rgb also changes because it is the s | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-017` | multi_turn | freely available | hit | 1 | False | 免费获取 |
| `multi-017` | multi_turn | from the Python web site https://www | hit | 1 | False | 从Python官方网站 https://www.python.org/ 免费获取 |
| `multi-018` | multi_turn | 可附加到列定义或表约束 | miss | 1 | False | CHECK约束用于确保插入或更新行时满足特定条件 |
| `multi-018` | multi_turn | 用于约束列值（如 x>3） | hit | 1 | False | CHECK约束用于确保插入或更新行时满足特定条件 |
| `multi-019` | multi_turn | 可以（示例演示直接写数据库文件绕过约束） | hit | 1 | False | 文档展示了通过外部程序直接向数据库文件写入违反CHECK约束（x>3）的值2，随后执行`SELE |
| `multi-022` | multi_turn | 值被丢弃（drop） | hit | 1 | False | 当一个值的所有者（owner）超出作用域（goes out of scope）时，该值将被丢弃（ |
| `multi-023` | multi_turn | 请求（分配）它需要的内存 | hit | 1 | False | 其实现会请求它所需的内存（在堆上分配内存） |
| `multi-024` | multi_turn | 文本插值（text interpolation）{{ }} | miss | 1 | False | 没有找到关于Vue模板中双大括号语法的具体说明 |
| `multi-025` | multi_turn | 冒号简写 :id（即 : 前缀） | partial | 1 | False | 使用冒号 `:` 代替 `v-bind:` |
| `multi-026` | multi_turn | JavaScript Proxies（Proxy 代理） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-027` | multi_turn | BEGIN TRANSACTION（begin-stmt） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-028` | multi_turn | BEGIN / COMMIT（以及 ROLLBACK） | miss | 1 | False | 无法找到关于 PostgreSQL 教程中事务块控制命令的具体信息 |
| `multi-030` | multi_turn | 数字（把 Python 当作计算器） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-031` | multi_turn | Numbers | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-032` | multi_turn | 构建用户界面（UI） | hit | 1 | False | React 是一个用于构建**用户界面（UI）**的 JavaScript 库 |
| `multi-033` | multi_turn | key（通常用数据库 ID） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `multi-034` | multi_turn | 组件的记忆 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-021` | single_fact | 下划线 _ | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-022` | single_fact | j 或 J | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-024` | single_fact | 循环未执行 break 就结束时执行 | hit | 2 | False | 会在循环未执行 `break` 的情况下执行，即循环正常结束其所有迭代后执行 |
| `zh-025` | single_fact | set() 函数 | hit | 1 | False | 创建空集合应该使用 `set()` 函数 |
| `zh-026` | single_fact | del 语句 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-027` | single_fact | 海象运算符 := | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-029` | single_fact | json 模块 | hit | 1 | False | 可以使用标准库模块 `json` 来将结构化数据保存为 JSON 格式 |
| `zh-031` | single_fact | 匹配该类本身实例或其派生类实例 | hit | 1 | False | 一个 `except` 子句中的类匹配的异常将是该类本身的实例或其所派生的类的实例 |
| `zh-031` | single_fact | 反过来（列出派生类去匹配基类）不可以 | hit | 1 | False | 但反过来则不可以——列出派生类的 `except` 子句不会匹配其基类的实例 |
| `zh-032` | single_fact | 打包异常实例列表 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-032` | single_fact | 让多个异常一起被引发 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-033` | single_fact | 定义所有情况下都必须执行的清理操作 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-034` | single_fact | 新的命名空间 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-035` | single_fact | fibo.py | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-036` | single_fact | __pycache__ 目录 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `en-021` | single_fact | negative indices count from the righ | hit | 1 | False | 可以使用负索引来引用字符串 `word` 的最后一个字符，即 `word[-1]` |
| `en-022` | single_fact | match statement | hit | 2 | False | match`语句 |
| `en-023` | single_fact | 4 spaces | hit | 1 | False | 使用4个空格 |
| `en-023` | single_fact | no tabs | hit | 1 | False | 不使用制表符 |
| `en-024` | single_fact | SQLite 的标语/特点（Choose any three） | miss | 1 | False | 无法找到关于“Small. Fast. Reliable.”具体含义的说明 |
| `en-027` | single_fact | become the postgres OS user | hit | 1 | False | 以安装 PostgreSQL 的操作系统用户身份登录（通常是 `postgres`） |
| `en-027` | single_fact | create the first user account under  | hit | 1 | False | 以安装 PostgreSQL 的操作系统用户身份登录（通常是 `postgres`） |
| `en-028` | single_fact | updates are logged to permanent stor | hit | 1 | False | 事务的所有更新在事务被报告完成之前被记录到永久存储（即磁盘）上 |
| `en-029` | single_fact | 每条值有唯一所有者 | hit | 1 | False | 同一时间只能有一个所有者 |
| `en-029` | single_fact | 所有者离开作用域时值被丢弃 | hit | 1 | False | 当所有者超出作用域时，该值将被丢弃（dropped）。 |
| `en-030` | single_fact | String 类型 | hit | 1 | False | 首先引入来说明所有权的数据类型是 `String` 类型 |
| `en-031` | single_fact | RFC 3986 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-016` | single_fact | argument — 参数 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-016` | single_fact | parameter — 形参 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-017` | single_fact | 原子化操作 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-018` | single_fact | 创建新数组（或复制现有数组） | hit | 1 | False | 应该创建一个新的数组（或复制现有数组），然后用这个副本来更新状态 |
| `mixed-018` | single_fact | 用新数组更新状态 | hit | 1 | False | 应该创建一个新的数组（或复制现有数组），然后用这个副本来更新状态 |
| `mixed-019` | single_fact | ref 传入函数后仍保留最新值与响应性 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-020` | single_fact | 根据 SELECT 结果创建并填充表 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-038` | metadata | 不是新入门编程的初学者 | hit | 1 | False | 而不是面向新入门编程的初学者 |
| `zh-039` | metadata | Python 官网 https://www.python.org/ | hit | 1 | False | Python 网站 https://www.python.org/ |
| `zh-040` | metadata | 模块 | miss | 1 | False | 根据提供的文档内容，可以确认以下章节名称 |
| `zh-040` | metadata | 错误和异常 | miss | 1 | False | 根据提供的文档内容，可以确认以下章节名称 |
| `zh-041` | metadata | 带点号模块名（如 A.B） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-042` | metadata | word（示例为 'Python' 的切片） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-044` | metadata | 集合（set） | hit | 1 | False | 5.4 节讲的是“集合”（set）数据类型 |
| `en-033` | metadata | section 2.1 Percent-Encoding | hit | 2 | False | RFC 3986 中关于 percent-encoding 的章节是 **Section 2.1 |
| `en-034` | metadata | T. Berners-Lee | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `en-034` | metadata | R. Fielding | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `en-036` | metadata | 64 * 1024 (64 KiB) | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `en-037` | metadata | 3.1 Column Data Types | hit | 1 | False | Section: 3. Column Definitions > 3.1. Column Dat |
| `en-038` | metadata | Chapter 3 Advanced Features | hit | 1 | False | 第 3 章“高级特性”（Advanced Features） |
| `en-039` | metadata | 4.2 References and Borrowing | hit | 2 | False | 4.2 引用与借用 |
| `mixed-021` | metadata | read-eval-print loop（读取-求值-打印循环） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-022` | metadata | 英文定义（A function returning another fu | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-022` | metadata | 并有中文正文解释（装饰器语法只是一种语法糖…同样的概念也适用于类）——条 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-023` | metadata | TaskApp | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `mixed-025` | metadata | 文档开头（编者栏）列出：Adam Turner 和 Thomas Wou | hit | 1 | False | Python 3.13 新特性文档的编者是 Adam Turner 和 Thomas Woute |
| `zh-045` | cross_document | 3.13 新特性文档在自由线程模式语境下提到 GIL | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-045` | cross_document | 教程正文中未讨论 GIL（仅代码示例可能含英文术语） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-046` | cross_document | PG 用 createdb 且数据库名有限制（字母开头、63 字节） | miss | 1 | False | 我无法基于现有证据回答两者的区别 |
| `zh-046` | cross_document | SQLite 文档侧重表可建在 main/temp/attached 数 | miss | 1 | False | 我无法直接比较 SQLite 和 PostgreSQL 关于数据库创建的说明 |
| `zh-047` | cross_document | 一致：两版第 3 章标题不同但编号相同（中文为「Python 速览」，英 | miss | 1 | False | 无法确认英文教程的内容，因为所有引用均来自中文教程 |
| `zh-048` | cross_document | mutable 指运行期间允许修改状态的对象 | miss | 1 | False | 我无法回答关于“mutable”术语的定义，因为文档中没有包含术语表对“mutable”的解释。 |
| `zh-048` | cross_document | datetime 对象（date/datetime）不可变 | hit | 1 | False | `date`、`datetime`、`time` 和 `timezone` 类型的对象都是不可变 |
| `zh-049` | cross_document | Vue 文档称「组件」（Components Basics） | miss | 1 | False | 文档中没有提及 Vue 的相关内容，因此无法回答 Vue 如何称呼组件。 |
| `zh-049` | cross_document | React 文档称「组件」（可复用的小单元） | hit | 1 | False | React 文档将组件称为“组件”（component），并描述为“独立 UI 片段”或“可重用 |
| `zh-050` | cross_document | 3.13 新特性文档在弃用章节列出 datetime 变更：utcnow | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-050` | cross_document | copy.replace() 现在支持 datetime.datetim | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-051` | cross_document | read-eval-print loop（读取-求值-打印循环） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-052` | cross_document | SQLite 语法页仅以 begin-stmt 出现在语法清单 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-052` | cross_document | PG 教程第 3 章有专门 Transactions 小节 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-053` | cross_document | Python 教程用 open() 返回 file object | miss | 1 | False | 文档中仅提及Python的`open()`函数及其用法[S1]，未涉及Node.js的文件操作A |
| `zh-053` | cross_document | Node.js 文档用 fs/promises 的 open() 返回  | miss | 1 | False | 我无法回答关于Node.js文件操作函数的问题 |
| `zh-054` | cross_document | 一致：都以 --disable-gil/禁用 GIL 描述自由线程构建 | hit | 2 | False | 两者对 `--disable-gil` 的描述是一致的 |
| `en-040` | cross_document | SQLite 语法清单列出 begin-stmt / commit-st | None | 3 | True |  |
| `en-040` | cross_document | PostgreSQL 教程有专门的 Transactions 小节，事务 | hit | 2 | False | 它说明了在PostgreSQL中使用`BEGIN`和`COMMIT`命令来包围事务，使用`ROL |
| `en-041` | cross_document | Python: assignment references the sa | miss | 2 | False | 文档中关于Python的内容主要涉及类对象、JSON序列化以及dataclasses等主题[S4 |
| `en-041` | cross_document | Rust: ownership rules govern memory  | hit | 1 | False | 每个值在Rust中都有一个所有者[S1] |
| `en-042` | cross_document | RFC 3986 defines generic URI syntax | miss | 1 | False | 是的，Node.js fs 文档支持 file URL 路径。根据文档，大多数 `node:fs |
| `en-042` | cross_document | Node.js fs accepts file URL paths | hit | 1 | False | Node.js fs 文档支持 file URL 路径 |
| `en-043` | cross_document | SQLite 文档明确说明不限制列数据类型（Unlike most SQ | hit | 1 | False | SQLite 不限制列中可插入的数据类型 |
| `en-044` | cross_document | Rust: assigning or passing a heap va | partial | 1 | False | 将变量传递给函数会移动（move）或复制（copy）该值，类似于赋值操作 [S2]。返回值也可以 |
| `en-044` | cross_document | Node.js: buffers passed by reference | miss | 1 | False | Node.js fs 模块通过缓冲区（如 `ArrayBufferView`）和文件描述符来传递 |
| `en-045` | cross_document | Python tutorial: backslash escaping  | partial | 2 | False | 使用反斜杠 `\` 来转义特殊字符 |
| `en-045` | cross_document | RFC 3986: percent-encoding for data  | miss | 1 | False | 该文档没有直接讨论字符串的编码机制，而是定义了URI的语法和解析规则 |
| `en-046` | cross_document | Python 教程 7.2.1：f.write(string) 将字符串 | None | 3 | True |  |
| `en-046` | cross_document | Node.js fs：filehandle.write(buffer[, | None | 3 | True |  |
| `en-046` | cross_document | Node.js fs：fsPromises.writeFile(file | None | 3 | True |  |
| `en-047` | cross_document | SQLite SELECT 页有 JOIN 专门小节（LEFT/RIGH | miss | 1 | False | SQLite 的语法页面（sqlite-lang.md）详细讨论了 JOIN 操作，包括非标准的 |
| `en-047` | cross_document | PG 教程目录包含 2.6 Joins Between Tables 小 | miss | 1 | False | 而 PostgreSQL 教程（postgresql-tutorial.md）主要介绍 SQL  |
| `en-048` | cross_document | PG 教程：window functions 无需显式参数，行为完全由  | miss | 2 | False | 这些语法定义与 PostgreSQL 教程中描述的 OVER 子句（如 `PARTITION B |
| `en-048` | cross_document | SQLite 语言文档定义 over-clause 语法图：OVER w | partial | 2 | False | 在 [S3] 中，SQLite 的语法图展示了 `window-defn` 的结构，包括： -  |
| `en-049` | cross_document | Rust: String type owns heap memory | miss | 1 | False | 无法从文档中找到相关信息，不能编造答案 |
| `en-049` | cross_document | SQLite: TEXT affinity for string col | miss | 1 | False | 并未明确说明哪个 SQLite 类型名称映射到 Rust 的 `String` 类型 |
| `en-050` | cross_document | RFC 3986 defines URI generic syntax  | miss | 1 | False | 没有找到关于定义 `file:` URL 语法的 RFC 编号信息 |
| `en-051` | cross_document | Python: lists as mutable sequences | miss | 1 | False | 文档中没有直接说明SQLite如何将行建模为类似Python列表的序列数据 |
| `en-051` | cross_document | SQLite: SELECT returns rows with a f | miss | 1 | False | 文档中没有直接说明SQLite如何将行建模为类似Python列表的序列数据 |
| `en-052` | cross_document | PostgreSQL: transactional durability | partial | 1 | False | 事务完成后，所有更新必须永久记录在磁盘上，即使系统崩溃也不会丢失（持久性）[S1][S7] |
| `en-052` | cross_document | Rust: memory-safety guarantees — the | partial | 1 | False | 编译器保证引用永远不会是悬垂引用（dangling references）——如果存在对数据的引 |
| `en-053` | cross_document | Art of War: 兵形象水（tactics are like wa | miss | 1 | False | 我无法找到关于《孙子兵法》（Art of War）的任何引用或内容 |
| `en-053` | cross_document | SQLite: 不限制列数据类型 | miss | 1 | False | 文档仅涉及SQLite的SQL语言文档，没有提及《孙子兵法》或与其相关的灵活性论述 |
| `mixed-026` | cross_document | 对应：同一章，标题翻译不同 | hit | 1 | False | 中文教程第 3 章标题为“Python 速览”[S1]，英文教程第 3 章标题为“An Info |
| `mixed-027` | cross_document | 术语表：原子化操作不可再分 | miss | 1 | False | 文档中仅提到atomic operation（原子化操作）的定义，但没有涉及SQLite事务的具 |
| `mixed-027` | cross_document | SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明 | miss | 1 | False | 我无法回答关于SQLite文档中事务原子性的问题 |
| `mixed-028` | cross_document | 两者都让数据变化驱动界面更新 | hit | 1 | False | 两者都旨在让 UI 自动响应状态变化 |
| `mixed-028` | cross_document | Vue 用 Proxy 实现响应式，React 用 state 记忆组件 | partial | 1 | False | 两者在具体实现上有差异（如 React 使用不可变快照，Vue 使用可变代理） |
| `mixed-029` | cross_document | 一致：都指 --disable-gil/禁用 GIL 的自由线程构建 | hit | 1 | False | 两者都明确提到了使用 `--disable-gil` 选项进行构建，因此说法一致。 |
| `mixed-030` | cross_document | Python 教程 9. 类：类把数据和功能绑定在一起 | miss | 1 | False | 文档中未包含Python教程中关于“类”概念的介绍 |
| `mixed-030` | cross_document | React 文档：组件是可重用、可嵌套的 UI 单元 | miss | 1 | False | React文档仅描述了组件是构建用户界面的可重用、可嵌套单元[S1] |
| `mixed-031` | cross_document | 一致：datetime 对象是不可变的，不属于 mutable | miss | 1 | False | 我无法回答这个问题 |
| `mixed-032` | cross_document | SQLite SELECT 页有 JOIN 讲解（LEFT/RIGHT/ | miss | 1 | False | SQLite 语法页（sqlite-lang.md）中有专门的 JOIN 讲解 |
| `mixed-032` | cross_document | PG 教程目录列出 2.6 Joins Between Tables 小 | hit | 1 | False | PostgreSQL 教程（postgresql-tutorial.md）中虽然提到了“Join |
| `zh-055` | mixed_intent | 格式化字符串字面值（f-string） | hit | 1 | False | 这种写法叫做**格式化字符串字面值**，简称为 **f-字符串**（f-string） |
| `zh-056` | mixed_intent | str() 返回可读形式 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-056` | mixed_intent | repr() 返回带引号/反斜杠的表示形式 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-057` | mixed_intent | 先求值右边所有表达式 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-057` | mixed_intent | 赋值前完成求值，顺序从左到右 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-058` | mixed_intent | 列表内容可以改变（如 cubes[3] = 64） | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-058` | mixed_intent | 字符串内容不可变 | miss | 1 | False | 未找到足够可靠的文档依据，暂时无法回答该问题。 |
| `zh-059` | mixed_intent | 模块（第 6 章） | hit | 1 | False | 下一主题是“6. 模块” |
| `en-055` | mixed_intent | The `&` operator creates a reference | hit | 1 | False | 创建引用（而不是移动值）的操作符是 `&`（取引用操作符）。文档中提到：“The `&s1` s |
| `mixed-033` | mixed_intent | static type checker 是查找类型问题的外部工具 | hit | 2 | False | 指读取 Python 代码并进行分析，以查找问题（例如不正确的类型）的外部工具 |
| `mixed-033` | mixed_intent | stdlib 是标准库（standard library）的缩写 | None | 3 | True |  |
| `mixed-034` | mixed_intent | REPL：多行编辑、命令历史、help/exit/quit 直接支持 | hit | 2 | False | 支持多行编辑并保留历史记录。 - 对 REPL 专属命令如 `help`、`exit` 和 `q |
| `mixed-034` | mixed_intent | JIT：可用 PYTHON_JIT 环境变量控制 | miss | 1 | False | 关于 JIT 的改进，在提供的文档片段中未找到相关信息，因此无法回答这部分内容。 |
| `mixed-035` | mixed_intent | 字节码 | miss | 1 | False | bytecode 的中文名在文档中未提及，无法提供。 |
| `noanswer-039` | no_answer | Yes — the doc names the per-platform | hit | 1 | False | 文档描述了在Linux系统上`fs.watch`使用`inotify(7)`作为底层机制来通知文 |
| `noanswer-039` | no_answer | Other platforms likewise named: BSD  | miss | 1 | False | 是的，文档描述了在Linux系统上`fs.watch`使用`inotify(7)`作为底层机制来 |
| `noanswer-040` | no_answer | Yes — the included chapters substant | miss | 1 | False | 无法确认Rust book（本语料库包含的章节）是否涵盖traits |
| `noanswer-040` | no_answer | Honest scope note: the dedicated tra | hit | 1 | False | 文档中仅在[S2]和[S7]中提及traits，但均未提供具体内容，仅说明将在第10章讨论 |
| `noanswer-050` | no_answer | Yes — section 10.11 (Quality Control | None | 3 | True |  |

---
本报告为第二轮诊断基线（owner 批示：M3 无门禁判定；M4 预注册阈值门禁另行呈批）。所有数字为事实陈述。
