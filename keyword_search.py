import os
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from aminer_search_pro import aminer_pro_search
import requests
from openai import OpenAI
from models import Agent

selector = Agent("checkpoints/pasa-7b-selector")
SEARCHPRO_URL = "https://datacenter.aminer.cn/gateway/api/v3/paper/search/paper/SearchPro"
AMINER_TOKEN = 'YOUR-AMINER-KEY'
AMINER_INFO_URL = "https://datacenter.aminer.cn/gateway/open_platform/api/paper/info"
client = OpenAI(api_key="YOUR-DEEPSEEK-API-KEY", base_url="https://api.deepseek.com")


def aminer_get_paper_info_batch(paper_ids):
    if not paper_ids:
        return []

    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": AMINER_TOKEN
    }

    try:
        resp = requests.post(
            AMINER_INFO_URL,
            headers=headers,
            json={"ids": paper_ids},
            timeout=15
        )
        if resp.status_code != 200:
            print(f"{resp.status_code}")
            return []

        resp_json = resp.json()
        if not resp_json.get("success"):
            print(f"{resp_json.get('msg')}")
            return []

        papers_data = resp_json.get("data", [])
        return papers_data

    except Exception as e:
        print(f"{e}")
        return []


def refine_keywords_with_deepseek(general_topic, section_topic, initial_keywords_list):
    question = (
        f"Based on the GENERAL TOPIC and the section topic below, generate exactly 10 **new** research keywords.\n"
        f"- The keywords must be **method-oriented or theme-oriented**, NOT entity names.\n"
        f"- The 10 generated keywords must be **all different from each other**.\n"
        f"- The generated keywords must also be **completely different from the initial keyword list**.\n"
        f"- Treat synonyms, paraphrases, or conceptually equivalent terms as duplicates; avoid them.\n"
        f"- Output ONLY the 10 keywords, separated by commas.\n\n"
        f"General Topic\n{general_topic}\n\n"
        f"Section Topic:\n{section_topic}\n\n"
        f"Initial Keywords (must NOT appear again):\n{initial_keywords_list}\n"
        f"Focus on concepts related to **semantic drift, query refinement, KL divergence**, and **feedback mechanisms** in search processes.\n"
        f"Your task is to **use KL divergence to avoid getting stuck in local semantic optima** during the search process. When performing retrieval, measure the **semantic deviation** by calculating the KL divergence between the current retrieval distribution and the target semantic manifold. If the system falls into a suboptimal semantic region, you must identify the degree of semantic drift and adjust the query accordingly to **correct semantic errors** and **guide the search towards a more relevant and optimal region**. The goal is to ensure that the search does not get trapped in a local minimum, but instead iteratively refines the search space, leading to a more comprehensive and relevant set of results."
        f"Output format must be keywords separated by commas"
    )
         

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a concise summarizer."},
            {"role": "user", "content": question},
        ],
        stream=False
    )

    resp_text = response.choices[0].message.content.strip()
    new_keywords = [kw.strip() for kw in resp_text.split(",") if kw.strip()] # The keywords generated from general topic
    print(f"Refined {len(new_keywords)} Keywords for section")

    return new_keywords


def select_paper_scores(aminer_papers, keywords_list):
    if not aminer_papers or 'data' not in aminer_papers or aminer_papers['data'] is None:
        print("aminer_papers has no data")
        return []

  
    paper_dict = {}
    for paper in aminer_papers['data']:
        pid = paper['id']
        if pid not in paper_dict:
            paper_dict[pid] = paper 

    prompts = []
    pid_list = []
    for pid, paper in paper_dict.items():
        prompt = (
            "You are an elite researcher, conducting research on "
            f"{keywords_list}\n"
            "Evaluate whether the following paper fully satisfies the detailed requirements of the user query "
            "and provide your reasoning. Ensure that your decision and reasoning are consistent.\n\n"
            f"Searched Paper:\nTitle: {paper['title']}\nAbstract: {paper['abstract']}\n\n"
            f"User Query: {keywords_list}\n\n"
            "Output format: Decision: True/False\nReason:...\nDecision:"
        )
        prompts.append(prompt)
        pid_list.append(pid)

   
    batch_size = 5
    all_scores = []
    for i in range(0, len(prompts), batch_size):
        batch_prompts = prompts[i:i + batch_size]
        all_scores.extend(selector.infer_score(batch_prompts))


    selected_paper_scores = [{"id": pid, "score": score} for pid, score in zip(pid_list, all_scores)]
    return selected_paper_scores



