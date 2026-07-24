use pyo3::prelude::*;
use scraper::{Html, Selector};
use url::Url;
use std::time::Duration;
use futures::future::join_all;

#[pyclass]
#[derive(Clone)]
pub struct ScraperConfig {
    #[pyo3(get, set)]
    pub proxy: Option<String>,
    #[pyo3(get, set)]
    pub user_agent: String,
    #[pyo3(get, set)]
    pub timeout_sec: u64,
}

#[pymethods]
impl ScraperConfig {
    #[new]
    #[pyo3(signature = (proxy=None, user_agent=None, timeout_sec=15))]
    fn new(proxy: Option<String>, user_agent: Option<String>, timeout_sec: u64) -> Self {
        Self {
            proxy,
            user_agent: user_agent.unwrap_or_else(|| {
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36".to_string()
            }),
            timeout_sec,
        }
    }
}

async fn fetch_page(
    client: &reqwest::Client,
    url: &str,
) -> Result<String, reqwest::Error> {
    let resp = client.get(url).send().await?;
    resp.text().await
}

fn extract_results(html: &str, base_url: &str, query: &str) -> Vec<(String, String)> {
    let document = Html::parse_document(html);
    let host = match Url::parse(base_url) {
        Ok(u) => format!("{}://{}", u.scheme(), u.host_str().unwrap_or("")),
        Err(_) => return vec![],
    };

    let selectors = [
        "a.film-name",
        "a.ml-mask",
        ".item a",
        ".movie-card a",
        "h2 a",
        "h3 a",
    ];

    let query_lower = query.to_lowercase();
    let query_words: Vec<&str> = query_lower.split_whitespace().collect();

    for selector_str in selectors {
        let selector = match Selector::parse(selector_str) {
            Ok(s) => s,
            Err(_) => continue,
        };

        let mut found = Vec::new();
        for element in document.select(&selector) {
            let title = if selector_str == "a.ml-mask" || selector_str == "a.film-name" {
                element.value().attr("title")
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| element.text().collect::<String>())
            } else {
                element.text().collect::<String>()
            };

            let href = element.value().attr("href").unwrap_or("").to_string();
            
            let title = title.trim();
            if title.len() < 2 || title.len() > 100 {
                continue;
            }

            // Basic relevance check: at least one query word should be in the title
            let title_lower = title.to_lowercase();
            if !query_words.is_empty() && !query_words.iter().any(|&w| title_lower.contains(w)) {
                continue;
            }

            // Exclude common navigation links
            let lower_title = title.to_lowercase();
            let bad_words = ["home", "search", "menu", "nav", "login", "sign", "join", "privacy", "terms"];
            if bad_words.iter().any(|&w| lower_title == w || lower_title.contains(&format!(" {} ", w))) {
                continue;
            }

            let mut absolute_href = href;
            if absolute_href.starts_with('/') {
                absolute_href = format!("{}{}", host, absolute_href);
            }

            if absolute_href.starts_with("http") && !title.is_empty() {
                found.push((title.to_string(), absolute_href));
            }
        }

        if !found.is_empty() {
            found.truncate(15);
            return found;
        }
    }

    // Fallback to a[href] but with stricter filtering
    if let Ok(selector) = Selector::parse("a[href]") {
        let mut found = Vec::new();
        for element in document.select(&selector) {
            let title = element.text().collect::<String>();
            let title = title.trim();
            if title.len() < 3 || title.len() > 80 {
                continue;
            }

            let title_lower = title.to_lowercase();
            // Stricter relevance for fallback: title must contain at least 50% of query words
            let matches = query_words.iter().filter(|&w| title_lower.contains(w)).count();
            if matches == 0 || (query_words.len() > 1 && matches < (query_words.len() + 1) / 2) {
                continue;
            }

            let href = element.value().attr("href").unwrap_or("");
            if href.is_empty() || href.starts_with('#') || href.starts_with("javascript:") {
                continue;
            }

            let mut absolute_href = href.to_string();
            if absolute_href.starts_with('/') {
                absolute_href = format!("{}{}", host, absolute_href);
            }

            if absolute_href.starts_with("http") {
                found.push((title.to_string(), absolute_href));
            }
        }
        if !found.is_empty() {
            found.truncate(10);
            return found;
        }
    }

    vec![]
}

#[pyfunction]
fn search(
    py: Python<'_>,
    query: String,
    bases: Vec<String>,
    config: ScraperConfig,
) -> PyResult<Bound<'_, PyAny>> {
    let user_agent = config.user_agent.clone();
    let proxy = config.proxy.clone();
    let timeout = Duration::from_secs(config.timeout_sec);

    pyo3_asyncio::tokio::future_into_py(py, async move {
        let mut client_builder = reqwest::Client::builder()
            .user_agent(user_agent)
            .timeout(timeout);

        if let Some(p) = proxy {
            if let Ok(proxy_obj) = reqwest::Proxy::all(p) {
                client_builder = client_builder.proxy(proxy_obj);
            }
        }

        let client = match client_builder.build() {
            Ok(c) => c,
            Err(e) => return Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
        };

        let mut tasks = Vec::new();
        for base in bases {
            let q = query.clone();
            let c = client.clone();
            tasks.push(tokio::spawn(async move {
                // Manually encode query if urlencoding crate is not wanted, 
                // but urlencoding is standard for this.
                let url = format!("{}{}", base, percent_encoding::utf8_percent_encode(&q, percent_encoding::NON_ALPHANUMERIC));
                match fetch_page(&c, &url).await {
                    Ok(html) => extract_results(&html, &base, &q),
                    Err(_) => vec![],
                }
            }));
        }

        let mut all_results = Vec::new();
        let mut seen_urls = std::collections::HashSet::new();

        let joined_results = join_all(tasks).await;
        for res in joined_results {
            if let Ok(results) = res {
                for (title, url) in results {
                    if !seen_urls.contains(&url) {
                        seen_urls.insert(url.clone());
                        all_results.push((title, url));
                    }
                }
            }
        }

        Ok(all_results)
    })
}

#[pymodule]
fn _scraper(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(search, m)?)?;
    m.add_class::<ScraperConfig>()?;
    Ok(())
}
