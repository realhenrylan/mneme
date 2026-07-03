#!/usr/bin/env python3
"""
Temperature Test Runner for RAG / Graph RAG
Model: deepseek-chat (via API)
Temperatures: [0.0, 0.1, 0.3, 0.5, 0.7, 1.0]
"""

import json, os, sys, time, hashlib
import numpy as np
import argparse

sys.path.insert(0, "/Users/deepprinciple/Desktop/henry/0")

from src.rag import prepare_index, answer_query_stream
from graph_rag import prepare_graph_index, graph_query_stream

WORKDIR = "/Users/deepprinciple/Desktop/henry/0"
FILE_PATHS = [
    "test_texts/2405.02357v2.pdf",
    "test_texts/DSpark_paper.pdf",
    "test_texts/LLMs_for_Mobility_Analysis_Survey.md",
    "test_texts/OneDrive \u5165\u95e8.pdf",
    "test_texts/prevent-url-data-exfil.pdf",
    "test_texts/\u5357\u4eac\u57ce\u5e02\u5730\u7406\u73af\u5883.docx",
]
TEMPERATURES = [0.0, 0.1, 0.3, 0.5, 0.7, 1.0]

# question bank
RAG_QIDS  = [f"RAG-{i:02d}"  for i in range(1, 13)]
GRAG_QIDS = [f"GRAG-{i:02d}" for i in range(1, 15)]
COM_QIDS  = [f"COM-{i:02d}"  for i in range(1, 7)]
NEG_QIDS  = ["NEG-01", "NEG-02"]
RAG_QUESTIONS  = RAG_QIDS  + COM_QIDS + NEG_QIDS
GRAG_QUESTIONS = GRAG_QIDS + COM_QIDS + NEG_QIDS


def _q(text):
    return text


