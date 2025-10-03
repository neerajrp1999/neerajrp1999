import os
import re
import requests
import tempfile
import subprocess
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs

GITHUB_USERNAME = "neerajrp1999"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
API_BASE = "https://api.github.com"
GRAPHQL_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
README_PATH = "README.md"
REQUEST_TIMEOUT = 15

def get_all_repos():
    """Return list of repos (uses authenticated /user/repos when token exists)."""
    repos = []
    page = 1
    per_page = 100
    while True:
        if GITHUB_TOKEN:
            url = f"{API_BASE}/user/repos"
            params = {"per_page": per_page, "page": page, "affiliation": "owner,collaborator"}
            r = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        else:
            url = f"{API_BASE}/users/{GITHUB_USERNAME}/repos"
            params = {"per_page": per_page, "page": page, "type": "owner"}
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if r.status_code != 200:
            print(f"Warning: repo fetch returned {r.status_code}: {r.text}")
            break

        data = r.json()
        if not data:
            break
        repos.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return repos


def get_basic_stats():
    if GITHUB_TOKEN:
        r = requests.get(f"{API_BASE}/user", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        user_data = r.json() if r.status_code == 200 else {}
    else:
        r = requests.get(f"{API_BASE}/users/{GITHUB_USERNAME}", timeout=REQUEST_TIMEOUT)
        user_data = r.json() if r.status_code == 200 else {}

    repos = get_all_repos()
    public_repos = sum(1 for r in repos if not r.get("private"))
    private_repos = sum(1 for r in repos if r.get("private"))
    total_repos = public_repos + private_repos
    followers = user_data.get("followers", 0)
    stars = sum(r.get("stargazers_count", 0) for r in repos)
    repo_urls = [r.get("clone_url") for r in repos if r.get("clone_url")]
    return total_repos, public_repos, private_repos, followers, stars, repo_urls


def get_yearly_contributions(username):
    if not GITHUB_TOKEN:
        return 0
    today = datetime.utcnow().date()
    last_year = today - timedelta(days=365)
    query = """
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    vars = {"login": username, "from": f"{last_year}T00:00:00Z", "to": f"{today}T23:59:59Z"}
    try:
        r = requests.post(GRAPHQL_URL, json={"query": query, "variables": vars}, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    except Exception:
        return 0


def parse_owner_repo_from_clone_url(clone_url):
    """Return (owner, repo) for typical GitHub clone URLs."""
    if clone_url.endswith(".git"):
        clone_url = clone_url[:-4]
    if clone_url.startswith("git@"):
        path = clone_url.split(":", 1)[1]
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    else:
        parsed = urlparse(clone_url)
        path = parsed.path.lstrip("/")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None


def get_commit_count_api(owner, repo, author):
    """Try to estimate commit count using the REST API by inspecting Link header."""
    try:
        url = f"{API_BASE}/repos/{owner}/{repo}/commits"
        params = {"author": author, "per_page": 1}
        r = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            link = r.headers.get("Link", "")
            if link:
                m = re.search(r'&page=(\d+)>;\s*rel="last"', link)
                if m:
                    return int(m.group(1))
            data = r.json()
            return len(data)
    except Exception:
        pass
    return 0


def analyze_repo(repo_url, username, full_clone=False, shallow_depth=50):
    commits = added = removed = 0
    owner, repo = parse_owner_repo_from_clone_url(repo_url)
    try:
        with tempfile.TemporaryDirectory() as td:
            clone_cmd = ["git", "clone"]
            if not full_clone:
                clone_cmd += ["--depth", str(shallow_depth)]
            clone_cmd += [repo_url, td]
            subprocess.run(clone_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            try:
                r1 = subprocess.run(["git", "rev-list", "--count", "HEAD", "--author", username], cwd=td,
                                    capture_output=True, text=True, check=False)
                commits = int(r1.stdout.strip() or 0)
            except Exception:
                commits = 0
            try:
                r2 = subprocess.run(["git", "log", "--author", username, "--pretty=tformat:", "--numstat"],
                                    cwd=td, capture_output=True, text=True, check=False)
                a = r2.stdout.splitlines()
                for line in a:
                    parts = line.split("\t")
                    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                        added += int(parts[0])
                        removed += int(parts[1])
            except Exception:
                pass
    except Exception:
        pass

    if commits == 0 and owner and repo:
        commits = get_commit_count_api(owner, repo, username)

    return commits, added, removed


def build_readme(username, total_repos, public_repos, private_repos, stars, followers, contributions, total_commits, total_added, total_removed):
    loc = total_added - total_removed
    readme = f"""<table>
<tr>
<td valign="top">
<pre>
{username} ————————————————————————————————————————————————
. OS: ........................ Windows 10, Linux, Android 14
. Uptime: .................... 2+ years (Professional Experience)
. Host: ...................... 64 Squares LLC, Pune.
. Kernel: .................... Full-Stack Software Engineer | Backend-Focused | Cloud-Native Systems
. IDE: ....................... IntelliJ IDEA 2025.2.1, VSCode 1.95.1

. Core Expertise: ............ Full-Stack Web Development, API Design, Scalable Architecture, 
. Core Expertise: ............ System Design, Cloud Deployments, Performance Optimization,
. Core Expertise: ............ Agile Delivery, and End-to-End Product Development

. Languages.Programming: ..... Java, Python, JavaScript/TypeScript, C, C++
. Frontend: .................. React JS/TS, Redux, Tailwind CSS, HTML, CSS
. Backend: ................... Node.js, Express, Spring Boot, Sequelize, JPA, Hibernate, Redis, REST APIs
. Databases: ................. MySQL, PostgreSQL, NoSQL
. Cloud/DevOps: .............. AWS, Git, Linux, CI/CD Pipelines
. Other Skills: .............. Data Structures & Algorithms, Problem Solving, Debugging, System Design
. Learning: .................. Go, Rust

. Languages.Real: ............ English, Hindi, Marathi

. Hobbies.Software: .......... Software Development, Building Tools, Automation, Open Source Projects
. Hobbies.Hardware: .......... Overclocking, Undervolting

 — Open Source ——————————————————————————————————————————
. <a href="https://www.npmjs.com/package/react-canvas-img" target="_blank" rel="noopener noreferrer">react-canvas-img</a>

— Contact ——————————————————————————————————————————————
. Email.Personal: ............ <a href="mailto:neerajrp1999@gmail.com">neerajrp1999@gmail.com</a>
. Email.Work: ................ <a href="mailto:neerajrp1999@zohomail.in">neerajrp1999@zohomail.in</a>
. LinkedIn: .................. <a href="https://www.linkedin.com/in/neerajprajapati309" target="_blank" rel="noopener noreferrer">neerajprajapati309</a>
. Leetcode: .................. <a href="https://leetcode.com/neerajrp1999" target="_blank" rel="noopener noreferrer">neerajrp1999</a>

 — GitHub Stats ——————————————————————————————————————————
. Total Repos: ............... {total_repos} (Public: {public_repos}, Private: {private_repos})
. Stars: ..................... {stars}
. Followers: ................. {followers}
. Contributions (Last Year) .. {contributions}
. Commits: ................... {total_commits}
. Lines of Code: ............. {loc:,} ({total_added:,}++, {total_removed:,}-- )

</pre>
</td>
</tr>
</table>
"""
    return readme


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-loc", action="store_true", help="Skip LOC/commit scanning (fast)")
    parser.add_argument("--full-clone", action="store_true", help="Perform full clone for each repo (slow, accurate)")
    parser.add_argument("--max-repos", type=int, default=None, help="Limit number of repos to analyze")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for repo analysis")
    args = parser.parse_args()

    print("Fetching GitHub metadata...")
    total_repos, public_repos, private_repos, followers, stars, repo_urls = get_basic_stats()
    contributions = get_yearly_contributions(GITHUB_USERNAME)

    total_commits = total_added = total_removed = 0

    if not args.no_loc and repo_urls:
        to_process = repo_urls[:args.max_repos] if args.max_repos else repo_urls
        print(f"Analyzing {len(to_process)} repositories (workers={args.workers}) - this may take a while...")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(analyze_repo, url, GITHUB_USERNAME, args.full_clone): url for url in to_process}
            for fut in as_completed(futures):
                commits, added, removed = fut.result()
                total_commits += commits
                total_added += added
                total_removed += removed
    else:
        if args.no_loc:
            print("Skipping LOC/commit computation (--no-loc specified).")
        else:
            print("No repositories to analyze.")

    readme_md = build_readme(GITHUB_USERNAME, total_repos, public_repos, private_repos, stars, followers, contributions, total_commits, total_added, total_removed)

    with open(README_PATH, "w", encoding="utf-8") as fh:
        fh.write(readme_md)

    print("✅ README.md updated.")
    print(f"Stats: repos={total_repos} stars={stars} followers={followers} contributions={contributions}")
    print(f"Commits={total_commits}, LOC added={total_added:,}, removed={total_removed:,}, net={total_added - total_removed:,}")


if __name__ == "__main__":
    import argparse
    main()
