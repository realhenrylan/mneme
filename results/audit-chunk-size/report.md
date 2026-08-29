# A1 审计：chunk 长度分布（阈值冻结依据）

- 方法：v1: src.loaders.LoaderRegistry -> chunk_document（与 prepare_index 同路径，内存重建零写入）；v2: 只读 data/v2-corpus/chunks/chunks.jsonl
- 候选阈值档：(10, 15, 20, 25, 30, 40, 50)

## v1（共 736 块）

- 长度（strip 后字符）：min=1 median=363.0 max=1982
- 百分位：{'p0': 1, 'p10': 178, 'p25': 323, 'p50': 363, 'p75': 388, 'p90': 668, 'p99': 1894}
- < 候选阈值数量：{'10': 5, '15': 10, '20': 12, '25': 14, '30': 16, '40': 17, '50': 21}
- 形态分布：{'body_fragment': 616, 'heading_fragment': 119, 'list_fragment': 1}

- 按 chunk_type：
  - ``: 68 块，<20 字符 10（含 <50 样例见下）
  - `anchor`: 4 块，<20 字符 0（含 <50 样例见下）
  - `child`: 609 块，<20 字符 2（含 <50 样例见下）
  - `parent`: 55 块，<20 字符 0（含 <50 样例见下）

### v1 短块样例（<50 字符，按长度升序，最多 60 条）

| source | chunk_id | type | len | shape | preview |
| --- | --- | --- | --- | --- | --- |
| prevent-url-data-exfil.pdf | e4230571adaf0b872ac0b456f53a9095124f88c72e7949d0fb33c8ba0c13610f_chunk_24 | child | 1 | body_fragment | 4 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_113 |  | 4 | body_fragment | (12) |
| prevent-url-data-exfil.pdf | e4230571adaf0b872ac0b456f53a9095124f88c72e7949d0fb33c8ba0c13610f_chunk_12 | child | 4 | heading_fragment | 1.\n2 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_111 |  | 6 | body_fragment | (11)\n9 |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_0 |  | 8 | body_fragment | 南京城市地理环境 |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_1 |  | 10 | heading_fragment | 1.1南京市地理概况 |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_4 |  | 12 | heading_fragment | 1.2南京市自然资源概况 |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_8 |  | 12 | heading_fragment | 1.3南京市人文资源概况 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_26 |  | 13 | heading_fragment | 2. Background |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_68 |  | 13 | heading_fragment | 2 tanh(𝑊𝑜𝑧𝑘), |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_82 |  | 15 | heading_fragment | 2 ∥𝑝𝑑\n𝑘−𝑝𝑡\n𝑘∥1. |
| LLMs_for_Mobility_Analysis_Survey.md | e9bb35155eb071a21fa61163eb98029349dfdc279d5e48de21a9e10a8faa1d39_chunk_6 |  | 16 | heading_fragment | ## 2. Background |
| LLMs_for_Mobility_Analysis_Survey.md | e9bb35155eb071a21fa61163eb98029349dfdc279d5e48de21a9e10a8faa1d39_chunk_16 |  | 23 | heading_fragment | ### 3.1 Data Processing |
| LLMs_for_Mobility_Analysis_Survey.md | e9bb35155eb071a21fa61163eb98029349dfdc279d5e48de21a9e10a8faa1d39_chunk_22 |  | 23 | heading_fragment | ### 3.2 Model Framework |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_360 | child | 25 | body_fragment | losslessness argument.\n33 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_136 |  | 26 | heading_fragment | 4.3. Experimental Analysis |
| OneDrive 入门.pdf | 092e01b197eea9690e1a6c34c48bbc01d58b4e65f9b39bdfdf77357746412b09_chunk_5 |  | 35 | body_fragment | 更具创造性、更井然有序且更安全，这都得益于\nMicrosoft 365 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_88 |  | 40 | heading_fragment | 3.2.2. Hardware-Aware Prefix Scheduler\n7 |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_6 |  | 40 | body_fragment | 南京市地下水资源同样丰富，且水质优良，拥有汤山温泉、珍珠泉等著名的温泉旅游资源。 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_135 | child | 41 | body_fragment | draft block based on expected acceptance. |
| 南京城市地理环境.docx | d8fa2a45c99677a0ed0440cc3bfed8eb270589e4b1c31821526505e0dcbe7e9b_chunk_5 |  | 47 | body_fragment | 南京市境内水网密布，河湖水系主要属于长江水系，长江、秦淮河、玄武湖与莫愁湖均是南京重要的河湖。 |

## v2（共 1006 块）

- 长度（strip 后字符）：min=22 median=1872.5 max=1998
- 百分位：{'p0': 22, 'p10': 1300, 'p25': 1658, 'p50': 1873, 'p75': 1951, 'p90': 1985, 'p99': 1998}
- < 候选阈值数量：{'10': 0, '15': 0, '20': 0, '25': 1, '30': 1, '40': 1, '50': 1}
- 形态分布：{'list_fragment': 132, 'body_fragment': 631, 'heading_fragment': 243}

### v2 短块样例（<50 字符，按长度升序，最多 60 条）

| source | chunk_id | type | len | shape | preview |
| --- | --- | --- | --- | --- | --- |
| postgresql-tutorial.md | 761b22915b5e_chunk_8 | pending | 22 | heading_fragment | # 3. Advanced Features |