def aminer_kw_search(keyword, category_topic, general_topic):
    search_results = aminer_pro_search(keyword)
    if not search_results:
        return None

    search_results = [pid for pid in search_results if pid]
    if not search_results:
        return None

    details = aminer_get_paper_info_batch(search_results)

    papers_for_selector = []
    for detail in details:
        if not detail:
            continue
        papers_for_selector.append({
            "id": detail["_id"],
            "title": detail.get("title") or detail.get("title_zh", ""),
            "abstract": detail.get("abstract") or detail.get("abstract_zh", "")
        })

    if not papers_for_selector:
        return None

    aminer_papers = {"data": papers_for_selector}

    selected_id_scores = select_paper_scores(
        aminer_papers,
        [keyword, category_topic]
    )

    well_fit_scores = sorted(
        [item for item in selected_id_scores if item["score"] > 0.01],
        key=lambda x: x["score"],
        reverse=True
    )

    if not well_fit_scores:
        return None

    cleaned_items = [
        {"id": item["id"], "score": item["score"]}
        for item in well_fit_scores
    ]

    return {
        "keyword": keyword,
        "items": cleaned_items
    }
    
def keywords_adding(general_topic, paper_category, current_paper_ids, ground_truth_papers,max_time = 5):

    total_new_keywords = []
    total_new_ids = []
    non_hit_keywords = []
    
    hit_keywords_infor = {}
    process_num = 0
    for key, value in paper_category.items():
        print(f"Processing section: {process_num} / {len(paper_category)}")
        process_num += 1
        initial_keywords_list = value.get("keywords", [])
        useful_section_keywords = []
        collected_items = []
        section_non_hit_keywords = []
        

        with ThreadPoolExecutor(max_workers = 10) as executor:
            futures = [executor.submit(aminer_kw_search, kw, key, general_topic) for kw in initial_keywords_list]
            
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue  
                
                kw = result["keyword"] 
                hited = False  
                if result:   
                    for item in result["items"]:
                        collected_items.append(item)
                        if item["id"] in ground_truth_papers:
                            hit_keywords_infor.setdefault(kw, []).append(item["id"])
                            hited = True
                            useful_section_keywords.append(result["keyword"])
                if not hited:
                    section_non_hit_keywords.append(kw)
        
        non_hit_keywords.append(section_non_hit_keywords)

        id_best = {}
        for item in collected_items:
            pid, score = item["id"], item["score"]
            if pid not in id_best or score > id_best[pid]:
                id_best[pid] = score
        
        dedup_items = [{"id": pid, "score": score} for pid, score in id_best.items()]

        max_len = len(paper_category[key].get("ids", [])) * max_time
        dedup_items_sorted = sorted(dedup_items, key=lambda x: x["score"], reverse=True)

        if len(dedup_items_sorted) > max_len:
            dedup_items_sorted = dedup_items_sorted[:max_len]

        top_items = dedup_items_sorted
        final_ids_set = set(item["id"] for item in top_items)

        for gt_id in ground_truth_papers:
            if gt_id in id_best: 
                final_ids_set.add(gt_id)

        total_new_ids.append(list(final_ids_set))


        new_keywords = refine_keywords_with_deepseek(general_topic, key, initial_keywords_list) # refine keywords
        total_new_keywords.append(new_keywords)

    return total_new_keywords, total_new_ids, non_hit_keywords, hit_keywords_infor

         

        