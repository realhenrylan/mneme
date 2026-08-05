# v2 拒答 case 质量报告（refusal quality）

> 拒答判定 = 语料（13 文档 / 1006 chunks）中无相关证据。

- 拒答用例总数：31（no_answer 30 + 链内拒答轮 1）
- 主题分布：语料相关主题 18 例（low_refuse 构造）、语料外主题 13 例

| case_id | 语言 | 难度 | band | 主题 | 构造理由 |
|---|---|---|---|---|---|
| multi-029 | mixed | medium | normal | 那这两篇文档对事务隔离级别的定义一样吗？ | LLM_ASSISTED；拒答轮：SQLite 语法页与 PG 教程均未定义隔离级别，两文档均无证据 |
| noanswer-026 | zh | hard | low_refuse | Python 教程中介绍了 pandas 库的 DataFrame 用法吗？ | LLM_ASSISTED；low_refuse：pandas 主题与教程相近但语料无任何 panda |
| noanswer-027 | zh | hard | low_refuse | 教程里讲没讲过 Django 框架的部署方式？ | LLM_ASSISTED；low_refuse：主题相近（Python 生态）但无证据 |
| noanswer-028 | zh | medium | low_refuse | Python 3.13 新特性文档中提到 Go 语言的相关内容了吗？ | LLM_ASSISTED；low_refuse：跨语言主题，语料无 Go 内容 |
| noanswer-029 | zh | medium | low_refuse | 术语表中有没有 Django 的条目？ | LLM_ASSISTED；low_refuse |
| noanswer-030 | zh | hard | normal | 教程中对比了 Python 与 C 语言的具体性能数据吗？ | LLM_ASSISTED；normal：教程提及 C 语言但无性能对比数据 |
| noanswer-031 | zh | hard | normal | 教程里说明了 CPython 解释器的 C 源码在哪个仓库路径吗？ | LLM_ASSISTED；normal：教程未给出源码路径 |
| noanswer-032 | zh | medium | low_refuse | SQLite 语法文档里 PRAGMA journal_mode 的用法说明在哪 | LLM_ASSISTED；low_refuse：SQLite 主题相近但收录的语法页无 PRAGMA |
| noanswer-033 | zh | medium | low_refuse | PostgreSQL 教程中讲流式复制（streaming replicatio | LLM_ASSISTED；low_refuse：PG 主题相近但教程（start/advanced） |
| noanswer-034 | zh | medium | low_refuse | Vue 指南文档里有专门的 TypeScript 章节吗？ | LLM_ASSISTED；low_refuse：收录的 essentials 章节无 TypeScr |
| noanswer-035 | zh | hard | low_refuse | React 文档中介绍了 Testing（测试）章节吗？ | LLM_ASSISTED；low_refuse：收录的 learn 章节无测试内容 |
| noanswer-036 | zh | hard | normal | Rust 书中第 7 章讲模块系统的内容是什么？ | LLM_ASSISTED；normal：语料仅收录第 3–6 章，无第 7 章 |
| noanswer-037 | en | medium | normal | Where does the PostgreSQL tutorial expla | LLM_ASSISTED；low_refuse：教程讲 createdb 用户但无 CREATE R |
| noanswer-038 | en | medium | low_refuse | Does RFC 3986 define the about: URI sche | LLM_ASSISTED；low_refuse：RFC 3986 不定义具体 scheme |
| noanswer-039 | en | hard | low_refuse | Does the Node.js fs doc describe inotify | LLM_ASSISTED；low_refuse：fs.watch 有 caveats 但无 inot |
| noanswer-040 | en | hard | low_refuse | Does the Rust book (chapters included in | LLM_ASSISTED；low_refuse：收录章节（3–6 章）无 trait |
| noanswer-041 | en | medium | low_refuse | Does the Python tutorial explain how to  | LLM_ASSISTED；low_refuse：主题相近（Python 生态）但无 matplotl |
| noanswer-042 | en | medium | normal | Does RFC 3986 cover internationalized UR | LLM_ASSISTED；normal：IRI 属 RFC 3987，3986 不覆盖 |
| noanswer-043 | en | hard | normal | What are the birth and death years of Su | LLM_ASSISTED；normal：文本无作者生卒信息 |
| noanswer-044 | en | hard | low_refuse | Where does the SQLite syntax doc explain | LLM_ASSISTED；low_refuse：收录页无 WAL/PRAGMA 内容 |
| noanswer-045 | en | medium | low_refuse | Does the PostgreSQL tutorial cover logic | LLM_ASSISTED；low_refuse：教程无逻辑复制内容 |
| noanswer-046 | en | medium | low_refuse | Does the included Rust book chapters exp | LLM_ASSISTED；low_refuse：Cargo 发布不在收录章节 |
| noanswer-047 | en | hard | low_refuse | Does the Node.js fs documentation cover  | LLM_ASSISTED；low_refuse |
| noanswer-048 | en | hard | normal | Where does RFC 3986 define the http sche | LLM_ASSISTED；normal：http scheme 由其他 RFC 定义 |
| noanswer-049 | en | hard | normal | Does the Art of War chapter on fire atta | LLM_ASSISTED；normal：火攻章讲策略，无配方 |
| noanswer-050 | en | medium | low_refuse | Does the Python tutorial introduce the u | LLM_ASSISTED；low_refuse：教程无 unittest 内容 |
| noanswer-051 | mixed | medium | low_refuse | 教程或术语表里提到机器学习框架（如 scikit-learn）的内容了吗？ | LLM_ASSISTED；low_refuse：主题相近但无证据 |
| noanswer-052 | mixed | hard | low_refuse | SQLite 和 PostgreSQL 文档里讲了 JSON 数据类型的功能吗？ | LLM_ASSISTED；low_refuse：两文档收录内容均无 JSON 数据类型 |
| noanswer-053 | mixed | hard | low_refuse | Vue 或 React 文档里有状态管理库（Pinia/Redux）的章节吗？ | LLM_ASSISTED；low_refuse：收录章节无状态管理库内容 |
| noanswer-054 | mixed | medium | normal | 语料中有关于 Git 版本控制的内容吗？ | LLM_ASSISTED；normal：语料无 Git 相关文档 |
| noanswer-055 | mixed | medium | normal | 语料中有关于云部署（cloud deployment）的内容吗？ | LLM_ASSISTED；normal：语料无云部署内容 |

## 旧 v1 no_answer 与新语料冲突检测

- 方法：25 例旧 no_answer 查询关键词（中文 2-gram + 英文词）对新语料全文本命中率 ≥50% 粗筛，命中项人工复核。
- 结论：全部 25 例无实质证据冲突（命中均为停用词/泛词，如 population、install、cook）；旧用例进入 dev 池安全性确认。
- 已知风险：语料扩充后旧 no_answer 的"无证据"性质依赖人工抽查结论，正式评测前应在 dev 检索中复核（计划 §5.4）。