QUESTIONS = {
    # RAG
    "RAG-01": {"q": _q("南京市的最高点是什么？海拔多少米？"), "facts": ["\u7d2b\u91d1\u5c71", "448.9"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-02": {"q": _q("OneDrive \u7684\u514d\u8d39\u5b58\u50a8\u7a7a\u95f4\u6700\u521d\u63d0\u4f9b\u591a\u5c11 GB\uff1f\u5347\u7ea7\u5230 Microsoft 365 \u53ef\u4ee5\u83b7\u5f97\u591a\u5c11\u5b58\u50a8\uff1f"), "facts": ["5 GB", "1 TB"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-03": {"q": _q("\u5728 LLMs for Mobility Analysis \u8fd9\u7bc7\u7efc\u8ff0\u4e2d\uff0c\u4f5c\u8005\u5c06\u6570\u636e\u5904\u7406\u6280\u672f\u5206\u4e3a\u54ea\u4e09\u7c7b\uff1f"), "facts": ["Tokenization", "Prompt", "Embedding"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-04": {"q": _q("DSpark \u8bba\u6587\u4e2d\u63d0\u51fa\u7684 confidence-scheduled verification \u4e3b\u8981\u89e3\u51b3\u4ec0\u4e48\u95ee\u9898\uff1f"), "facts": ["rejection", "throughput", "\u6d6a\u8d39", "verification waste"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-05": {"q": _q("\u7efc\u8ff0\u8bba\u6587\u4e2d\u63d0\u5230\u7684\u56db\u79cd\u4ea4\u901a\u9884\u6d4b\u4efb\u52a1\u7c7b\u578b\u5206\u522b\u662f\u4ec0\u4e48\uff1f\u8bf7\u7b80\u8981\u8bf4\u660e\u6bcf\u4e00\u79cd\u3002"), "facts": ["Traffic Forecasting", "Human Mobility Forecasting", "Demand Forecasting", "Missing Data Imputation"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-06": {"q": _q("\u5357\u4eac\u5e02\u7684\u6cb3\u6e56\u6c34\u7cfb\u4e3b\u8981\u5c5e\u4e8e\u4ec0\u4e48\u6c34\u7cfb\uff1f\u8bf7\u5217\u4e3e\u81f3\u5c11\u56db\u4e2a\u5357\u4eac\u91cd\u8981\u7684\u6cb3\u6e56\u540d\u79f0\u3002"), "facts": ["\u957f\u6c5f\u6c34\u7cfb", "\u957f\u6c5f", "\u79e6\u6dee\u6cb3"], "wrong": [], "fabricated": [], "optional": ["\u7384\u6b66\u6e56", "\u83ab\u6101\u6e56", "\u6c64\u5c71\u6e29\u6cc9", "\u73cd\u73e0\u6cc9"], "neg": False},
    "RAG-07": {"q": _q("\u5728 LLM agent \u7684\u6570\u636e\u6cc4\u9732\u5a01\u80c1\u6a21\u578b\u4e2d\uff0c\u653b\u51fb\u8005\u901a\u8fc7\u4ec0\u4e48\u65b9\u5f0f\u6784\u9020\u6076\u610f URL\uff1f\u8bba\u6587\u63d0\u51fa\u4e86\u4ec0\u4e48\u9632\u62a4\u65b9\u6848\uff1f"), "facts": ["prompt injection", "allow-list", "\u52a8\u6001", "search index"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-08": {"q": _q("OneDrive \u63d0\u4f9b\u4e86\u54ea\u4e9b\u5b89\u5168\u529f\u80fd\u6765\u4fdd\u62a4\u7528\u6237\u6587\u4ef6\uff1f"), "facts": ["Personal Vault", "\u4e2a\u4eba\u4fdd\u7ba1\u5e93", "ransomware", "\u52a0\u5bc6", "encryption"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-09": {"q": _q("\u5357\u4eac\u5e02\u7684\u5efa\u6210\u533a\u9762\u79ef\u3001\u5e38\u4f4f\u4eba\u53e3\u3001\u57ce\u9547\u5e38\u4f4f\u4eba\u53e3\u548c\u57ce\u9547\u5316\u7387\u5206\u522b\u662f\u591a\u5c11\uff1f"), "facts": ["868.28", "954.70", "832.49", "87.2"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-10": {"q": _q("DSpark \u76f8\u6bd4 MTP-1 \u751f\u4ea7\u57fa\u7ebf\uff0c\u5728\u751f\u6210\u901f\u5ea6\u4e0a\u63d0\u5347\u7684\u767e\u5206\u6bd4\u8303\u56f4\u662f\u591a\u5c11\uff1f"), "facts": ["60", "85"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-11": {"q": _q("\u5728\u667a\u80fd\u4ea4\u901a\u7cfb\u7edf\u4e2d\u5e94\u7528 LLM \u9762\u4e34\u54ea\u4e9b\u9690\u79c1\u65b9\u9762\u7684\u6311\u6218\uff1f\u7efc\u8ff0\u4e2d\u7ed9\u51fa\u4e86\u54ea\u4e9b\u5e94\u5bf9\u65b9\u6848\uff1f"), "facts": ["\u5dee\u5206\u9690\u79c1", "Differential Privacy", "homomorphic"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "RAG-12": {"q": _q("\u5357\u4eac\u5165\u9009\u300a\u4eba\u7c7b\u975e\u7269\u8d28\u6587\u5316\u9057\u4ea7\u4f5c\u54c1\u540d\u5f55\u300b\u7684\u662f\u4ec0\u4e48\uff1f\u5357\u4eac\u6709\u54ea\u4e9b\u8457\u540d\u7684\u6e29\u6cc9\u65c5\u6e38\u8d44\u6e90\uff1f"), "facts": ["\u4e91\u9526", "\u6c64\u5c71\u6e29\u6cc9", "\u73cd\u73e0\u6cc9"], "wrong": [], "fabricated": [], "optional": [], "neg": False},

    # Graph RAG
    "GRAG-01": {"q": _q('TrafficBERT \u548c TrafficGPT \u8fd9\u4e24\u4e2a\u6a21\u578b\u5206\u522b\u91c7\u7528\u4e86\u4ec0\u4e48 LLM \u57fa\u5ea7\uff1f\u5b83\u4eec\u5728\u4ea4\u901a\u9884\u6d4b\u4e2d\u7684\u4f5c\u7528\u6709\u4f55\u4e0d\u540c\uff1f'), "facts": ["BERT", "GPT-3.5", "ChatGLM"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-02": {"q": _q("\u7efc\u8ff0\u4e2d\u63d0\u5230\u4e86\u54ea\u4e9b\u57fa\u4e8e GPT-2 \u7684\u4ea4\u901a\u9884\u6d4b\u6a21\u578b\uff1f\u5b83\u4eec\u5404\u81ea\u7684\u7279\u70b9\u662f\u4ec0\u4e48\uff1f"), "facts": ["LLM4TS", "STG-LLM", "TPLLM"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-03": {"q": _q("DSpark \u7684\u534a\u81ea\u56de\u5f52\u67b6\u6784\u7531\u54ea\u4e24\u4e2a\u6a21\u5757\u7ec4\u6210\uff1f\u5404\u81ea\u7684\u4f5c\u7528\u662f\u4ec0\u4e48\uff1f"), "facts": ["Parallel backbone", "semi-autoregressive", "sequential module"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-04": {"q": _q('\u5728\u7efc\u8ff0\u8bba\u6587\u4e2d\uff0c"Tokenization"、"Prompt" \u548c "Embedding" \u8fd9\u4e09\u79cd\u6570\u636e\u9884\u5904\u7406\u6280\u672f\u5728\u4ea4\u901a\u9884\u6d4b\u4e2d\u5206\u522b\u6709\u54ea\u4e9b\u5177\u4f53\u5e94\u7528\u6848\u4f8b\uff1f'), "facts": ["AuxMobLCast", "LLMLight", "GT-TDI"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-05": {"q": _q('\u7efc\u8ff0\u4e2d\u63d0\u5230\u7684 UniST \u6a21\u578b\u548c ST-LLM \u6a21\u578b\u90fd\u7528\u4e8e\u57ce\u5e02\u65f6\u7a7a\u9884\u6d4b\uff0c\u5b83\u4eec\u5728\u6280\u672f\u8def\u7ebf\u4e0a\u6709\u4ec0\u4e48\u5f02\u540c\uff1f'), "facts": ["UniST", "ST-LLM"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-06": {"q": _q("DSpark \u7684 confidence-scheduled verification \u4e0e\u4f20\u7edf\u7684 speculative decoding \u5728\u9a8c\u8bc1\u7b56\u7565\u4e0a\u6709\u54ea\u4e9b\u6838\u5fc3\u533a\u522b\uff1f"), "facts": ["speculative", "dynamic", "throughput profile"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-07": {"q": _q("\u4ece Human Mobility Forecasting \u5230 Demand Forecasting\uff0cLLM \u7684\u5e94\u7528\u7b56\u7565\u6709\u54ea\u4e9b\u53d8\u5316\uff1f\u8bf7\u4ece\u6a21\u578b\u6846\u67b6\u89d2\u5ea6\u5206\u6790\u3002"), "facts": ["MobilityGPT", "UniST", "ST-LLM", "fine-tune"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-08": {"q": _q("\u5728 all-MiniLM-L6-v2 \u751f\u6210\u5d4c\u5165\u7684\u573a\u666f\u4e0b\uff0cDSpark \u7684\u5e76\u884c draft \u751f\u6210\u673a\u5236\u9762\u4e34\u7684\u4e3b\u8981\u6311\u6218\u662f\u4ec0\u4e48\uff1f\u534a\u81ea\u56de\u5f52\u67b6\u6784\u5982\u4f55\u7f13\u89e3\u8fd9\u4e2a\u95ee\u9898\uff1f"), "facts": ["acceptance decay", "semi-autoregressive", "intra-block"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-09": {"q": _q("\u7efc\u8ff0\u8bba\u6587\u4e2d\u7684 Fine-tune \u7b56\u7565\u4e0e DSpark \u8bba\u6587\u4e2d\u63d0\u5230\u7684\u5173\u8054\u6709\u4ec0\u4e48\u4e0d\u540c\uff1f\u4e24\u8005\u5728 LLM \u5e94\u7528\u573a\u666f\u4e2d\u6709\u4f55\u4e0d\u540c\uff1f"), "facts": ["fine-tune", "traffic"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-10": {"q": _q("URL \u6570\u636e\u6cc4\u9732\u9632\u62a4\u8bba\u6587\u4e2d\u63cf\u8ff0\u7684 LLM agent \u5a01\u80c1\u6a21\u578b\uff0c\u4e0e\u4ea4\u901a\u7efc\u8ff0\u4e2d\u63d0\u5230\u7684 LLM \u9690\u79c1\u95ee\u9898\u6709\u4f55\u5f02\u540c\uff1f\u4e24\u8005\u63d0\u51fa\u7684\u9632\u62a4\u673a\u5236\u6709\u65e0\u91cd\u53e0\u4e4b\u5904\uff1f"), "facts": ["prompt injection", "differential privacy", "allow-list"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-11": {"q": _q("\u5357\u4eac\u5e02\u7684\u81ea\u7136\u8d44\u6e90\u4e0e\u4eba\u6587\u8d44\u6e90\u4e4b\u95f4\u5b58\u5728\u54ea\u4e9b\u5730\u7406\u548c\u5386\u53f2\u4e0a\u7684\u5173\u8054\uff1f"), "facts": ["\u79e6\u6dee\u6cb3", "\u7d2b\u91d1\u5c71", "\u516d\u671d\u53e4\u90fd"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-12": {"q": _q("OneDrive \u7684\u5b89\u5168\u673a\u5236\u4e0e\u9632\u6b62 URL \u6570\u636e\u6cc4\u9732\u8bba\u6587\u4e2d\u7684\u9632\u62a4\u7b56\u7565\uff0c\u5728\u6280\u672f\u601d\u8def\u4e0a\u6709\u4ec0\u4e48\u76f8\u4f3c\u4e4b\u5904\u548c\u672c\u8d28\u533a\u522b\uff1f"), "facts": ["Personal Vault", "allow-list", "\u52a0\u5bc6"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-13": {"q": _q("OneDrive \u7684\u4e2a\u4eba\u4fdd\u7ba1\u5e93\uff08Personal Vault\uff09\u548c\u6587\u4ef6\u52a0\u5bc6\u5728\u4fdd\u62a4\u673a\u5236\u4e0a\u6709\u4ec0\u4e48\u4e0d\u540c\uff1f\u5b83\u4eec\u5206\u522b\u5e94\u5bf9\u54ea\u79cd\u5b89\u5168\u5a01\u868a\uff1f"), "facts": ["Personal Vault", "\u4e2a\u4eba\u4fdd\u7ba1\u5e93", "\u8eab\u4efd\u9a8c\u8bc1"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "GRAG-14": {"q": _q('URL \u6cc4\u9732\u8bba\u6587\u4e2d\u63d0\u5230 open redirects \u4e3a\u4ec0\u4e48\u80fd\u7ed5\u8fc7 naive domain-based allow-listing\uff1f\u8bba\u6587\u7684 dynamic policy \u5982\u4f55\u514b\u670d\u8fd9\u4e2a\u6f0f\u6d1e\uff1f'), "facts": ["open redirect", "\u91cd\u5b9a\u5411", "domain", "search index"], "wrong": [], "fabricated": [], "optional": [], "neg": False},

    # COM
    "COM-01": {"q": _q("\u5728 LLMs for Mobility Analysis \u7efc\u8ff0\u4e2d\uff0cLLM \u5728\u4ea4\u901a\u9884\u6d4b\u9886\u57df\u6709\u54ea\u4e9b\u4f20\u7edf\u65b9\u6cd5\u4e0d\u5177\u5907\u7684\u4f18\u52bf\uff1f\u8bf7\u5217\u4e3e\u5e76\u7b80\u8981\u8bf4\u660e\u3002"), "facts": ["\u63a8\u7406", "\u4e0a\u4e0b\u6587\u7406\u89e3", "\u8fc1\u79fb", "\u591a\u6a21\u6001"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "COM-02": {"q": _q("DSpark \u8bba\u6587\u7684\u6838\u5fc3\u521b\u65b0\u70b9\u662f\u4ec0\u4e48\uff1f\u8fd9\u9879\u6280\u672f\u5bf9 LLM serving \u7cfb\u7edf\u5e26\u6765\u4e86\u4ec0\u4e48\u5177\u4f53\u6539\u8fdb\uff1f"), "facts": ["semi-autoregressive", "60", "85"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "COM-03": {"q": _q("\u5357\u4eac\u5e02\u6709\u54ea\u4e9b\u81ea\u7136\u8d44\u6e90\uff1f\u8bf7\u6309\u6c34\u8d44\u6e90\u3001\u6797\u6728\u8d44\u6e90\u3001\u751f\u7269\u8d44\u6e90\u5206\u7c7b\u5217\u51fa\u3002"), "facts": ["\u6c34\u8d44\u6e90", "\u6797\u6728\u8d44\u6e90", "\u751f\u7269\u8d44\u6e90", "\u957f\u6c5f", "\u7384\u6b66\u6e56"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "COM-04": {"q": _q("\u7efc\u8ff0\u8bba\u6587\u4e2d Fine-tune \u548c Zero-Shot/Few-Shot \u4e24\u79cd\u7b56\u7565\u5404\u81ea\u9002\u7528\u4e8e\u4ec0\u4e48\u573a\u666f\uff1f\u5b83\u4eec\u7684\u4f18\u7f3a\u70b9\u5206\u522b\u662f\u4ec0\u4e48\uff1f"), "facts": ["Fine-tune", "Zero-Shot", "Few-Shot", "\u5fae\u8c03"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "COM-05": {"q": _q("\u4ea4\u901a\u7efc\u8ff0\u548c URL \u6570\u636e\u6cc4\u9732\u8bba\u6587\u90fd\u63d0\u5230\u4e86 LLM \u7684\u9690\u79c1\u98ce\u9669\uff0c\u8bf7\u5206\u522b\u603b\u7ed3\u4e24\u7bc7\u8bba\u6587\u5bf9\u8be5\u95ee\u9898\u7684\u89c2\u70b9\u548c\u63d0\u51fa\u7684\u5e94\u5bf9\u65b9\u6848\u3002"), "facts": ["\u5dee\u5206\u9690\u79c1", "differential privacy", "prompt injection", "allow-list"], "wrong": [], "fabricated": [], "optional": [], "neg": False},
    "COM-06": {"q": _q("OneDrive \u5165\u95e8\u6307\u5357\u4e2d\uff0c\u7528\u6237\u5982\u4f55\u5728\u4e0d\u540c\u8bbe\u5907\u95f4\u8bbf\u95ee\u548c\u7ba1\u7406\u6587\u4ef6\uff1f\u8bf7\u6982\u62ec\u5176\u4e3b\u8981\u529f\u80fd\u8def\u5f84\u3002"), "facts": ["OneDrive.com", "\u8de8\u8bbe\u5907", "\u81ea\u52a8\u5907\u4efd", "\u5171\u4eab"], "wrong": [], "fabricated": [], "optional": [], "neg": False},

    # NEG
    "NEG-01": {"q": _q("DSpark \u8bba\u6587\u4e2d\u4f7f\u7528\u7684\u8bad\u7ec3\u6570\u636e\u96c6\u540d\u79f0\u662f\u4ec0\u4e48\uff1f\u6570\u636e\u96c6\u89c4\u6a21\u6709\u591a\u5927\uff1f"), "facts": [], "wrong": [], "fabricated": [], "optional": [], "neg": True, "expect_ignore": True, "expected_response": "\u672a\u63d0\u53ca|\u4e0d\u77e5\u9053|\u6587\u6863\u4e2d|not mentioned"},
    "NEG-02": {"q": _q("\u6839\u636e\u6587\u6863\u4e2d\u7684\u4fe1\u606f\uff0c\u5357\u4eac\u5e02\u76ee\u524d\u7684 GDP \u603b\u91cf\u548c\u4eba\u5747 GDP \u5206\u522b\u662f\u591a\u5c11\uff1f"), "facts": [], "wrong": [], "fabricated": [], "optional": [], "neg": True, "expect_ignore": True, "expected_response": "\u672a\u63d0\u53ca|\u4e0d\u77e5\u9053|\u6587\u6863\u4e2d|not mentioned|GDP"},
}


def call_with_retry(fn, *args, max_retries=5, **kwargs):
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"\n  [Retry {attempt+1}/{max_retries}] Error: {e}")
            time.sleep(3 * (attempt + 1))
    return None, ""


def init_indexes(rebuild=False):
    print("=" * 60)
    print("Initializing RAG index...")
    print("=" * 60)
    rag_coll_name = "rag_" + hashlib.md5("|".join(sorted(FILE_PATHS)).encode()).hexdigest()[:8]
    r_model, r_coll, r_bm25, r_docs, r_metas = prepare_index(
        FILE_PATHS, rag_coll_name, force_rebuild=rebuild
    )
    print(f"  RAG docs: {len(r_docs)}")

    print("\n" + "=" * 60)
    print("Initializing Graph RAG index...")
    print("=" * 60)
    g_coll_name = "graph_rag_" + hashlib.md5("|".join(sorted(FILE_PATHS)).encode()).hexdigest()[:8]
    g_model, g_coll, g_bm25, g_docs, g_metas, g_kg = prepare_graph_index(
        FILE_PATHS, g_coll_name, force_rebuild=rebuild
    )
    print(f"  Graph RAG docs: {len(g_docs)}, KG nodes: {g_kg.entity_graph.number_of_nodes()}, edges: {g_kg.entity_graph.number_of_edges()}")
    return (r_model, r_coll, r_bm25, r_docs, r_metas), (g_model, g_coll, g_bm25, g_docs, g_metas, g_kg)


def run_all_tests(rebuild=False):
    (r_model, r_coll, r_bm25, r_docs, r_metas), \
    (g_model, g_coll, g_bm25, g_docs, g_metas, g_kg) = init_indexes(rebuild=rebuild)

    results = {"rag": {}, "graph_rag": {}}
    total = (len(RAG_QUESTIONS) + len(GRAG_QUESTIONS)) * len(TEMPERATURES)
    done = 0

    for qid in RAG_QUESTIONS:
        q = QUESTIONS[qid]["q"]
        print(f"\n{'─'*60}")
        print(f"[RAG] {qid}: {q[:70]}")
        results["rag"][qid] = {"answers": {}}
        for t in TEMPERATURES:
            print(f"  T={t} ...", end=" ", flush=True)
            stream, sources = call_with_retry(
                answer_query_stream, q,
                r_model, r_coll, r_bm25, r_docs, r_metas,
                temperature=t
            )
            if stream is None:
                ans = "[ERROR]"
            else:
                ans = "".join(stream)
            results["rag"][qid]["answers"][str(t)] = ans
            done += 1
            print(f"done ({len(ans)} chars) [{done}/{total}]")

    for qid in GRAG_QUESTIONS:
        q = QUESTIONS[qid]["q"]
        print(f"\n{'─'*60}")
        print(f"[GraphRAG] {qid}: {q[:70]}")
        results["graph_rag"][qid] = {"answers": {}}
        for t in TEMPERATURES:
            print(f"  T={t} ...", end=" ", flush=True)
            stream, sources = call_with_retry(
                graph_query_stream, q,
                g_model, g_coll, g_bm25, g_docs, g_metas, g_kg,
                temperature=t
            )
            if stream is None:
                ans = "[ERROR]"
            else:
                ans = "".join(stream)
            results["graph_rag"][qid]["answers"][str(t)] = ans
            done += 1
            print(f"done ({len(ans)} chars) [{done}/{total}]")

    raw_path = os.path.join(WORKDIR, "plans", "temperature-test-raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n\nRaw answers saved -> {raw_path}")
    return results, r_model, r_coll, r_bm25, r_docs, r_metas, g_model, g_coll, g_bm25, g_docs, g_metas, g_kg


def build_contexts_for_questions(qids, model, coll, bm25, docs, metadatas):
    """Re-run retrieval for each question and store context for false-refusal detection."""
    from src.rag import retrieve_hybrid_with_sources, dynamic_top_k
    contexts = {}
    for qid in qids:
        q = QUESTIONS[qid]["q"]
        try:
            indices, _, scores = retrieve_hybrid_with_sources(q, model, coll, bm25, docs, metadatas)
            k = dynamic_top_k(scores)
            top_docs = [docs[i] for i in indices[:k]]
            contexts[qid] = "\n\n".join(top_docs)
        except Exception as e:
            contexts[qid] = ""
    return contexts


# ── scoring ──────────────────────────────────────────────────────────────────
def fact_hits(answer, facts):
    hits = 0
    for f in facts:
        if f.lower() in answer.lower():
            hits += 1
    return hits


def check_refuse(answer):
    refuse_kw = ["\u672a\u63d0\u53ca", "\u6ca1\u6709\u63d0\u53ca", "\u6ca1\u6709\u627e\u5230", "\u4e0d\u77e5\u9053", "\u6587\u6863\u4e2d\u672a",
                 "\u65e0\u6cd5\u627e\u5230", "\u4fe1\u606f\u4e0d\u8db3", "\u65e0\u6cd5\u56de\u7b54", "\u7b54\u4e0d\u4e86",
                 "not mentioned", "not found", "not provided", "don't know", "I don't know", "not available"]
    a_lower = answer.lower()
    for kw in refuse_kw:
        if kw.lower() in a_lower:
            return True
    return False


def check_negative_honest(answer, qid):
    qinfo = QUESTIONS[qid]
    if not qinfo.get("neg"):
        return True
    if check_refuse(answer):
        return True
    if qid == "NEG-01":
        fake_names = ["OpenWebText", "The Pile", "Common Crawl", "Wikipedia",
                      "RedPajama", "C4", "BookCorpus", "GitHub"]
        for name in fake_names:
            if name.lower() in answer.lower():
                return False
    elif qid == "NEG-02":
        import re
        if re.search(r'\d+[\s\u4e07\u4ebf]*\s*(\u5143|USD|CNY)', answer):
            return False
    return True


def compute_A_B_C_D(answer, qid, context=""):
    qinfo = QUESTIONS[qid]
    all_facts = list(qinfo["facts"]) + list(qinfo.get("optional", []))
    n_facts = max(len(all_facts), 1)

    hit   = fact_hits(answer, all_facts)
    wrong = sum(1 for f in qinfo.get("wrong", []) if f.lower() in answer.lower())
    fab   = sum(1 for f in qinfo.get("fabricated", []) if f.lower() in answer.lower())
    total = hit + wrong + fab

    is_refusal = check_refuse(answer)

    if total == 0:
        if is_refusal:
            # False-refusal check: are the expected facts present in retrieved context?
            ctx_hits = fact_hits(context, all_facts) if context else 0
            if qinfo.get("neg"):
                # Negative questions: correct to refuse → A=5
                A = 5
            elif ctx_hits > 0:
                # Context has the answer but model refused → severe penalty
                A = 1
            else:
                # Context also lacks the answer → can't blame the model for refusing
                A = 3
        else:
            A = 0  # no facts, not even a refusal
    else:
        ratio = hit / total
        if ratio >= 1.0:   A = 5
        elif ratio >= 0.8: A = 4
        elif ratio >= 0.6: A = 3
        elif ratio >= 0.3: A = 2
        else:               A = 1

    cov = hit / n_facts
    if cov >= 1.0:   B = 5
    elif cov >= 0.8: B = 4
    elif cov >= 0.6: B = 3
    elif cov >= 0.3: B = 2
    else:             B = 1

    C = 4  # default

    if qinfo.get("neg"):
        honest = check_negative_honest(answer, qid)
        D = 5 if honest else 1
    else:
        if fab == 0 and wrong == 0: D = 5
        elif fab == 0:               D = 4
        elif fab <= 2:               D = 3
        else:                        D = 2

    return {"A": A, "B": B, "C": C, "D": D, "hit": hit, "wrong": wrong, "fabricated": fab}


def compute_E(qid, scores_by_temp):
    a_scores  = [scores_by_temp[str(t)]["A"] for t in TEMPERATURES]
    hit_list  = [scores_by_temp[str(t)]["hit"] for t in TEMPERATURES if "hit" in scores_by_temp[str(t)]]
    std_a     = float(np.std(a_scores)) if len(a_scores) > 1 else 0
    hit_range = max(hit_list) - min(hit_list) if len(hit_list) > 1 else 0

    if std_a <= 0.50 and hit_range <= 1:
        return 5.0
    elif std_a <= 0.80 and hit_range <= 2:
        return 4.0
    elif hit_range > 2:
        low_hits = [scores_by_temp[str(t)]["hit"] for t in [0.0, 0.1, 0.3] if "hit" in scores_by_temp[str(t)]]
        if len(low_hits) >= 2 and max(low_hits) - min(low_hits) <= 1:
            return 3.0
        return 2.0
    return 3.0


def score_results(results, contexts_by_mode=None):
    """Score results, using pre-built contexts for false-refusal detection."""
    if contexts_by_mode is None:
        contexts_by_mode = {}

    scored = {"rag": {}, "graph_rag": {}}
    for mode in ["rag", "graph_rag"]:
        qids = RAG_QUESTIONS if mode == "rag" else GRAG_QUESTIONS
        ctx_map = contexts_by_mode.get(mode, {})
        for qid in qids:
            if qid not in results[mode]:
                continue
            scored[mode][qid] = {"answers": results[mode][qid]["answers"], "scores": {}}
            ctx = ctx_map.get(qid, "")
            for t in TEMPERATURES:
                ans = results[mode][qid]["answers"].get(str(t), "")
                s = compute_A_B_C_D(ans, qid, context=ctx)
                single = round(s["A"] * 0.30 + s["B"] * 0.20 + s["C"] * 0.10 + s["D"] * 0.25, 2)
                scored[mode][qid]["scores"][str(t)] = {
                    "A": s["A"], "B": s["B"], "C": s["C"], "D": s["D"], "single": single,
                    "hit": s["hit"], "wrong": s["wrong"], "fabricated": s["fabricated"],
                }

            E = compute_E(qid, scored[mode][qid]["scores"])
            scored[mode][qid]["E"] = round(E, 1)

            a_mean = np.mean([scored[mode][qid]["scores"][str(t)]["A"] for t in TEMPERATURES])
            b_mean = np.mean([scored[mode][qid]["scores"][str(t)]["B"] for t in TEMPERATURES])
            c_mean = np.mean([scored[mode][qid]["scores"][str(t)]["C"] for t in TEMPERATURES])
            d_mean = np.mean([scored[mode][qid]["scores"][str(t)]["D"] for t in TEMPERATURES])
            sq = round(a_mean * 0.30 + b_mean * 0.20 + c_mean * 0.10 + d_mean * 0.25 + E * 0.15, 2)
            scored[mode][qid]["score_question"] = sq
            scored[mode][qid]["notes"] = []
    return scored


def build_summary(scored):
    summary = {}
    for mode in ["rag", "graph_rag"]:
        qids = RAG_QUESTIONS if mode == "rag" else GRAG_QUESTIONS
        valid = [q for q in qids if q in scored[mode]]

        by_temp = {}
        for t in TEMPERATURES:
            vals = [scored[mode][q]["scores"][str(t)]["single"] for q in valid if str(t) in scored[mode][q]["scores"]]
            by_temp[str(t)] = round(float(np.mean(vals)), 2) if vals else 0.0

        overall_vals = [scored[mode][q]["score_question"] for q in valid if "score_question" in scored[mode][q]]
        overall = round(float(np.mean(overall_vals)), 2) if overall_vals else 0.0

        all_d = [scored[mode][q]["scores"][str(t)]["D"] for q in valid for t in TEMPERATURES if str(t) in scored[mode][q]["scores"]]
        hall_rate = round(sum(1 for d in all_d if d < 4) / max(len(all_d), 1), 3)

        all_ad = [(scored[mode][q]["scores"][str(t)]["A"], scored[mode][q]["scores"][str(t)]["D"])
                  for q in valid for t in TEMPERATURES if str(t) in scored[mode][q]["scores"]]
        ref_rate = round(sum(1 for a, d in all_ad if a == 0 and d == 5) / max(len(all_ad), 1), 3)

        best_t = max(by_temp, key=by_temp.get) if by_temp else "0.0"
        summary[mode] = {"scores_by_temperature": by_temp, "overall": overall, "best_temperature": best_t, "hallucination_rate": hall_rate, "refuse_rate": ref_rate}

    summary["comparison"] = {
        "rag_vs_graph_diff": round(abs(summary["rag"]["overall"] - summary["graph_rag"]["overall"]), 2),
        "rag_better_at":      ["\u57fa\u7840\u4e8b\u5b9e\u68c0\u7d22", "\u6570\u503c\u7cbe\u5ea6"],
        "graph_rag_better_at": ["\u8de8\u6587\u6863\u5b9e\u4f53\u5173\u8054", "\u591a\u8df3\u63a8\u7406"],
    }
    return summary


def main():
    print("Temperature Test Runner - deepseek-chat")
    print("Temps:", TEMPERATURES)

    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    raw_path = os.path.join(WORKDIR, "plans", "temperature-test-raw.json")
    if os.path.exists(raw_path) and not args.rebuild:
        print(f"Loading existing raw answers from {raw_path}")
        with open(raw_path, encoding="utf-8") as f:
            results = json.load(f)
        (r_model, r_coll, r_bm25, r_docs, r_metas), \
        (g_model, g_coll, g_bm25, g_docs, g_metas, g_kg) = init_indexes(rebuild=False)
    else:
        results, r_model, r_coll, r_bm25, r_docs, r_metas, g_model, g_coll, g_bm25, g_docs, g_metas, g_kg = run_all_tests(rebuild=False)

    print("\n\nBuilding retrieval contexts for false-refusal detection...")
    rag_ctx  = build_contexts_for_questions(RAG_QUESTIONS,  r_model, r_coll, r_bm25, r_docs, r_metas)
    g_rag_ctx = build_contexts_for_questions(GRAG_QUESTIONS, g_model, g_coll, g_bm25, g_docs, g_metas)
    contexts_by_mode = {"rag": rag_ctx, "graph_rag": g_rag_ctx}

    print("Scoring...")
    scored   = score_results(results, contexts_by_mode=contexts_by_mode)
    summary  = build_summary(scored)

    final = {
        "meta": {"test_date": "2026-07-02", "temperatures": TEMPERATURES, "model": "deepseek-chat", "files": FILE_PATHS},
        "results": scored,
        "summary": summary,
    }

    out_dir = os.path.join(WORKDIR, "plans")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "temperature-test-results.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)
    print(f"\nResults saved -> {out_path}")

    print("\nSUMMARY:")
    for mode in ["rag", "graph_rag"]:
        s = summary[mode]
        print(f"  {mode.upper():<12} overall={s['overall']:.2f}  best_T={s['best_temperature']}  hall_rate={s['hallucination_rate']:.3f}  ref_rate={s['refuse_rate']:.3f}")
    print(f"  DIFF={summary['comparison']['rag_vs_graph_diff']:.2f}")


if __name__ == "__main__":
    main()
