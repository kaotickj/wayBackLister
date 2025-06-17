import requests
import re
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import os
import tempfile
import time
import random

# ANSI color codes for console output clarity
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"

def display_banner():
    banner = r"""
		    ▌ ▌      ▌        ▌  ▌  ▗    ▐        
		    ▌▖▌▝▀▖▌ ▌▛▀▖▝▀▖▞▀▖▌▗▘▌  ▄ ▞▀▘▜▀ ▞▀▖▙▀▖
   		    ▙▚▌▞▀▌▚▄▌▌ ▌▞▀▌▌ ▖▛▚ ▌  ▐ ▝▀▖▐ ▖▛▀ ▌  
		    ▘ ▘▝▀▘▗▄▘▀▀ ▝▀▘▝▀ ▘ ▘▀▀▘▀▘▀▀  ▀ ▝▀▘▘   
                                                                                                            
                     WaybackLister v2.1.2 by FR13ND0x7F
                    Modified and Improved by Kaotick Jay 
           Enhanced Directory Listing Detection Using Wayback Machine
    """
    print(banner)

def fetch_wayback_urls(domain, retries=3, backoff=5, timeout=(5, 30)):
    print(f"{YELLOW}[+] Querying Wayback Machine for {domain}...{RESET}")
    wayback_url = (
        f"https://web.archive.org/cdx/search/cdx?url=*.{domain}/*"
        f"&output=txt&fl=original&collapse=urlkey"
    )
    headers = {'User-Agent': 'WaybackLister/2.0'}

    for attempt in range(1, retries + 1):
        try:
            with requests.get(wayback_url, stream=True, headers=headers, timeout=timeout) as response:
                if 500 <= response.status_code < 600:
                    # Server-side error - trigger retry
                    raise requests.exceptions.HTTPError(f"Server error: {response.status_code}")
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as temp_file:
                    for line in response.iter_lines(decode_unicode=True):
                        if line.strip():
                            temp_file.write(line.strip() + "\n")
                    return temp_file.name

        except requests.exceptions.Timeout:
            print(f"{YELLOW}[!] Timeout occurred (Attempt {attempt}/{retries})... retrying in {backoff}s{RESET}")
        except requests.exceptions.HTTPError as e:
            print(f"{YELLOW}[!] Server error on attempt {attempt}/{retries}: {e}... retrying in {backoff}s{RESET}")
        except requests.exceptions.RequestException as e:
            print(f"{RED}[-] Error fetching data from Wayback Machine for {domain}: {e}{RESET}")
            break

        # Exponential backoff with jitter before next retry
        sleep_time = backoff * (2 ** (attempt - 1))
        jitter = sleep_time * 0.1
        time.sleep(sleep_time + (jitter * (2 * (random.random() - 0.5)))) 

    return None

def extract_paths_for_domain(temp_file_path, target_domain):
    unique_paths = set()
    with open(temp_file_path, "r", encoding="utf-8") as temp_file:
        for line in temp_file:
            url = line.strip()
            parsed_url = urlparse(url)
            if parsed_url.hostname == target_domain:
                path = parsed_url.path
                if path and path != "/":
                    unique_paths.add(path)
    return sorted(unique_paths)

def extract_subdomains(temp_file_path, domain):
    subdomains = set()
    domain_parts = domain.split(".")
    domain_suffix = "." + ".".join(domain_parts[-2:])
    
    with open(temp_file_path, "r", encoding="utf-8") as temp_file:
        for line in temp_file:
            url = line.strip()
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            
            if hostname and hostname.endswith(domain_suffix) and hostname != domain:
                subdomains.add(hostname)
    
    return sorted(subdomains)

