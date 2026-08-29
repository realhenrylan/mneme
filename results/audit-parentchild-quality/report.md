# B1 审计：parent 划分质量（只读）

- tiny child 阈值：< 30 字符
- v1: tiny child 共 **3** 块，按 source: {'DSpark_paper.pdf': 1, 'prevent-url-data-exfil.pdf': 2}；形态: {'body_fragment': 2, 'heading_fragment': 1}
- v1: parent 55 块，尺寸 min=412 median=1141 max=1982
- v1: child⊆parent 健全性：检查 201 个 child，违规 0（非子串或缺 parent）
- v1: tiny child 样例：

| source | chunk_id | len | shape | preview |
| --- | --- | --- | --- | --- |
| prevent-url-data-exfil.pdf | e4230571adaf0b872ac0b456f53a9095124f88c72e7949d0fb33c8ba0c13610f_chunk_24 | 1 | body_fragment | 4 |
| prevent-url-data-exfil.pdf | e4230571adaf0b872ac0b456f53a9095124f88c72e7949d0fb33c8ba0c13610f_chunk_12 | 4 | heading_fragment | 1.\n2 |
| DSpark_paper.pdf | 3be83454b2997f53c90577babbcb77dd5293a7d789b803c10bebfdd3ec5b3f06_chunk_360 | 25 | body_fragment | losslessness argument.\n33 |

- v2: tiny chunk（<30 字符）共 **1** 块；sealed 无关系字段，关系维度不适用
