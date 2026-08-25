# Overlap 人工审核待确认清单（25 条）

> 从 `~/.mneme/chroma_db/eval-autorun-lock`（736 chunks）本地只读提取候选 chunk 文本；
> bigram_overlap = |snippet 与 chunk 的字符 bigram 交集| / |snippet bigram|（review_pack 同口径）。
> 请在 `results/graph-gate/review-pack-chunk-annotated/review-overlap.jsonl` 中
> 为每条填写 `review_decision`（confirmed / reject）。

## 1. cross-002 / OneDrive 入门.pdf
- query: Compare the security features discussed in the URL exfiltration paper and OneDrive.
- snippet: `个人保管库、勒索软件检测和恢复以及文件加密`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9474, best-window=0.9474): cel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 2. cross-002 / prevent-url-data-exfil.pdf
- query: Compare the security features discussed in the URL exfiltration paper and OneDrive.
- snippet: `implement robust safeguards`
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=1.0000): Figure 1: Sample attack Given the simplicity and effectiveness of these techniques, it is critical to im- plement robust safeguards, especially as there have been multiple attacks docu- mented externally. • Covert Data Exfiltration via LLMs1: Demonstrated in January 2024, this attack showed that URLs queried by the model could leak conversation data directly
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=1.0000): Figure 1: Sample attack Given the simplicity and effectiveness of these techniques, it is critical to im- plement robust safeguards, especially as there have been multiple attacks docu- mented externally. • Covert Data Exfiltration via LLMs1: Demonstrated in January 2024, this attack showed that URLs queried by the model could leak conversation data directly
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.3333): ws any link to be redirected to after an initial pass to an original site. Often seen as a security problem, there are a number of sites that explicitly allow this type of redirection. An example of this is shown in Figure 3, where the use of open redirects on google.com allow the original link to be nominally to the google.com domain but to eventually end u

## 3. cross-004 / OneDrive 入门.pdf
- query: 南京的自然水系和OneDrive的文件同步有什么相似之处？
- snippet: `自动备份并同步到 onedrive`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=1.0000, best-window=1.0000):  OneDrive.com 和 OneDrive 移 动应用，几乎可以从你所在的任意位置 使用所有设备创建、访问和编辑文件。 电脑文件夹备份 打开电脑文件夹备份，将“桌面”、 “文档”和“图片”文件夹自动备份并 同步到 OneDrive。 如何设置电脑文件夹备份 云存储 OneDrive 提供了一个安全的位 置来存储文件和照片。最初提供 

## 4. cross-006 / OneDrive 入门.pdf
- query: URL数据泄露论文和OneDrive安全功能都关注安全问题，它们的安全策略有什么区别？
- snippet: `个人保管库、勒索软件检测和恢复以及文件加密`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9474, best-window=0.9474): cel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 5. cross-006 / prevent-url-data-exfil.pdf
- query: URL数据泄露论文和OneDrive安全功能都关注安全问题，它们的安全策略有什么区别？
- snippet: `implement robust safeguards`
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=1.0000): Figure 1: Sample attack Given the simplicity and effectiveness of these techniques, it is critical to im- plement robust safeguards, especially as there have been multiple attacks docu- mented externally. • Covert Data Exfiltration via LLMs1: Demonstrated in January 2024, this attack showed that URLs queried by the model could leak conversation data directly
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=1.0000): Figure 1: Sample attack Given the simplicity and effectiveness of these techniques, it is critical to im- plement robust safeguards, especially as there have been multiple attacks docu- mented externally. • Covert Data Exfiltration via LLMs1: Demonstrated in January 2024, this attack showed that URLs queried by the model could leak conversation data directly
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.3333): ws any link to be redirected to after an initial pass to an original site. Often seen as a security problem, there are a number of sites that explicitly allow this type of redirection. An example of this is shown in Figure 3, where the use of open redirects on google.com allow the original link to be nominally to the google.com domain but to eventually end u

