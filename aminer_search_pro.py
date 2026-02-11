import json
import requests
import os
from datetime import datetime
import re
import concurrent.futures


SERPER_KEY = "YOUR-SERPER-KEY"
search_url = "https://google.serper.dev/search"
aminer_search_url = "https://datacenter.aminer.cn/gateway/api/v3/paper/search/paper/SearchPro"
get_id_url = "https://datacenter.aminer.cn/gateway/api/v3/paper/get/by/arxiv/ids"
ref_url = "https://datacenter.aminer.cn/gateway/api/v3/paper/pub_relation"
AMINER_KEY = "YOUR-AMINER-KEY"


def aminer_pro_search(query, use_topic=True, year=None, size=100, offset=0):
    headers = {
        'Content-Type': 'application/json;charset=utf-8',
        'Authorization': f'Bearer {AMINER_KEY}'
    }
    data = {
        'use_topic': use_topic,
        'query': query,
        'size': size,
        'offset': offset
    }
    if year:
        data['end_year'] = year 
    else:
        data['end_year'] = 2025
    
    try:
        response = requests.post(aminer_search_url, headers=headers, data=json.dumps(data), timeout=(10, 30))
        if response.status_code != 200:
            print(f"请求失败，状态码: {response.status_code}, detail: {response.text}")
            return None
        if response is None:
            return None
        try:
            data = response.json().get('data', {}).get('data', [])
            ids = [item['id'] for item in data if 'id' in item]
            return ids
        except Exception as e:
            print(f"解析Aminer返回内容失败 (不是有效的JSON), detail: {e}")
            return None
    except Exception as e:
        print(f"Exception occurred during AMiner search")
        return None
