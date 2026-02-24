from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import logging

logging.basicConfig(level=logging.DEBUG)

def test():
    url = "https://chshare.link/scorecard/feI1yC"
    
    session = requests.Session(impersonate="chrome120")
    
    print("Fetching first URL...")
    response = session.get(url, timeout=30)
    print("First URL Status:", response.status_code)
    print("First URL Final URL:", response.url)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Check if we got bot-blocked on first request
    page_title = soup.title.string if soup.title else ""
    if "Cloudflare" in page_title or "Attention Required" in page_title or "Just a moment" in page_title:
        print("BLOCKED ON FIRST URL. Title:", page_title)
        return
        
    real_url = response.url
    if real_url.endswith("/scorecard"):
        pass
    else:
        og_url_tag = soup.find("meta", property="og:url")
        if og_url_tag and og_url_tag.get("content"):
            og_url = og_url_tag["content"]
            if not og_url.startswith("http"):
                og_url = "https://" + og_url
            real_url = og_url + "/scorecard" if not og_url.endswith("/scorecard") else og_url
        else:
            real_url = real_url.rstrip("/") + "/scorecard"
            
    print("Real URL to fetch:", real_url)
    
    if response.url != real_url and not response.url.endswith("/scorecard"):
        print("Fetching scorecard URL...")
        # Sometimes sending Referer is required by anti-bot
        response = session.get(real_url, headers={"Referer": response.url}, timeout=30)
        print("Scorecard Status:", response.status_code)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_title = soup.title.string if soup.title else ""
        if "Cloudflare" in page_title or "Attention Required" in page_title or "Just a moment" in page_title:
            print("BLOCKED ON SCORECARD URL. Title:", page_title)
            print("Response headers:", response.headers)
            return
            
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        print("NO __NEXT_DATA__")
    else:
        print("SUCCESS")

if __name__ == "__main__":
    test()
