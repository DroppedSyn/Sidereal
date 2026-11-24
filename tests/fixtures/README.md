# Test fixtures

Recorded once from the VM on **2026-11-24** (M0) with User-Agent
`Sidereal/0.1 (+personal news reader)`, then trimmed: at most 20 entries (MSRC: 40) and at most
100 KB per feed, original structure kept. Very long text inside an entry (full HTML bodies) is cut
and ends with ` [truncated]`. Tests never fetch anything (plan rule 7); re-record by hand only.

## feeds/

| file | source URL | notes |
|---|---|---|
| `azure-updates.xml` | https://www.microsoft.com/releasecommunications/api/v2/azure/rss | 20 items |
| `azure-blog.xml` | https://azure.microsoft.com/en-us/blog/feed/ | 10 items (all the feed had) |
| `tc-azure-networking.xml` | https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=AzureNetworkingBlog | 20 |
| `tc-azure-netsec.xml` | …`board.id=AzureNetworkSecurityBlog` | 20 |
| `tc-entra.xml` | …`board.id=microsoft-entra-blog` | 20 |
| `tc-defender-cloud.xml` | …`board.id=MicrosoftDefenderCloudBlog` | 20 |
| `tc-sentinel.xml` | …`board.id=MicrosoftSentinelBlog` | 20 |
| `tc-azure-architecture.xml` | …`board.id=AzureArchitectureBlog` | 20; original 2.5 MB, bodies truncated |
| `ms-security-blog.xml` | https://www.microsoft.com/en-us/security/blog/feed/ | 10 |
| `msrc-update-guide.xml` | https://api.msrc.microsoft.com/update-guide/rss | 40 of 5,700+: 20 matching the default product regex (Exchange, SharePoint, AD, NTLM, Kerberos, DNS, RDP, Windows Kernel, Azure DevOps), 5 Chromium, 15 other non-matching (.NET, Visio, Xbox…); UTF-8 BOM removed, `Z` dates |
| `cisa-kev.json` | https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json | 20 newest vulnerabilities, 6 of them Microsoft; `count` set to 20 |
| `cisa-advisories.xml` | https://www.cisa.gov/cybersecurity-advisories/all.xml | 20; two-digit years (`Tue, 24 Nov 26 12:00:00 +0000`) |
| `bleepingcomputer.xml` | https://www.bleepingcomputer.com/feed/ | 15 (all) |
| `thehackernews.xml` | https://feeds.feedburner.com/TheHackersNews | 20 |
| `krebs.xml` | https://krebsonsecurity.com/feed/ | 10; served as `application/rss+xml` on 2026-11-24 (the plan's probe saw `text/html`) |
| `darkreading.xml` | https://www.darkreading.com/rss.xml | 20 |
| `sans-isc.xml` | https://isc.sans.edu/rssfeed_full.xml | 10 |
| `schneier.xml` | https://www.schneier.com/feed/atom/ | 10, Atom |
| `cloudflare-blog.xml` | https://blog.cloudflare.com/rss/ | 20 |
| `csa-blog.xml` | https://cloudsecurityalliance.org/feed | 20 |
| `hn-cloud-sec.json` | https://hn.algolia.com/api/v1/search_by_date?query=azure&tags=story&numericFilters=points%3E%3D40 | one query (`azure`), first 20 hits |
| `tc-dead-board.xml` | https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=Identity | untrimmed: a valid RSS channel titled "Resource Not Found" with no items (error feed, plan §6.4) |
| `msrc-blog-html.html` | https://msrc.microsoft.com/blog/feed | HTML (a JS app), not a feed; first ~30 KB |

## pages/

| file | source URL | notes |
|---|---|---|
| `tc-azure-networking-route-maps.html` | https://techcommunity.microsoft.com/t5/azure-networking-blog/control-hybrid-path-selection-with-route-maps-in-azure-route/ba-p/4575141 | 614 KB → 99 KB: `script` (except JSON-LD), `style`, `svg`, `noscript`, `iframe` and inline `style` attributes removed; trafilatura still extracts ~13.6k chars |
| `bleepingcomputer-rackspace-spot.html` | https://www.bleepingcomputer.com/news/security/rackspace-shuts-down-spot-cloud-platform-after-security-breach/ | 90 KB → 72 KB, same trimming; trafilatura extracts ~3.7k chars |