## 6. en-004 / DSpark_paper.pdf
- query: What is speculative decoding?
- snippet: `a lightweight draft model proposes a block of candidate tokens, and the full-size target model verifies the entire block in a single forward pass via rejection sampling`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=0.9619, best-window=0.7143): e head is trained end-to-end alongside the draft model and subsequently calibrated via STS to provide reliable scheduling signals. Training the draft model requires the target model’s output distributions for supervision. Evaluating both models over the full document context incurs substantial memory footprints and inter-worker communication overhead. To add

## 7. en-005 / DSpark_paper.pdf
- query: How much does DSpark improve the macro-average accepted length over Eagle3?
- snippet: `it improves the macro-average accepted length over the autoregressive eagle3 by 30.9%, 26.7%, and 30.0%`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=1.0000, best-window=0.8906): ark domains. Specifically, across the Qwen3-4B, 8B, and 14B models, DSpark improves the macro-average accepted length over Eagle3 by 30.9%, 26.7%, and 30.0%, respectively. Similarly, compared to DFlash, DSpark yields relative improvements of 16.3%, 18.4%, and 18.3% across the three scales. Crucially, this advantage generalizes across model families, as demon

## 8. en-009 / LLMs_for_Mobility_Analysis_Survey.md
- query: What is the arXiv ID of the mobility analysis survey?
- snippet: `arxiv: 2405.02357v2`
- chunk `e9bb35155eb0…` (source=LLMs_for_Mobility_Analysis_Survey.md, bigram=1.0000, best-window=1.0000): y of South California, Duke Kunshan University **Submission Date:** February 24, 2025 **arXiv:** 2405.02357v2 [cs.LG] 21 Feb 2025 --- 

## 9. en-012 / OneDrive 入门.pdf
- query: What are the key features of OneDrive security?
- snippet: `个人保管库、勒索软件检测和恢复以及文件加密等安全功能`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9583, best-window=0.9583): cel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 10. en-017 / prevent-url-data-exfil.pdf
- query: What is the WebPilot Cross-Plugin Attack?
- snippet: `a benign-looking page accessed via the webpilot plugin could exfiltrate data`
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.9483): ation data directly in the query string. • WebPilot Cross-Plugin Attack2: Rehberger and collaborators demon- strated that a benign-looking page accessed via the WebPilot plugin could trigger another plugin, such as Zapier, to retrieve and exfiltrate user emails. • Writer.com Indirect Prompt Injection3: Adversaries caused the assistant to load hidden images, 
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.9655): • WebPilot Cross-Plugin Attack2: Rehberger and collaborators demon- strated that a benign-looking page accessed via the WebPilot plugin could trigger another plugin, such as Zapier, to retrieve and exfiltrate user emails. • Writer.com Indirect Prompt Injection3: Adversaries caused the assistant to load hidden images, with the source URL encoding private

## 11. en-019 / DSpark_paper.pdf
- query: How does DSpark improve over DFlash?
- snippet: `over the parallel dflash by 16.3%, 18.4%, and 18.3%`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=0.9706, best-window=0.9706): he macro-average accepted length over the autoregressive Eagle3 (Li et al., 2026b) by 30.9%, 26.7%, and 30.0%, and over the parallel DFlash (Chen et al., 2026) by 16.3%, 18.4%, and 18.3%, respectively. Beyond top- line metrics, our fine-grained position-wise analysis reveals the distinct generation characteristics of different drafters, empirically demonstra
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=0.9706, best-window=0.9706): verage accepted length over the autoregressive Eagle3 (Li et al., 2026b) by 30.9%, 26.7%, and 30.0%, and over the parallel DFlash (Chen et al., 2026) by 16.3%, 18.4%, and 18.3%, respectively. Beyond top- line metrics, our fine-grained position-wise analysis reveals the distinct generation characteristics

