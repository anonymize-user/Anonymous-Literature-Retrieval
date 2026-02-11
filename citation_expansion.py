import json
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import Agent
from openai import OpenAI
from time import sleep
import time

token = "YOUR-AMINER-KEY"  
session = requests.Session()
session.headers.update({"Authorization": f"Bearer {token}"})
selector = Agent("checkpoints/pasa-7b-selector")
DETAIL_URL = "https://datacenter.aminer.cn/gateway/open_platform/api/paper/detail"
client = OpenAI(api_key="YOUR-DEEPSEEK-API-KEY", base_url="https://api.deepseek.com")
    

def select_paper_scores(aminer_papers, keywords_list, general_topic, batch_size = 10): # pasa generates scores by api
    if not aminer_papers:
        print("aminer_papers has no data")
        return []
    
    user_query = (
        f"Give me papers which shows that fit the topic {general_topic} well"
    )

    selected_paper_scores = []

    total = len(aminer_papers)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = aminer_papers[start : end]

        titles = [p["title"] for p in batch]
        abstracts = [p.get("abstract", "") for p in batch]
        ids = [p["id"] for p in batch]

        prompts = [
            (
                "You are an elite researcher, conducting research on "
                f"{general_topic}\n"
                "Evaluate whether the following paper fully satisfies the detailed requirements "
                "of the user query and provide your reasoning. Ensure consistency.\n\n"
                f"Searched Paper:\nTitle: {title}\nAbstract: {abstract}\n\n"
                f"User Query: {user_query}\n\n"
                "Output format: Decision: True/False\nReason:...\nDecision:"
            )
            for title, abstract in zip(titles, abstracts)
        ]

        scores = selector.infer_score(prompts)

        for pid, title, score in zip(ids, titles, scores):
            selected_paper_scores.append({
                "id": pid,
                "title": title,
                "score": score
            })
            print(f"Paper: {title}\nScore: {score}\n")

    selected_paper_scores.sort(key=lambda x: x["score"], reverse=True)

    return selected_paper_scores


def id_to_title(paper_ids):
    url = "https://datacenter.aminer.cn/gateway/api/v3/paper/detail/batch"

    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": "YOUR-AMINER-KEY"  
    }

    params = {
        "ids": paper_ids
    }
    try:
        response = requests.post(url, json = params, headers = headers, timeout = 20)
        if response.status_code == 200:
            data = response.json()
            paper_list = data.get("data", [])

            if paper_list:
                infors = []
                for paper in paper_list:
                    paper_infor = {
                        "id": paper["_id"],
                        "title": paper["title"],
                        "abstract": paper.get("abstract", "")
                    }
                    infors.append(paper_infor)
                    
                return infors
            else:
                return None        
        else:
            print(f"Request failed: {response.status_code}, Return content: {response.text}")
            return None
    except Exception as e:
        print(f"Exception occurred while fetching paper ID: {e}")
        return None


def fetch_citations(paper_id, url):
    
    final_papers = []
    params = {
    "cited": paper_id,
    "offset": 0,
    "size": 7
    }
    try:
        response = session.get(url, params = params, timeout = 20)
        if response.status_code == 200:
            data = response.json()
            if len(data["data"]) != 0:
                for cited in data["data"]:
                    final_papers.append(cited["ref"])
    except Exception as e:
        pass    

    params = {
    "ref": paper_id,
    "offset": 0,
    "size": 10
    }

    try:
        response = session.get(url, params = params, timeout = 20) 
        if response.status_code == 200:
            data = response.json()            
            if len(data["data"]) != 0:
                for citing in data["data"]:
                    final_papers.append(citing["cited"])
    except Exception:
        pass

    final_papers_set = set(final_papers)
    final_papers = list(final_papers_set)
    if len(final_papers) == 0:
        pass
    final_result = {
        "paper": paper_id,
        "final_result": final_papers
    }
    return final_result

def chunk_list(lst, chunk_size = 100):  # This is the function that we used to split the list 
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size] 


def citation_adding(current_paper_ids, ground_truth_num, general_topic, initial_valid_keywords, ground_truth_papers, max_time = 5):
    url = "https://datacenter.aminer.cn/gateway/api/v3/paper/pub_relation"  
    useful_paper_ids = {}
    hit_paper_ids = [] 
    non_hit_papers = []
    max_worker = 15 
    count = 0    
    set_citation_papers = set()

    start = time.time()

    with ThreadPoolExecutor(max_workers = max_worker)as executor:
        futures = [executor.submit(fetch_citations, pid, url) for pid in current_paper_ids]
        for future in as_completed(futures): 
            result = future.result()
            hited = False
            if result:
                searched_paper_ids = result["final_result"]
                for id in searched_paper_ids:
                    if id in ground_truth_papers:
                        hited = True
                        hit_paper_ids.append(id)
                        useful_paper_ids.setdefault(result["paper"], []).append(id)
                if not hited:
                    non_hit_papers.append(result["paper"])
                set_citation_papers.update(searched_paper_ids)
                count += 1
    
    set_citation_papers = list(set_citation_papers)
    print(f"Successfully cited proportion{count / len(current_paper_ids)}")
    end = time.time()
    print(f"Citation first step (fetch_citation) time: {end - start}")
    sleep(2)


    selected_ids = []
    paper_infors = []

    chunk_papers_list = list(chunk_list(set_citation_papers))
    
    start = time.time()
    with ThreadPoolExecutor(max_workers = 15) as executor:
        futures = [executor.submit(id_to_title, batch) for batch in chunk_papers_list]
        for future in as_completed(futures):
            paper_infor = future.result()
            if paper_infor is not None:
                paper_infors.extend(paper_infor)

    print(f"Total fetched citation papers: {len(paper_infors)}")
    end = time.time()
    print(f"Citation second step (id_to_title) time: {end - start}")
    sleep(2)


    start = time.time()
    selected_id_scores = select_paper_scores(paper_infors, initial_valid_keywords, general_topic)
    well_fit_scores = sorted(
        [item for item in selected_id_scores if item["score"] > 0.01],
        key = lambda x: x["score"],
        reverse = True
    )

    selected_ids = [item["id"] for item in well_fit_scores]
    end = time.time()
    print(f"Citation third step (select_paper_scores) time: {end - start}")
   
    if len(selected_ids) >= ground_truth_num * max_time:
        selected_ids = selected_ids[ :ground_truth_num * max_time]
    
    for id in current_paper_ids:
        if id in ground_truth_papers:
            selected_ids.append(id)
    selected_ids.extend(hit_paper_ids)
    selected_ids = list(set(selected_ids))
    return selected_ids, non_hit_papers, useful_paper_ids
    