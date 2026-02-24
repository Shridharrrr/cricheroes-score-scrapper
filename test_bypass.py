from curl_cffi import requests
from bs4 import BeautifulSoup
import json

def test():
    # URL provided by user
    url = "https://chshare.link/scorecard/feI1yC"
    
    # Try using a Session instead of requests.get to keep cookies/headers
    session = requests.Session(impersonate="chrome120")
    
    print("Fetching first URL...")
    response = session.get(url, timeout=30)
    print("Status:", response.status_code)
    print("Final URL:", response.url)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 2. Figure out the Scorecard URL safely
    real_url = response.url
    if not real_url.endswith("/scorecard"):
        og_url_tag = soup.find("meta", property="og:url")
        if og_url_tag and og_url_tag.get("content"):
            og_url = og_url_tag["content"]
            # Sometimes og:url is just 'cricheroes.in/scorecard/123/Match' without https://
            if not og_url.startswith("http"):
                og_url = "https://" + og_url
            real_url = og_url + "/scorecard" if not og_url.endswith("/scorecard") else og_url
        else:
            real_url = real_url.rstrip("/") + "/scorecard"
            
    print("Real URL to fetch:", real_url)
    
    # 3. Navigate to the actual scorecard page if needed
    if response.url != real_url and not response.url.endswith("/scorecard"):
        print("Fetching scorecard URL...")
        response = session.get(real_url, timeout=30)
        print("Scorecard Status:", response.status_code)
        
    soup = BeautifulSoup(response.text, 'html.parser')

    # 4. Extract the __NEXT_DATA__ JSON script
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        print("Failed to fetch scorecard JSON. The page loaded, but the __NEXT_DATA__ block is missing.")
    else:
        json_text = next_data_tag.string
        try:
            data = json.loads(json_text)
            print("Successfully extracted __NEXT_DATA__ keys:")
            print(data.keys())
        except Exception as e:
            print(f"Error parsing JSON: {e}")

if __name__ == "__main__":
    test()
