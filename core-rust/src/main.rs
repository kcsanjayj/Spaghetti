//! spaghetti-core: the prep station.
//!
//! Tiny CLI, std-only. Python talks to it over stdin/stdout with plain text,
//! so there is no FFI, no JSON parser and no dependency to audit.
//!
//!   chunk   <size> <overlap>   stdin: text            -> chunks separated by \x1e
//!   rank    <k>                stdin: query\nchunk\x1echunk... -> "index<TAB>score" lines
//!   overlap                    stdin: answer\x1econtext -> fraction (0..1)
//!   hw                         (no input)             -> key=value hardware lines
//!
//! Every algorithm has a twin in backend/spaghetti/engine/python_engine.py;
//! tests/test_engine.py proves both give the same results.

mod hw;
mod text;

use std::io::{self, Read, Write};

const RS: char = '\x1e';

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).expect("stdin must be UTF-8");

    let out = match args.first().map(String::as_str) {
        Some("chunk") => {
            let size = arg(&args, 1, 120);
            let overlap = arg(&args, 2, 20);
            text::chunk(&input, size, overlap).join(&RS.to_string())
        }
        Some("rank") => {
            let k = arg(&args, 1, 4);
            let (query, rest) = input.split_once('\n').unwrap_or((&input, ""));
            let chunks: Vec<&str> = if rest.is_empty() { vec![] } else { rest.split(RS).collect() };
            text::rank(query, &chunks, k)
                .iter()
                .map(|(i, s)| format!("{}\t{:.6}", i, s))
                .collect::<Vec<_>>()
                .join("\n")
        }
        Some("overlap") => {
            let (answer, context) = input.split_once(RS).unwrap_or((&input, ""));
            format!("{:.6}", text::overlap(answer, context))
        }
        Some("hw") => hw::probe(),
        Some("version") => env!("CARGO_PKG_VERSION").to_string(),
        _ => {
            eprintln!("usage: spaghetti-core chunk|rank|overlap|hw|version");
            std::process::exit(2);
        }
    };
    io::stdout().write_all(out.as_bytes()).unwrap();
}

fn arg(args: &[String], i: usize, default: usize) -> usize {
    args.get(i).and_then(|v| v.parse().ok()).unwrap_or(default)
}
