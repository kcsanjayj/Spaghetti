//! Hardware probe: what can this machine run? std-only, no dependencies.
//! Output is plain `key=value` lines so Python can parse it in three lines.
use std::process::Command;

fn run(cmd: &str, args: &[&str]) -> Option<String> {
    let out = Command::new(cmd).args(args).output().ok()?;
    if !out.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn ram_mb(os: &str) -> u64 {
    match os {
        "linux" => std::fs::read_to_string("/proc/meminfo")
            .ok()
            .and_then(|t| t.lines().find(|l| l.starts_with("MemTotal:")).map(str::to_string))
            .and_then(|l| l.split_whitespace().nth(1).and_then(|v| v.parse::<u64>().ok()))
            .map(|kb| kb / 1024)
            .unwrap_or(0),
        "macos" => run("sysctl", &["-n", "hw.memsize"]).and_then(|v| v.parse::<u64>().ok()).map(|b| b / 1_048_576).unwrap_or(0),
        "windows" => run(
            "powershell",
            &["-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
        )
        .and_then(|v| v.parse::<u64>().ok())
        .map(|b| b / 1_048_576)
        .unwrap_or(0),
        _ => 0,
    }
}

/// (gpu name, dedicated VRAM in MB). NVIDIA via nvidia-smi; Apple Silicon is reported separately.
fn gpu() -> (String, u64) {
    if let Some(line) = run("nvidia-smi", &["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]) {
        if let Some(first) = line.lines().next() {
            let mut p = first.split(',');
            let name = p.next().unwrap_or("").trim().to_string();
            let vram = p.next().and_then(|v| v.trim().parse().ok()).unwrap_or(0);
            return (name, vram);
        }
    }
    (String::new(), 0)
}

pub fn probe() -> String {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let (gpu_name, vram) = gpu();
    let unified = os == "macos" && arch == "aarch64";
    format!(
        "os={os}\narch={arch}\ncores={cores}\nram_mb={}\ngpu={gpu_name}\nvram_mb={vram}\nunified={}\n",
        ram_mb(os),
        unified as u8
    )
}
