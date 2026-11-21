use std::collections::{HashMap, HashSet};

const STOP: &[&str] = &[
    "the", "is", "are", "was", "were", "an", "of", "to", "in", "on", "and", "or", "for", "with",
    "what", "which", "who", "how", "does", "do", "did", "it", "its", "this", "that", "be", "as",
    "at", "by", "from", "me", "my", "about", "can", "you", "tell",
];
const K1: f64 = 1.5;
const B: f64 = 0.75;

/// Lowercase alphanumeric tokens, 2+ chars, stop words removed.
pub fn tokenize(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let flush = |cur: &mut String, out: &mut Vec<String>| {
        if cur.chars().count() >= 2 && !STOP.contains(&cur.as_str()) {
            out.push(std::mem::take(cur));
        } else {
            cur.clear();
        }
    };
    for c in s.chars() {
        if c.is_alphanumeric() {
            cur.extend(c.to_lowercase());
        } else {
            flush(&mut cur, &mut out);
        }
    }
    flush(&mut cur, &mut out);
    out
}

/// Sliding window over words: `size` words per chunk, `overlap` words shared.
pub fn chunk(text: &str, size: usize, overlap: usize) -> Vec<String> {
    let words: Vec<&str> = text.split_whitespace().collect();
    let size = size.max(1);
    let step = size.saturating_sub(overlap).max(1);
    let mut out = Vec::new();
    let mut start = 0;
    while start < words.len() {
        let end = (start + size).min(words.len());
        out.push(words[start..end].join(" "));
        if end == words.len() {
            break;
        }
        start += step;
    }
    out
}

/// BM25 over the given chunks. Returns (index, score) best-first, score > 0 only.
pub fn rank(query: &str, chunks: &[&str], k: usize) -> Vec<(usize, f64)> {
    let docs: Vec<Vec<String>> = chunks.iter().map(|c| tokenize(c)).collect();
    let n = docs.len() as f64;
    if docs.is_empty() {
        return vec![];
    }
    let avg = docs.iter().map(|d| d.len()).sum::<usize>() as f64 / n;
    let mut df: HashMap<&str, usize> = HashMap::new();
    for d in &docs {
        for t in d.iter().collect::<HashSet<_>>() {
            *df.entry(t.as_str()).or_insert(0) += 1;
        }
    }
    let q: HashSet<String> = tokenize(query).into_iter().collect();
    let mut scored: Vec<(usize, f64)> = docs
        .iter()
        .enumerate()
        .map(|(i, d)| {
            let len = d.len() as f64;
            let mut s = 0.0;
            for t in &q {
                let tf = d.iter().filter(|x| *x == t).count() as f64;
                if tf == 0.0 {
                    continue;
                }
                let f = *df.get(t.as_str()).unwrap_or(&0) as f64;
                let idf = (1.0 + (n - f + 0.5) / (f + 0.5)).ln();
                let norm = if avg > 0.0 { 1.0 - B + B * len / avg } else { 1.0 };
                s += idf * (tf * (K1 + 1.0)) / (tf + K1 * norm);
            }
            (i, s)
        })
        .filter(|(_, s)| *s > 0.0)
        .collect();
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.0.cmp(&b.0)));
    scored.truncate(k);
    scored
}

/// Share of unique answer tokens that also appear in the context (cheap groundedness).
pub fn overlap(answer: &str, context: &str) -> f64 {
    let a: HashSet<String> = tokenize(answer).into_iter().collect();
    if a.is_empty() {
        return 0.0;
    }
    let c: HashSet<String> = tokenize(context).into_iter().collect();
    a.intersection(&c).count() as f64 / a.len() as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizes_and_drops_stopwords() {
        assert_eq!(tokenize("The Pasta, is al-dente!"), vec!["pasta", "al", "dente"]);
    }

    #[test]
    fn chunks_with_overlap() {
        let t = "a1 b2 c3 d4 e5 f6";
        assert_eq!(chunk(t, 4, 2), vec!["a1 b2 c3 d4", "c3 d4 e5 f6"]);
        assert!(chunk("", 4, 1).is_empty());
    }

    #[test]
    fn ranks_relevant_first() {
        let r = rank("boil pasta", &["bake bread", "boil the pasta eight minutes"], 3);
        assert_eq!(r[0].0, 1);
        assert_eq!(r.len(), 1);
    }

    #[test]
    fn overlap_fraction() {
        assert!((overlap("pasta sauce", "pasta water") - 0.5).abs() < 1e-9);
    }
}