## 12. mixed-001 / DSpark_paper.pdf
- query: DSpark论文中Qwen3-4B模型的macro-average accepted length提升了多少？
- snippet: `it improves the macro-average accepted length over the autoregressive eagle3 by 30.9%, 26.7%, and 30.0%`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=1.0000, best-window=0.8906): ark domains. Specifically, across the Qwen3-4B, 8B, and 14B models, DSpark improves the macro-average accepted length over Eagle3 by 30.9%, 26.7%, and 30.0%, respectively. Similarly, compared to DFlash, DSpark yields relative improvements of 16.3%, 18.4%, and 18.3% across the three scales. Crucially, this advantage generalizes across model families, as demon

## 13. mixed-002 / OneDrive 入门.pdf
- query: 南京的OneDrive免费存储空间和Microsoft 365存储空间分别是多少？
- snippet: `最初提供 5 gb 的免费存储空间,也可升级到 microsoft 365,获取 1 tb 的空间`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.8889, best-window=0.8889): 5 GB 的免费存储空间，也可升级到 Microsoft 365，获取 1 TB 的空间。 了解如何上传文件

## 14. mixed-003 / OneDrive 入门.pdf
- query: What are the key security features of OneDrive个人保管库？
- snippet: `借助个人保管库、勒索软件检测和恢复以及文件加密等安全功能`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9615, best-window=0.9615): 和 Excel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 15. mixed-005 / DSpark_paper.pdf
- query: DSpark的speculative decoding如何工作？
- snippet: `a lightweight draft model proposes a block of candidate tokens, and the full-size target model verifies the entire block in a single forward pass via rejection sampling`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=0.9619, best-window=0.7143): e head is trained end-to-end alongside the draft model and subsequently calibrated via STS to provide reliable scheduling signals. Training the draft model requires the target model’s output distributions for supervision. Evaluating both models over the full document context incurs substantial memory footprints and inter-worker communication overhead. To add

## 16. mixed-008 / DSpark_paper.pdf
- query: 南京的城镇化率87.2%和DSpark对Eagle3的提升30.9%分别来自哪些文档？
- snippet: `improves the macro-average accepted length over the autoregressive eagle3 by 30.9%`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=1.0000, best-window=0.8491): all evaluated target models and benchmark domains. Specifically, across the Qwen3-4B, 8B, and 14B models, DSpark improves the macro-average accepted length over Eagle3 by 30.9%, 26.7%, and 30.0%, respectively. Similarly, compared to DFlash, DSpark yields relative improvements of 16.3%, 18.4%, and 18.3% across the three scales. Crucially, this advantage gener

## 17. mixed-012 / OneDrive 入门.pdf
- query: 南京的长江水系和OneDrive的云存储有什么共同点？
- snippet: `onedrive 提供了一个安全的位置来存储文件和照片`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=1.0000, best-window=1.0000): e 移 动应用，几乎可以从你所在的任意位置 使用所有设备创建、访问和编辑文件。 电脑文件夹备份 打开电脑文件夹备份，将“桌面”、 “文档”和“图片”文件夹自动备份并 同步到 OneDrive。 如何设置电脑文件夹备份 云存储 OneDrive 提供了一个安全的位 置来存储文件和照片。最初提供 

## 18. mixed-013 / prevent-url-data-exfil.pdf
- query: WebPilot攻击和prompt injection有什么关系？
- snippet: `a benign-looking page accessed via the webpilot plugin could exfiltrate data`
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.9483): ation data directly in the query string. • WebPilot Cross-Plugin Attack2: Rehberger and collaborators demon- strated that a benign-looking page accessed via the WebPilot plugin could trigger another plugin, such as Zapier, to retrieve and exfiltrate user emails. • Writer.com Indirect Prompt Injection3: Adversaries caused the assistant to load hidden images, 
- chunk `e4230571adaf…` (source=prevent-url-data-exfil.pdf, bigram=1.0000, best-window=0.9655): • WebPilot Cross-Plugin Attack2: Rehberger and collaborators demon- strated that a benign-looking page accessed via the WebPilot plugin could trigger another plugin, such as Zapier, to retrieve and exfiltrate user emails. • Writer.com Indirect Prompt Injection3: Adversaries caused the assistant to load hidden images, with the source URL encoding private

