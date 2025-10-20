import requests

def http_get(url: str, timeout: int = 10) -> dict:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Request failed: {str(e)}")