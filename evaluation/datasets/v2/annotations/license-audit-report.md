# v2 许可证证据审计报告（license evidence audit）

> fail-closed：attribution ↔ manifest ↔ 许可证文件三者一致；
> 任何不一致即整体不通过，且不得进入最终 corpus manifest。

- 文档数：13
- 同源共用组（同一来源的同一许可证）：docs.python.org 各页共用 PSF-2.0.txt；rust-lang/book 双许可证文件
- 跨来源复用：无（每个许可证文件仅服务其专属来源）

| 文档 | 许可证 | 许可证证据文件 | 状态 |
|---|---|---|---|
| art-of-war | Public-Domain | `gutenberg-ebook-132-license.txt` | ✅ 已确认 |
| nodejs-fs | MIT | `MIT-nodejs.txt` | ✅ 已确认 |
| postgresql-tutorial | PostgreSQL | `PostgreSQL-Copyright.txt` | ✅ 已确认 |
| python-datetime-zh | PSF-2.0 | `PSF-2.0.txt` | ✅ 已确认 |
| python-glossary-zh | PSF-2.0 | `PSF-2.0.txt` | ✅ 已确认 |
| python-tutorial-en | PSF-2.0 | `PSF-2.0.txt` | ✅ 已确认 |
| python-tutorial-zh | PSF-2.0 | `PSF-2.0.txt` | ✅ 已确认 |
| python-whatsnew313-zh | PSF-2.0 | `PSF-2.0.txt` | ✅ 已确认 |
| react-learn-zh | CC-BY-4.0 | `CC-BY-4.0-react.txt` | ✅ 已确认 |
| rfc3986 | IETF-Trust | `IETF-Trust-rfc5378.txt` | ✅ 已确认 |
| rust-book-core | MIT/Apache-2.0 | `rust-book-MIT.txt (+ rust-book-APACHE.txt)` | ✅ 已确认 |
| sqlite-lang | Public-Domain | `sqlite-public-domain.txt` | ✅ 已确认 |
| vue-guide-zh | CC-BY-4.0 | `CC-BY-4.0-vuejs.txt` | ✅ 已确认 |

## pending 声明

- 经逐文档核验，13 个来源的许可证证据均可独立确认，无 pending 来源。
- 特别记录：Node.js 文档的 CC-BY-4.0 声明仅见于网站历史页脚，当前无法独立确认；已改用 nodejs/node 仓库 LICENSE（MIT，明确涵盖 associated documentation files）作为再分发依据。
- art-of-war 采用 Project Gutenberg ebook 132 随附的完整Gutenberg License 条款（gutenberg-ebook-132-license.txt）作为再分发证据；该书在美国为公共领域（版权不受限）。