## 19. multi-006 / DSpark_paper.pdf
- query: What were the results on Qwen3 models?
- snippet: `improves the macro-average accepted length over the autoregressive eagle3 by 30.9%, 26.7%, and 30.0%`
- chunk `3be83454b299…` (source=DSpark_paper.pdf, bigram=1.0000, best-window=0.8871): aseline (DFlash) across all evaluated target models and benchmark domains. Specifically, across the Qwen3-4B, 8B, and 14B models, DSpark improves the macro-average accepted length over Eagle3 by 30.9%, 26.7%, and 30.0%, respectively. Similarly, compared to DFlash, DSpark yields relative improvements of 16.3%, 18.4%, and 18.3% across the three scales. Crucial

## 20. multi-007 / OneDrive 入门.pdf
- query: OneDrive是什么？
- snippet: `将文件保存到 onedrive,以便从任意位置使用所有设备对其进行保护、备份和访问`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=1.0000, best-window=1.0000): Microsoft OneDrive 入门 将文件保存到 OneDrive，以便从任意位置使用所有设备对其进 行保护、备份和访问。
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=1.0000, best-window=1.0000): Microsoft OneDrive 入门 将文件保存到 OneDrive，以便从任意位置使用所有设备对其进 行保护、备份和访问。

## 21. multi-008 / OneDrive 入门.pdf
- query: 它提供多少免费空间？
- snippet: `最初提供 5 gb 的免费存储空间`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.6923, best-window=0.6923): 5 GB 的免费存储空间，也可升级到 Microsoft 365，获取 1 TB 的空间。 了解如何上传文件

## 22. multi-010 / OneDrive 入门.pdf
- query: What security features does it have?
- snippet: `个人保管库、勒索软件检测和恢复以及文件加密`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9474, best-window=0.9474): cel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 23. zh-014 / OneDrive 入门.pdf
- query: OneDrive的免费存储空间有多大？
- snippet: `最初提供 5 gb 的免费存储空间`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.6923, best-window=0.6923): 5 GB 的免费存储空间，也可升级到 Microsoft 365，获取 1 TB 的空间。 了解如何上传文件

## 24. zh-015 / OneDrive 入门.pdf
- query: OneDrive如何保护文件安全？
- snippet: `借助个人保管库、勒索软件检测和恢复以及文件加密等安全功能`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=0.9615, best-window=0.9615): 和 Excel 轻 松创建、编辑和共享文件。 了解如何使用 Office 网页版 共享和协作 与任何人共享文档、文件夹和照片。他 们不需要帐户即可查看、编辑或实时协 作处理文件。 了解如何共享文件 安全性 借助个人保管库、勒索软件检测和恢复1 以及文件加密等安全功能，始终保障工作 和个人文件的安全。 1需要 Microsoft 365 个人版或家庭版订阅。

## 25. zh-017 / OneDrive 入门.pdf
- query: OneDrive的电脑文件夹备份功能可以备份哪些文件夹？
- snippet: `将"桌面"、"文档"和"图片"文件夹自动备份并同步到 onedrive`
- chunk `092e01b197ee…` (source=OneDrive 入门.pdf, bigram=1.0000, best-window=1.0000): 随处访问 借助 OneDrive.com 和 OneDrive 移 动应用，几乎可以从你所在的任意位置 使用所有设备创建、访问和编辑文件。 电脑文件夹备份 打开电脑文件夹备份，将“桌面”、 “文档”和“图片”文件夹自动备份并 同步到 OneDrive。 如何设置电脑文件夹备份 云存储 OneDrive 提供了一个安全的位 置来存储文件和照片。最初提供 