def check_directory_listing(domain, path):
    protocols = ["http", "https"]
    patterns = [
        "Index of /",
        "Directory Listing for",
        "<title>Index of",
        "Parent Directory</a>",
        "Last modified</a>",
        "Name</a>",
        "Size</a>",
        "Description</a>"
    ]
    headers = {'User-Agent': 'WaybackLister/2.0'}
    
    for protocol in protocols:
        url = f"{protocol}://{domain}{path}"
        try:
            response = requests.get(url, timeout=5, headers=headers, allow_redirects=True)
            if response.status_code == 200:
                for pattern in patterns:
                    if pattern in response.text:
                        return url
        except requests.exceptions.RequestException:
            continue
    return None

def process_domain(domain, paths, threads):
    print(f"[+] Processing domain: {domain}")
    
    if not paths:
        print(f"[-] No unique paths found for {domain}.")
        return
    
    print(f"[+] Found {len(paths)} unique paths for {domain}. Checking for directory listings...")
    
    directory_listings = []
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(check_directory_listing, domain, path) for path in paths]
        for future in as_completed(futures):
            result = future.result()
            if result:
                directory_listings.append(result)
                print(f"{GREEN}[+] Directory Listing Found: {result}{RESET}")
    
    if directory_listings:
        print(f"\n[+] Summary of Directory Listings for {domain}:")
        for listing in directory_listings:
            print(f"  - {listing}")
    else:
        print(f"[-] No directory listings found for {domain}.")

def auto_discover_and_process(domain, threads):
    print(f"[+] Auto-discovering subdomains for {domain}...")
    temp_file_path = fetch_wayback_urls(domain)
    
    if not temp_file_path:
        print(f"[-] No archived URLs found for {domain}. Skipping.")
        return
    
    try:
        subdomains = extract_subdomains(temp_file_path, domain)
        domains_to_process = [domain] + subdomains
        
        print(f"[+] Found {len(domains_to_process)} targets to process:")
        for target in domains_to_process:
            print(f"  - {target}")
        
        for target_domain in domains_to_process:
            paths = extract_paths_for_domain(temp_file_path, target_domain)
            process_domain(target_domain, paths, threads)
    
    finally:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

def process_domains_from_file(file_path, threads):
    try:
        with open(file_path, "r") as file:
            domains = [line.strip() for line in file if line.strip()]
        
        for domain in domains:
            if not re.match(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$", domain):
                print(f"[-] Invalid domain format for {domain}. Skipping.")
                continue
            
            print(f"\n[+] Processing domain from file: {domain}")
            temp_file_path = fetch_wayback_urls(domain)
            
            if temp_file_path:
                try:
                    paths = extract_paths_for_domain(temp_file_path, domain)
                    process_domain(domain, paths, threads)
                finally:
                    os.unlink(temp_file_path)
    
    except FileNotFoundError:
        print(f"[-] File not found: {file_path}")

def main():
    display_banner()
    parser = argparse.ArgumentParser(description="WaybackLister v2.0 - Enhanced Directory Listing Detection")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-d", "--domain", help="Single target domain to scan (e.g., example.com)")
    group.add_argument("-f", "--file", help="File containing a list of domains to scan (one per line)")
    group.add_argument("-auto", help="Automatically discover and scan subdomains for the given domain")
    parser.add_argument("-t", "--threads", type=int, default=10, help="Number of threads (default: 10)")
    args = parser.parse_args()

    if args.domain:
        if not re.match(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$", args.domain):
            print(f"{RED}[-] Invalid domain format. Please enter a valid domain.{RESET}")
            return
        temp_file = fetch_wayback_urls(args.domain)
        if temp_file:
            try:
                paths = extract_paths_for_domain(temp_file, args.domain)
                process_domain(args.domain, paths, args.threads)
            finally:
                os.unlink(temp_file)
    
    elif args.file:
        process_domains_from_file(args.file, args.threads)
    
    elif args.auto:
        if not re.match(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$", args.auto):
            print(f"{RED}[-] Invalid domain format. Please enter a valid domain.{RESET}")
            return
        auto_discover_and_process(args.auto, args.threads)

if __name__ == "__main__":
    main()
