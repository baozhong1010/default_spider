from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from spider.config.models import PaginationConfig, RequestConfig


@dataclass
class RequestTask:
    url: str
    method: str
    headers: Dict[str, str]
    params: Dict[str, Any]
    data: Optional[Union[Dict[str, Any], str]]
    json: Optional[Union[Dict[str, Any], List[Any]]]


def build_list_request_tasks(entry_urls, request_cfg, pagination_cfg):
    # type: (List[str], RequestConfig, PaginationConfig) -> List[RequestTask]
    tasks = []  # type: List[RequestTask]
    mode = pagination_cfg.mode

    if mode == "none":
        for url in entry_urls:
            tasks.append(
                RequestTask(
                    url=url,
                    method=request_cfg.method,
                    headers=dict(request_cfg.headers),
                    params=dict(request_cfg.params),
                    data=request_cfg.data,
                    json=request_cfg.json_body,
                )
            )
        return tasks

    for page in range(pagination_cfg.start_page, pagination_cfg.end_page + 1):
        for url in entry_urls:
            if mode == "page_param":
                params = dict(request_cfg.params)
                params[pagination_cfg.page_param] = page
                task_url = url
            elif mode == "url_template":
                params = dict(request_cfg.params)
                task_url = pagination_cfg.url_template.format(page=page, base_url=url)
            else:
                params = dict(request_cfg.params)
                task_url = url

            tasks.append(
                RequestTask(
                    url=task_url,
                    method=request_cfg.method,
                    headers=dict(request_cfg.headers),
                    params=params,
                    data=request_cfg.data,
                    json=request_cfg.json_body,
                )
            )
    return tasks
